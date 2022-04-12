import json
import re
import click
from datetime import datetime, timezone
from typing import List, Set

from elliottlib.assembly import assembly_issues_config
from elliottlib.bzutil import BugzillaBugTracker, BugTracker, Bug
from elliottlib import (Runtime, bzutil, constants, errata, logutil)
from elliottlib.cli.common import (cli, find_default_advisory,
                                   use_default_advisory_option)
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import green_prefix, green_print, red_prefix, yellow_print, chunk

pass_runtime = click.make_pass_decorator(Runtime)

LOGGER = logutil.getLogger(__name__)


class FindBugsMode:
    def __init__(self, status: List):
        self.status = set(status)

    def include_status(self, status: List):
        self.status |= set(status)

    def exclude_status(self, status: List):
        self.status -= set(status)

    def search(self, bug_tracker_obj: BugTracker, verbose: bool = False):
        return bug_tracker_obj.search(
            self.status,
            verbose=verbose
        )


class FindBugsSweep(FindBugsMode):
    def __init__(self):
        super().__init__(status={'MODIFIED', 'ON_QA', 'VERIFIED'})


class FindBugsQE(FindBugsMode):
    def __init__(self):
        super().__init__(
            status={'MODIFIED'}
        )


class FindBugsBlocker(FindBugsMode):
    def __init__(self):
        super().__init__(
            status={'NEW', 'ASSIGNED', 'POST', 'MODIFIED', 'ON_DEV', 'ON_QA'}
        )

    def search(self, bug_tracker_obj: BugTracker, verbose: bool = False):
        return bug_tracker_obj.blocker_search(
            self.status,
            verbose=verbose
        )


@cli.command("find-bugs", short_help="Find or add MODIFIED/VERIFIED bugs to ADVISORY")
@click.option("--add", "-a", 'advisory',
              type=int, metavar='ADVISORY',
              help="Add found/listed bugs to ADVISORY")
@use_default_advisory_option
@click.option("--mode",
              required=True,
              type=click.Choice(['sweep', 'qe', 'blocker']),
              default='blocker',
              help='Mode to use to find bugs')
@click.option("--check-builds",
              required=False,
              is_flag=True,
              help='In sweep mode, add bugs only if corresponding builds attached to advisory')
@click.option("--include-status", 'include_status',
              multiple=True,
              default=None,
              required=False,
              type=click.Choice(constants.VALID_BUG_STATES),
              help="Include bugs of this status")
@click.option("--exclude-status", 'exclude_status',
              multiple=True,
              default=None,
              required=False,
              type=click.Choice(constants.VALID_BUG_STATES),
              help="Exclude bugs of this status")
@click.option("--cve-trackers",
              required=False,
              default=None,
              is_flag=True,
              help='Include CVE trackers when searching for bugs')
@click.option("--report",
              required=False,
              is_flag=True,
              help="Output a detailed report of the found bugs")
@click.option('--output', '-o',
              required=False,
              type=click.Choice(['text', 'json', 'slack']),
              default='text',
              help='Applies chosen format to --report output')
@click.option("--into-default-advisories",
              is_flag=True,
              help='Attaches bugs found to their correct default advisories, e.g. operator-related bugs go to '
                   '"extras" instead of the default "image", bugs filtered into "none" are not attached at all.')
@click.option('--brew-event', type=click.INT, required=False,
              help='Only in sweep mode: SWEEP bugs that have changed to the desired status before the Brew event')
@click.option("--noop", "--dry-run",
              is_flag=True,
              default=False,
              help="Don't change anything")
@pass_runtime
def find_bugs_cli(runtime: Runtime, advisory, default_advisory_type, mode, check_builds, include_status, exclude_status,
                  cve_trackers, report, output, into_default_advisories, brew_event, noop):
    """Find OCP bugs and (optional) add them to ADVISORY. Bugs can be
"swept" into advisories automatically (--mode sweep).
Use cases are described below:

SWEEP: For this use-case the --group option MUST be provided. The
--group automatically determines the correct target-releases to search
for bugs claimed to be fixed, but not yet attached to advisories.
--check-builds flag forces bug validation with attached builds to rpm advisory.
It assumes builds have been attached and only attaches bugs with matching builds.
default --status: ['MODIFIED', 'ON_QA', 'VERIFIED']

QE: Find MODIFIED bugs for the target-releases, and set them to ON_QA.
The --group option MUST be provided. Cannot be used in combination
with --add, --use-default-advisory, --into-default-advisories, --exclude-status.

BLOCKER: List active blocker bugs for the target-releases.
The --group option MUST be provided. Cannot be used in combination
with --add, --use-default-advisory, --into-default-advisories.
default --status: ['NEW', 'ASSIGNED', 'POST', 'MODIFIED', 'ON_DEV', 'ON_QA']
Use --exclude_status to filter out from default status list.

Using --use-default-advisory without a value set for the matching key
in the build-data will cause an error and elliott will exit in a
non-zero state. Use of this option silently overrides providing an
advisory with the --add option.

    List bugs that WOULD be swept into advisories (NOOP):

\b
    $ elliott --group openshift-4.8 --assembly 4.8.32 find-bugs --mode sweep

    Sweep bugs for an assembly into the advisories defined

\b
    $ elliott -g openshift-4.8 --assembly 4.8.32 find-bugs --mode sweep --into-default-advisories

    Sweep rpm bugs into the rpm advisory defined

\b
    $ elliott -g openshift-4.8 --assembly 4.8.32 find-bugs --mode sweep --use-default-advisory rpm


    Find bugs for 4.6 that are in MODIFIED state, and set them to ON_QA:

\b
    $ elliott -g openshift-4.6 --mode qe

    Find blocker bugs for 4.6 - output in report format:
\b
    $ elliott -g openshift-4.6 --mode blocker --report
"""
    count_advisory_attach_flags = sum(map(bool, [advisory, default_advisory_type, into_default_advisories]))

    if count_advisory_attach_flags > 1:
        raise click.BadParameter("Use only one of --use-default-advisory, --add, or --into-default-advisories")

    if mode == 'qe' and exclude_status:
        raise click.BadParameter("--exclude_status not supported with mode qe")

    if mode in ['qe', 'blocker'] and count_advisory_attach_flags > 0:
        raise click.BadParameter("Mode does not operate on an advisory. Do not specify any of "
                                 "`--use-default-advisory`, `--add`, or `--into-default-advisories`")

    if cve_trackers:
        LOGGER.warning('--cve-trackers is deprecated. cve trackers are now included by default in all '
                       'searches.')

    runtime.initialize(mode="both")

    bz_config = BugzillaBugTracker.get_config(runtime)
    bugzilla = BugzillaBugTracker(bz_config)

    # filter out bugs ART does not manage
    m = re.match(r"rhaos-(\d+).(\d+)", runtime.branch)
    if not m:
        raise ElliottFatalError(f"Unable to determine OpenShift version from branch name {runtime.branch}.")
    major_version = int(m[1])
    minor_version = int(m[2])

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    if mode == 'sweep':
        find_bugs_obj = FindBugsSweep()
    elif mode == 'qe':
        find_bugs_obj = FindBugsQE()
    elif mode == 'blocker':
        find_bugs_obj = FindBugsBlocker()

    find_bugs_obj.include_status(include_status)
    find_bugs_obj.exclude_status(exclude_status)

    if output == 'text':
        green_prefix(f"Searching for bugs with status {' '.join(find_bugs_obj.status)} and target release(s):")
        click.echo(" {tr}".format(tr=", ".join(bugzilla.target_release())))

    bugs = find_bugs_obj.search(bug_tracker_obj=bugzilla, verbose=runtime.debug)

    sweep_cutoff_timestamp = get_sweep_cutoff_timestamp(runtime, cli_brew_event=brew_event)
    if sweep_cutoff_timestamp:
        green_print(f"Filtering bugs that have changed ({len(bugs)}) to one of the desired statuses before the "
                    f"cutoff time"
                    f" {datetime.utcfromtimestamp(sweep_cutoff_timestamp)}...")
        qualified_bugs = []
        for chunk_of_bugs in chunk(bugs, constants.BUG_LOOKUP_CHUNK_SIZE):
            b = bzutil.filter_bugs_by_cutoff_event(bugzilla.client(), chunk_of_bugs, find_bugs_obj.status,
                                                   sweep_cutoff_timestamp)
            qualified_bugs.extend(b)
        click.echo(f"{len(qualified_bugs)} of {len(bugs)} bugs are qualified for the cutoff time {datetime.utcfromtimestamp(sweep_cutoff_timestamp)}...")
        bugs = qualified_bugs

    # Loads included/excluded bugs from assembly config
    issues_config = assembly_issues_config(runtime.get_releases_config(), runtime.assembly)
    # JIRA issues are not supported yet. Only loads issues with integer IDs.
    included_bug_ids: Set[int] = {int(issue["id"]) for issue in issues_config.include if isinstance(issue["id"], int) or issue["id"].isdigit()}
    excluded_bug_ids: Set[int] = {int(issue["id"]) for issue in issues_config.exclude if isinstance(issue["id"], int) or issue["id"].isdigit()}
    if included_bug_ids & excluded_bug_ids:
        raise ValueError(f"The following bugs are defined in both 'include' and 'exclude': {included_bug_ids & excluded_bug_ids}")
    if included_bug_ids:
        yellow_print(f"The following bugs will be additionally included because they are explicitly defined in the assembly config: {included_bug_ids}")
        included_bugs = bugzilla.get_bugs(included_bug_ids)
        bugs.extend(included_bugs)
    if excluded_bug_ids:
        yellow_print(f"The following bugs will be excluded because they are explicitly defined in the assembly config: {excluded_bug_ids}")
        bugs = [bug for bug in bugs if bug.id not in excluded_bug_ids]

    if output == 'text':
        green_prefix(f"Found {len(bugs)} bugs: ")
        click.echo(", ".join(sorted(str(b.id) for b in bugs)))

    if mode == 'qe':
        for bug in bugs:
            bzutil.set_state(bug, 'ON_QA', noop=noop, comment_for_release=f"{major_version}.{minor_version}")

    if report:
        print_report(bugs, output)

    if advisory and not default_advisory_type:  # `--add ADVISORY_NUMBER` should respect the user's wish and attach all available bugs to whatever advisory is specified.
        errata.add_bugs_with_retry(advisory, bugs, noop=noop)
        return

    # If --use-default-advisory or --into-default-advisories is given, we need to determine which bugs should be swept into which advisory.
    # Otherwise we don't need to sweep bugs at all.
    if not (into_default_advisories or default_advisory_type):
        return

    # key is impetus ("rpm", "image", "extras"), value is a set of bug IDs.
    impetus_bugs = {
        "rpm": set(),
        "image": set(),
        "extras": set()
    }

    # @lmeyer: simple and stupid would still be keeping the logic in python,
    # possibly with config flags for branched logic.
    # until that logic becomes too ugly to keep in python, i suppose..
    if major_version < 4:  # for 3.x, all bugs should go to the rpm advisory
        impetus_bugs["rpm"] = set(bugs)
    else:  # for 4.x
        # sweep rpm cve trackers into "rpm" advisory
        rpm_bugs = {}
        if mode == 'sweep':
            rpm_bugs = bzutil.get_valid_rpm_cves(bugs)
            green_prefix("RPM CVEs found: ")
            click.echo(sorted(b.id for b in rpm_bugs))

            if rpm_bugs:
                # if --check-builds flag is set
                # only attach bugs that have corresponding brew builds attached to rpm advisory
                if check_builds:
                    click.echo("Validating bugs with builds attached to the rpm advisory")
                    attached_builds = errata.get_advisory_nvrs(runtime.group_config.advisories["rpm"])
                    packages = attached_builds.keys()
                    not_found = []
                    for bug, package_name in rpm_bugs.items():
                        if package_name not in packages:
                            not_found.append((bug.id, package_name))
                        else:
                            click.echo(f"Build found for #{bug.id}, {package_name}")
                            impetus_bugs["rpm"].add(bug)

                    if not_found:
                        red_prefix("RPM CVE Warning: ")
                        click.echo("The following CVE (bug, package) were found but not attached, because no corresponding brew builds were found attached to the rpm advisory. First attach builds and then rerun to attach the bugs")
                        click.echo(not_found)
                else:
                    click.echo("Skipping attaching RPM CVEs. Use --check-builds flag to validate with builds.")

        impetus_bugs["extras"] = extras_bugs(bugs)

        # all other bugs should go into "image" advisory
        impetus_bugs["image"] = set(bugs) - impetus_bugs["extras"] - rpm_bugs.keys()

    if default_advisory_type and impetus_bugs.get(default_advisory_type):
        errata.add_bugs_with_retry(advisory, impetus_bugs[default_advisory_type], noop=noop)
    elif into_default_advisories:
        for impetus, bugs in impetus_bugs.items():
            if bugs:
                green_prefix(f'{impetus} advisory: ')
                errata.add_bugs_with_retry(runtime.group_config.advisories[impetus], bugs, noop=noop)


type_bug_list = List[Bug]


def extras_bugs(bugs: type_bug_list) -> type_bug_list:
    # optional operators bugs should be swept to the "extras" advisory
    # a way to identify operator-related bugs is by its "Component" value.
    # temporarily hardcode here until we need to move it to ocp-build-data.
    extras_components = {
        "Logging",
        "Service Brokers",
        "Metering Operator",
        "Node Feature Discovery Operator"
    }  # we will probably find more
    extras_subcomponents = {
        ("Networking", "SR-IOV")
    }
    extra_bugs = set()
    for bug in bugs:
        if bug.component in extras_components:
            extra_bugs.add(bug)
        elif hasattr(bug, 'sub_component') and (bug.component, bug.sub_component) in extras_subcomponents:
            extra_bugs.add(bug)
    return extra_bugs


def print_report(bugs: type_bug_list, output: str = 'text') -> None:
    if output == 'slack':
        for bug in bugs:
            click.echo("<{}|{}> - {:<25s} ".format(bug.weburl, bug.id, bug.component))

    elif output == 'json':
        print(json.dumps(
            [
                {
                    "id": bug.id,
                    "component": bug.component,
                    "status": bug.status,
                    "date": str(bug.creation_time_parsed),
                    "summary": bug.summary[:60],
                    "url": bug.weburl
                }
                for bug in bugs
            ],
            indent=4
        ))

    else:  # output == 'text'
        green_print(
            "{:<13s} {:<25s} {:<12s} {:<7s} {:<10s} {:60s}".format("ID", "COMPONENT", "STATUS", "SCORE", "AGE",
                                                                   "SUMMARY"))
        for bug in bugs:
            created_date = bug.creation_time_parsed
            days_ago = (datetime.now(timezone.utc) - created_date).days
            cf_pm_score = bug.cf_pm_score if hasattr(bug, "cf_pm_score") else '?'
            click.echo("{:<13s} {:<25s} {:<12s} {:<7s} {:<3d} days   {:60s} ".format(str(bug.id),
                                                                                     bug.component,
                                                                                     bug.status,
                                                                                     cf_pm_score,
                                                                                     days_ago,
                                                                                     bug.summary[:60]))


def get_sweep_cutoff_timestamp(runtime, cli_brew_event):
    sweep_cutoff_timestamp = 0
    if cli_brew_event:
        green_print(f"Using command line specified cutoff event {runtime.assembly_basis_event}...")
        sweep_cutoff_timestamp = runtime.build_retrying_koji_client().getEvent(cli_brew_event)["ts"]
    elif runtime.assembly_basis_event:
        green_print(f"Determining approximate cutoff timestamp from basis event {runtime.assembly_basis_event}...")
        brew_api = runtime.build_retrying_koji_client()
        sweep_cutoff_timestamp = bzutil.approximate_cutoff_timestamp(runtime.assembly_basis_event, brew_api,
                                                                     runtime.rpm_metas() + runtime.image_metas())

    return sweep_cutoff_timestamp
