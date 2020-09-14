from __future__ import absolute_import, print_function, unicode_literals

import elliottlib
from elliottlib import constants, logutil, Runtime, bzutil, openshiftclient, errata
LOGGER = logutil.getLogger(__name__)
from elliottlib.cli import cli_opts
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import green_prefix, green_print, red_print

import click
pass_runtime = click.make_pass_decorator(Runtime)
import datetime
import re


@cli.command("find-bugs", short_help="Find or add MODIFED/VERIFIED bugs to ADVISORY")
@click.option("--add", "-a", 'advisory',
              default=False, metavar='ADVISORY',
              help="Add found bugs to ADVISORY. Applies to bug flags as well (by default only a list of discovered bugs are displayed)")
@use_default_advisory_option
@click.option("--mode",
              required=True,
              type=click.Choice(['list', 'sweep', 'diff', 'qe']),
              default='list',
              help='Mode to use to find bugs')
@click.option("--status", 'status',
              multiple=True,
              required=False,
              default=['MODIFIED', 'VERIFIED', 'ON_QA'],
              type=click.Choice(constants.VALID_BUG_STATES),
              help="Status of the bugs")
@click.option("--id", metavar='BUGID', default=None,
              multiple=True, required=False,
              help="Bugzilla IDs to add, required for LIST mode.")
@click.option("--cve-trackers",
              required=False,
              is_flag=True,
              help='Include CVE trackers in sweep mode')
@click.option("--from-diff", "--between",
              required=False,
              nargs=2,
              help="Two payloads to compare against")
@click.option("--flag", metavar='FLAG',
              required=False, multiple=True,
              help="Optional flag to apply to found bugs [MULTIPLE]")
@click.option("--report",
              required=False,
              is_flag=True,
              help="Output a detailed report of the found bugs")
@click.option("--into-default-advisories",
              is_flag=True,
              help='attaches bugs found to their correct default advisories, e.g. operator-related bugs go to "extras" instead of the default "image", bugs filtered into "none" are not attached at all.')
@click.option("--noop", "--dry-run",
              is_flag=True,
              default=False,
              help="Don't change anything")
@pass_runtime
def find_bugs_cli(runtime, advisory, default_advisory_type, mode, status, id, cve_trackers, from_diff, flag, report, into_default_advisories, noop):
    """Find Red Hat Bugzilla bugs or add them to ADVISORY. Bugs can be
"swept" into the advisory either automatically (--mode sweep), or by
manually specifying one or more bugs using --mode list and the --id option.
Use cases are described below:

    Note: Using --id without --add is basically pointless

SWEEP: For this use-case the --group option MUST be provided. The
--group automatically determines the correct target-releases to search
for bugs claimed to be fixed, but not yet attached to advisories.

LIST: The --group option is not required if you are specifying bugs
manually. Provide one or more --id's for manual bug addition. In LIST
mode you must provide a list of IDs to attach with the --id option.

DIFF: For this use case, you must provide the --between option using two
URLs to payloads.

QE: Find MODIFIED bugs for the target-releases, and set them to ON_QA.
The --group option MUST be provided. Cannot be used in combination
with --into-default-advisories, --add, --into-default-advisories

Using --use-default-advisory without a value set for the matching key
in the build-data will cause an error and elliott will exit in a
non-zero state. Use of this option silently overrides providing an
advisory with the --add option.

    Automatically add bugs with target-release matching 3.7.Z or 3.7.0
    to advisory 123456:

\b
    $ elliott --group openshift-3.7 find-bugs --mode sweep --add 123456

    List bugs that WOULD be added to an advisory and have set the bro_ok flag on them (NOOP):

\b
    $ elliott --group openshift-3.7 find-bugs --mode sweep --flag bro_ok

    Attach bugs to their correct default advisories, e.g. operator-related bugs go to "extras" instead of the default "image":

\b
    $ elliott --group=openshift-4.4 find-bugs --mode=sweep --into-default-advisories

    Add two bugs to advisory 123456. Note that --group is not required
    because we're not auto searching:

\b
    $ elliott find-bugs --mode list --id 8675309 --id 7001337 --add 123456

    Automatically find bugs for openshift-4.1 and attach them to the
    rpm advisory defined in ocp-build-data:

\b
    $ elliott --group=openshift-4.1 --mode sweep --use-default-advisory rpm

    Find bugs for 4.6 that are in MODIFIED state, and set them to ON_QA:

\b
    $ elliott --group=openshift-4.6 --mode qe
"""
    if mode != 'list' and len(id) > 0:
        raise click.BadParameter("Combining the automatic and manual bug attachment options is not supported")

    if mode == 'list' and len(id) == 0:
        raise click.BadParameter("When using mode=list, you must provide a list of bug IDs")

    if mode == 'payload' and not len(from_diff) == 2:
        raise click.BadParameter("If using mode=payload, you must provide two payloads to compare")

    if sum(map(bool, [advisory, default_advisory_type, into_default_advisories])) > 1:
        raise click.BadParameter("Use only one of --use-default-advisory, --add, or --into-default-advisories")

    if mode == 'qe' and sum(map(bool, [advisory, default_advisory_type, into_default_advisories])) > 0:
        raise click.BadParameter("--mode=qe does not operate on an advisory. Do not specify any of `--use-default-advisory`, `--add`, or `--into-default-advisories`")

    runtime.initialize()
    bz_data = runtime.gitdata.load_data(key='bugzilla').data
    bzapi = bzutil.get_bzapi(bz_data)

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    if mode == 'sweep' or mode == 'qe':
        if mode == 'qe':
            status = ['MODIFIED']
        green_prefix(f"Searching for bugs with status {' '.join(status)} and target release(s):")
        click.echo(" {tr}".format(tr=", ".join(bz_data['target_release'])))
        bugs = bzutil.search_for_bugs(bz_data, status, filter_out_security_bugs=not(cve_trackers), verbose=runtime.debug)
    elif mode == 'list':
        bugs = [bzapi.getbug(i) for i in cli_opts.id_convert(id)]
    elif mode == 'diff':
        click.echo(runtime.working_dir)
        bug_id_strings = openshiftclient.get_bug_list(runtime.working_dir, from_diff[0], from_diff[1])
        bugs = [bzapi.getbug(i) for i in bug_id_strings]

    # Some bugs should goes to CPaaS so we should ignore them
    m = re.match(r"rhaos-(\d+).(\d+)", runtime.branch)  # extract OpenShift version from the branch name. there should be a better way...
    if not m:
        raise ElliottFatalError(f"Unable to determine OpenShift version from branch name {runtime.branch}.")
    major_version = int(m[1])
    minor_version = int(m[2])

    def _filter_bugs(bugs):  # returns a list of bugs that should be processed
        r = []
        ignored_repos = set()  # GitHub repos that should be ignored
        if major_version == 4 and minor_version == 5:
            # per https://issues.redhat.com/browse/ART-997: these repos should have their release-4.5 branches ignored by ART:
            ignored_repos = {
                "https://github.com/openshift/aws-ebs-csi-driver",
                "https://github.com/openshift/aws-ebs-csi-driver-operator",
                "https://github.com/openshift/cloud-provider-openstack",
                "https://github.com/openshift/csi-driver-nfs",
                "https://github.com/openshift/csi-driver-manila-operator"
            }
        for bug in bugs:
            external_links = [ext["type"]["full_url"].replace("%id%", ext["ext_bz_bug_id"]) for ext in bug.external_bugs]  # https://github.com/python-bugzilla/python-bugzilla/blob/7aa70edcfea9b524cd8ac51a891b6395ca40dc87/bugzilla/_cli.py#L750
            public_links = [runtime.get_public_upstream(url)[0] for url in external_links]  # translate openshift-priv org to openshift org when comparing to filter (i.e. prow may link to a PR on the private org).
            # if a bug has 1 or more public_links, we should ignore the bug if ALL of the public_links are ANY of `ignored_repos`
            if public_links and all(map(lambda url: any(map(lambda repo: url != repo and url.startswith(repo), ignored_repos)), public_links)):
                continue
            r.append(bug)
        return r

    if len(id) == 0:  # unless --id is given, we should ignore bugs that don't belong to ART. e.g. some bugs should go to CPaaS
        filtered_bugs = _filter_bugs(bugs)
        green_prefix(f"Found {len(filtered_bugs)} bugs ({len(bugs) - len(filtered_bugs)} ignored):")
        bugs = filtered_bugs
    else:
        green_prefix("Found {} bugs:".format(len(bugs)))
    click.echo(" {}".format(", ".join([str(b.bug_id) for b in bugs])))

    if mode == 'qe':
        for bug in bugs:
            bzutil.set_state(bug, 'ON_QA', noop=noop)

    if len(flag) > 0:
        for bug in bugs:
            for f in flag:
                if noop:
                    click.echo(f'Would have updated bug {bug.id} by setting flag {f}')
                    continue
                bug.updateflags({f: "+"})

    if report:
        green_print("{:<8s} {:<25s} {:<12s} {:<7s} {:<10s} {:60s}".format("ID", "COMPONENT", "STATUS", "SCORE", "AGE", "SUMMARY"))
        for bug in bugs:
            created_date = datetime.datetime.strptime(str(bug.creation_time), '%Y%m%dT%H:%M:%S')
            days_ago = (datetime.datetime.today() - created_date).days
            click.echo("{:<8d} {:<25s} {:<12s} {:<7s} {:<3d} days   {:60s} ".format(bug.id,
                                                                                    bug.component,
                                                                                    bug.status,
                                                                                    bug.cf_pm_score if hasattr(bug, "cf_pm_score") else '?',
                                                                                    days_ago,
                                                                                    bug.summary[:60]))

    if advisory and not default_advisory_type:  # `--add ADVISORY_NUMBER` should respect the user's wish and attach all available bugs to whatever advisory is specified.
        errata.add_bugs_with_retry(advisory, bugs, noop=noop)
        return

    # If --use-default-advisory or --into-default-advisories is given, we need to determine which bugs should be swept into which advisory.
    # Otherwise we don't need to sweep bugs at all.
    if not (into_default_advisories or default_advisory_type):
        return
    impetus_bugs = {}  # key is impetus ("rpm", "image", "extras"), value is a set of bug IDs.
    # @lmeyer: simple and stupid would still be keeping the logic in python, possibly with config flags for branched logic. until that logic becomes too ugly to keep in python, i suppose..
    if major_version < 4:  # for 3.x, all bugs should go to the rpm advisory
        impetus_bugs["rpm"] = set(bugs)
    else:  # for 4.x
        # optional operators bugs should be swept to the "extras" advisory, while other bugs should be swept to "image" advisory.
        # a way to identify operator-related bugs is by its "Component" value. temporarily hardcode here until we need to move it to ocp-build-data.
        extra_components = {"Logging", "Service Brokers", "Metering Operator", "Node Feature Discovery Operator"}  # we will probably find more
        impetus_bugs["extras"] = {b for b in bugs if b.component in extra_components}
        impetus_bugs["image"] = {b for b in bugs if b.component not in extra_components}

    if default_advisory_type and impetus_bugs.get(default_advisory_type):
        errata.add_bugs_with_retry(advisory, impetus_bugs[default_advisory_type], noop=noop)
    elif into_default_advisories:
        for impetus, bugs in impetus_bugs.items():
            if bugs:
                errata.add_bugs_with_retry(runtime.group_config.advisories[impetus], bugs, noop=noop)
