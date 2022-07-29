import json
import click
import sys
import traceback
from datetime import datetime
from typing import List, Optional

from elliottlib.assembly import assembly_issues_config
from elliottlib.bzutil import BugTracker, Bug
from elliottlib import (Runtime, bzutil, constants, errata, logutil)
from elliottlib.cli import common
from elliottlib.util import green_prefix, green_print, red_prefix, yellow_print, chunk


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


@common.cli.command("find-bugs:sweep", short_help="Sweep qualified bugs into advisories")
@click.option("--add", "-a", 'advisory_id',
              type=int, metavar='ADVISORY',
              help="Add found bugs to ADVISORY")
@common.use_default_advisory_option
@click.option("--check-builds",
              default=None,
              required=False,
              is_flag=True,
              help='When attaching, add bugs only if corresponding builds are attached to advisory')
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
@click.option("--report",
              required=False,
              is_flag=True,
              help="Output a detailed report of found bugs")
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
@click.pass_obj
def find_bugs_sweep_cli(runtime: Runtime, advisory_id, default_advisory_type, check_builds, include_status, exclude_status,
                        report, output, into_default_advisories, brew_event, noop):
    """Find OCP bugs and (optional) add them to ADVISORY.

 The --group automatically determines the correct target-releases to search
for bugs claimed to be fixed, but not yet attached to advisories.
--check-builds flag forces bug validation with attached builds to rpm advisory.
It assumes builds have been attached and only attaches bugs with matching builds.
default statuses: ['MODIFIED', 'ON_QA', 'VERIFIED']

Using --use-default-advisory without a value set for the matching key
in the build-data will cause an error and elliott will exit in a
non-zero state. Use of this option silently overrides providing an
advisory with the --add option.

    List bugs that WOULD be swept into advisories (NOOP):

\b
    $ elliott -g openshift-4.8 --assembly 4.8.32 find-bugs:sweep

    Sweep bugs for an assembly into the advisories defined

\b
    $ elliott -g openshift-4.8 --assembly 4.8.32 find-bugs:sweep --into-default-advisories

    Sweep rpm bugs into the rpm advisory defined

\b
    $ elliott -g openshift-4.8 --assembly 4.8.32 find-bugs:sweep --use-default-advisory rpm

"""
    count_advisory_attach_flags = sum(map(bool, [advisory_id, default_advisory_type, into_default_advisories]))
    if count_advisory_attach_flags > 1:
        raise click.BadParameter("Use only one of --use-default-advisory, --add, or --into-default-advisories")

    runtime.initialize(mode="both")
    major_version, _ = runtime.get_major_minor()
    find_bugs_obj = FindBugsSweep()
    find_bugs_obj.include_status(include_status)
    find_bugs_obj.exclude_status(exclude_status)

    exit_code = 0
    for b in runtime.bug_trackers.values():
        try:
            find_bugs_sweep(runtime, advisory_id, default_advisory_type, check_builds, major_version, find_bugs_obj,
                            report, output, brew_event, noop, count_advisory_attach_flags, b)
        except Exception as e:
            runtime.logger.error(traceback.format_exc())
            runtime.logger.error(f'exception with {b.type} bug tracker: {e}')
            exit_code = 1
    sys.exit(exit_code)


def find_bugs_sweep(runtime: Runtime, advisory_id, default_advisory_type, check_builds, major_version, find_bugs_obj,
                    report, output, brew_event, noop, count_advisory_attach_flags, bug_tracker):
    if output == 'text':
        statuses = sorted(find_bugs_obj.status)
        tr = bug_tracker.target_release()
        green_prefix(f"Searching {bug_tracker.type} for bugs with status {statuses} and target releases: {tr}\n")

    bugs = find_bugs_obj.search(bug_tracker_obj=bug_tracker, verbose=runtime.debug)

    sweep_cutoff_timestamp = get_sweep_cutoff_timestamp(runtime, cli_brew_event=brew_event)
    if sweep_cutoff_timestamp:
        utc_ts = datetime.utcfromtimestamp(sweep_cutoff_timestamp)
        green_print(f"Filtering bugs that have changed ({len(bugs)}) to one of the desired statuses before the "
                    f"cutoff time {utc_ts}...")
        qualified_bugs = []
        for chunk_of_bugs in chunk(bugs, constants.BUG_LOOKUP_CHUNK_SIZE):
            b = bug_tracker.filter_bugs_by_cutoff_event(chunk_of_bugs, find_bugs_obj.status,
                                                        sweep_cutoff_timestamp)
            qualified_bugs.extend(b)
        click.echo(f"{len(qualified_bugs)} of {len(bugs)} bugs are qualified for the cutoff time "
                   f"{utc_ts}...")
        bugs = qualified_bugs

    included_bug_ids, excluded_bug_ids = get_assembly_bug_ids(runtime)
    if included_bug_ids & excluded_bug_ids:
        raise ValueError("The following bugs are defined in both 'include' and 'exclude': "
                         f"{included_bug_ids & excluded_bug_ids}")
    if included_bug_ids:
        yellow_print("The following bugs will be additionally included because they are "
                     f"explicitly defined in the assembly config: {included_bug_ids}")
        included_bugs = bug_tracker.get_bugs(included_bug_ids)
        bugs.extend(included_bugs)
    if excluded_bug_ids:
        yellow_print("The following bugs will be excluded because they are explicitly "
                     f"defined in the assembly config: {excluded_bug_ids}")
        bugs = [bug for bug in bugs if bug.id not in excluded_bug_ids]

    if output == 'text':
        green_prefix(f"Found {len(bugs)} bugs: ")
        click.echo(", ".join(sorted(str(b.id) for b in bugs)))

    if report:
        print_report(bugs, output)

    if count_advisory_attach_flags < 1:
        return
    # `--add ADVISORY_NUMBER` should respect the user's wish
    # and attach all available bugs to whatever advisory is specified.
    if advisory_id and not default_advisory_type:
        bug_tracker.attach_bugs(advisory_id, [b.id for b in bugs], noop=noop)
        return

    rpm_advisory_id = common.find_default_advisory(runtime, 'rpm') if check_builds else None
    bugs_by_type = categorize_bugs_by_type(bugs, rpm_advisory_id=rpm_advisory_id,
                                           major_version=major_version,
                                           check_builds=check_builds)

    advisory_types_to_attach = [default_advisory_type] if default_advisory_type else bugs_by_type.keys()
    for advisory_type in sorted(advisory_types_to_attach):
        bugs = bugs_by_type.get(advisory_type)
        green_prefix(f'{advisory_type} advisory: ')
        if bugs:
            adv_id = common.find_default_advisory(runtime, advisory_type)
            bug_tracker.attach_bugs(adv_id, [b.id for b in bugs], noop=noop)
        else:
            click.echo("0 bugs found")


type_bug_list = List[Bug]


def get_assembly_bug_ids(runtime):
    # Loads included/excluded bugs from assembly config
    issues_config = assembly_issues_config(runtime.get_releases_config(), runtime.assembly)
    included_bug_ids = {i["id"] for i in issues_config.include}
    excluded_bug_ids = {i["id"] for i in issues_config.exclude}
    return included_bug_ids, excluded_bug_ids


def categorize_bugs_by_type(bugs: List, rpm_advisory_id: Optional[int] = None, major_version: int = 4, check_builds:
                            bool = True):
    # key is type ("rpm", "image", "extras"), value is a set of bug IDs.
    bugs_by_type = {
        "rpm": set(),
        "image": set(),
        "extras": set()
    }

    # for 3.x, all bugs should go to the rpm advisory
    if int(major_version) < 4:
        bugs_by_type["rpm"] = set(bugs)
    else:  # for 4.x, sweep rpm cve trackers into rpm advisory
        rpm_bugs = bzutil.get_valid_rpm_cves(bugs)
        if rpm_bugs:
            green_prefix("RPM CVEs found: ")
            click.echo(sorted(b.id for b in rpm_bugs))
            # if --check-builds flag is set
            # only attach bugs that have corresponding brew builds attached to rpm advisory
            if check_builds and rpm_advisory_id:
                click.echo("Validating bugs with builds attached to the rpm advisory")
                attached_builds = errata.get_advisory_nvrs(rpm_advisory_id)
                packages = attached_builds.keys()
                not_found = []
                for bug, package_name in rpm_bugs.items():
                    if package_name not in packages:
                        not_found.append((bug.id, package_name))
                    else:
                        click.echo(f"Build found for #{bug.id}, {package_name}")
                        bugs_by_type["rpm"].add(bug)

                if not_found:
                    red_prefix("RPM CVE Warning: ")
                    click.echo("The following CVE (bug, package) were found but not attached, because "
                               "no corresponding brew builds were found attached to the rpm advisory. "
                               "First attach builds and then rerun to attach the bugs")
                    click.echo(not_found)
                    raise ValueError(f'No build found for CVE (bug, package) tuples: {not_found}')
            else:
                click.echo("Skipping attaching RPM CVEs. Use --check-builds flag to validate with builds.")

        bugs_by_type["extras"] = extras_bugs(bugs)

        # all other bugs should go into "image" advisory
        bugs_by_type["image"] = set(bugs) - bugs_by_type["extras"] - rpm_bugs.keys()
    return bugs_by_type


def extras_bugs(bugs: type_bug_list) -> type_bug_list:
    # optional operators bugs should be swept to the "extras" advisory
    # a way to identify operator-related bugs is by its "Component" value.
    # temporarily hardcode here until we need to move it to ocp-build-data.
    extras_components = {
        "Logging",
        "Service Brokers",
        "Metering Operator",
        "Node Feature Discovery Operator",
        "Cloud Native Events",
        "Telco Edge",
    }  # we will probably find more
    extras_subcomponents = {
        ("Networking", "SR-IOV"),
        ("Storage", "Local Storage Operator"),
        ("Cloud Native Events", "Hardware Event Proxy"),
        ("Cloud Native Events", "Hardware Event Proxy Operator"),
        ("Telco Edge", "TALO"),
    }
    extra_bugs = set()
    for bug in bugs:
        if bug.component in extras_components:
            extra_bugs.add(bug)
        elif bug.sub_component and (bug.component, bug.sub_component) in extras_subcomponents:
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
                    "date": str(bug.creation_time_parsed()),
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
            days_ago = bug.created_days_ago()
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
