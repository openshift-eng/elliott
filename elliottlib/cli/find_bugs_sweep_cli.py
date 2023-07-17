import json
import click
import sys
import traceback
from datetime import datetime
from typing import List, Dict, Set

from elliottlib.assembly import assembly_issues_config
from elliottlib.bzutil import BugTracker, Bug, JIRABug
from elliottlib import (Runtime, bzutil, constants, errata, logutil)
from elliottlib.cli import common
from elliottlib.cli.common import click_coroutine
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import green_prefix, green_print, red_prefix, chunk


logger = logutil.getLogger(__name__)
type_bug_list = List[Bug]
type_bug_set = Set[Bug]


class FindBugsMode:
    def __init__(self, status: List, cve_only: bool):
        self.status = set(status)
        self.cve_only = cve_only

    def include_status(self, status: List):
        self.status |= set(status)

    def exclude_status(self, status: List):
        self.status -= set(status)

    def search(self, bug_tracker_obj: BugTracker, verbose: bool = False):
        func = bug_tracker_obj.cve_tracker_search if self.cve_only else bug_tracker_obj.search
        return func(
            self.status,
            verbose=verbose
        )


class FindBugsSweep(FindBugsMode):
    def __init__(self, cve_only: bool):
        super().__init__(status={'MODIFIED', 'ON_QA', 'VERIFIED'}, cve_only=cve_only)


@common.cli.command("find-bugs:sweep", short_help="Sweep qualified bugs into advisories")
@click.option("--add", "-a", 'advisory_id',
              type=int, metavar='ADVISORY',
              help="Add found bugs to ADVISORY")
@common.use_default_advisory_option
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
@click.option("--cve-only",
              is_flag=True,
              help="Only find CVE trackers")
@click.option("--noop", "--dry-run",
              is_flag=True,
              default=False,
              help="Don't change anything")
@click.pass_obj
@click_coroutine
async def find_bugs_sweep_cli(runtime: Runtime, advisory_id, default_advisory_type, include_status, exclude_status,
                              report, output, into_default_advisories, brew_event, cve_only, noop):
    """Find OCP bugs and (optional) add them to ADVISORY.

 The --group automatically determines the correct target-releases to search
for bugs claimed to be fixed, but not yet attached to advisories.
Security Tracker Bugs are validated with attached builds to advisories.
If expected builds are not found then tracker bugs are not attached.
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
    find_bugs_obj = FindBugsSweep(cve_only=cve_only)
    find_bugs_obj.include_status(include_status)
    find_bugs_obj.exclude_status(exclude_status)

    bugs: type_bug_list = []
    errors = []
    for b in [runtime.bug_trackers('jira'), runtime.bug_trackers('bugzilla')]:
        try:
            bugs.extend(await find_and_attach_bugs(runtime, advisory_id, default_advisory_type, major_version, find_bugs_obj,
                        output, brew_event, noop, count_advisory_attach_flags, b))
        except Exception as e:
            errors.append(e)
            logger.error(traceback.format_exc())
            logger.error(f'exception with {b.type} bug tracker: {e}')

    if errors:
        raise ElliottFatalError(f"Error finding or attaching bugs: {errors}. See logs for more information.")

    if not bugs:
        logger.info('No bugs found')
        sys.exit(0)

    if output == 'text':
        click.echo(f"Found {len(bugs)} bugs")
        click.echo(", ".join(sorted(str(b.id) for b in bugs)))

    if report:
        print_report(bugs, output)

    sys.exit(0)


async def get_bugs_sweep(runtime: Runtime, find_bugs_obj, brew_event, bug_tracker):
    bugs = find_bugs_obj.search(bug_tracker_obj=bug_tracker, verbose=runtime.debug)

    sweep_cutoff_timestamp = await get_sweep_cutoff_timestamp(runtime, cli_brew_event=brew_event)
    if sweep_cutoff_timestamp:
        utc_ts = datetime.utcfromtimestamp(sweep_cutoff_timestamp)
        logger.info(f"Filtering bugs that have changed ({len(bugs)}) to one of the desired statuses before the "
                    f"cutoff time {utc_ts}...")
        qualified_bugs = []
        for chunk_of_bugs in chunk(bugs, constants.BUG_LOOKUP_CHUNK_SIZE):
            b = bug_tracker.filter_bugs_by_cutoff_event(chunk_of_bugs, find_bugs_obj.status,
                                                        sweep_cutoff_timestamp, verbose=runtime.debug)
            qualified_bugs.extend(b)
        logger.info(f"{len(qualified_bugs)} of {len(bugs)} bugs are qualified for the cutoff time {utc_ts}...")
        bugs = qualified_bugs

    # filter bugs that have been swept into other advisories
    logger.info("Filtering bugs that haven't been attached to any advisories...")
    attached_bugs = await bug_tracker.filter_attached_bugs(bugs)
    if attached_bugs:
        attached_bug_ids = {b.id for b in attached_bugs}
        logger.warning("The following bugs have been attached to advisories: %s", attached_bug_ids)
        bugs = [b for b in bugs if b.id not in attached_bug_ids]

    included_bug_ids, excluded_bug_ids = get_assembly_bug_ids(runtime, bug_tracker_type=bug_tracker.type)
    if included_bug_ids & excluded_bug_ids:
        raise ValueError(f"The following {bug_tracker.type} bugs are defined in both 'include' and 'exclude': "
                         f"{included_bug_ids & excluded_bug_ids}")
    if included_bug_ids:
        logger.warning(f"The following {bug_tracker.type} bugs will be additionally included because they are "
                       f"explicitly defined in the assembly config: {included_bug_ids}")
        included_bugs = bug_tracker.get_bugs(included_bug_ids)
        bugs.extend(included_bugs)
    if excluded_bug_ids:
        logger.warning(f"The following {bug_tracker.type} bugs will be excluded because they are explicitly "
                       f"defined in the assembly config: {excluded_bug_ids}")
        bugs = [bug for bug in bugs if bug.id not in excluded_bug_ids]

    return bugs


async def find_and_attach_bugs(runtime: Runtime, advisory_id, default_advisory_type, major_version,
                               find_bugs_obj, output, brew_event, noop, count_advisory_attach_flags, bug_tracker):
    if output == 'text':
        statuses = sorted(find_bugs_obj.status)
        tr = bug_tracker.target_release()
        green_prefix(f"Searching {bug_tracker.type} for bugs with status {statuses} and target releases: {tr}\n")

    bugs = await get_bugs_sweep(runtime, find_bugs_obj, brew_event, bug_tracker)

    advisory_ids = runtime.get_default_advisories()
    bugs_by_type = categorize_bugs_by_type(bugs, advisory_ids,
                                           major_version=major_version)
    for kind, kind_bugs in bugs_by_type.items():
        logger.info(f'{kind} bugs: {[b.id for b in kind_bugs]}')

    if count_advisory_attach_flags < 1:
        return bugs
    # `--add ADVISORY_NUMBER` should respect the user's wish
    # and attach all available bugs to whatever advisory is specified.
    if advisory_id and not default_advisory_type:
        bug_tracker.attach_bugs([b.id for b in bugs], advisory_id=advisory_id, noop=noop, verbose=runtime.debug)
        return bugs

    if not advisory_ids:
        logger.info("No advisories to attach to")
        return bugs

    advisory_types_to_attach = [default_advisory_type] if default_advisory_type else bugs_by_type.keys()
    for advisory_type in sorted(advisory_types_to_attach):
        kind_bugs = bugs_by_type.get(advisory_type)
        if kind_bugs:
            bug_tracker.attach_bugs([b.id for b in kind_bugs], advisory_id=advisory_ids[advisory_type], noop=noop,
                                    verbose=runtime.debug)
    return bugs


def get_assembly_bug_ids(runtime, bug_tracker_type):
    # Loads included/excluded bugs from assembly config
    issues_config = assembly_issues_config(runtime.get_releases_config(), runtime.assembly)
    included_bug_ids = {i["id"] for i in issues_config.include}
    excluded_bug_ids = {i["id"] for i in issues_config.exclude}

    if bug_tracker_type == 'jira':
        included_bug_ids = {i for i in included_bug_ids if JIRABug.looks_like_a_jira_bug(i)}
        excluded_bug_ids = {i for i in excluded_bug_ids if JIRABug.looks_like_a_jira_bug(i)}
    elif bug_tracker_type == 'bugzilla':
        included_bug_ids = {i for i in included_bug_ids if not JIRABug.looks_like_a_jira_bug(i)}
        excluded_bug_ids = {i for i in excluded_bug_ids if not JIRABug.looks_like_a_jira_bug(i)}
    return included_bug_ids, excluded_bug_ids


def categorize_bugs_by_type(bugs: List[Bug], advisory_id_map: Dict[str, int], major_version: int = 4):
    bugs_by_type: Dict[str, type_bug_set] = {
        "rpm": set(),
        "image": set(),
        "extras": set(),
        # Metadata advisory will not have Bugs for z-stream releases
        # But at GA time it can have operator builds for the early operator release
        # and thus related extras bugs (including trackers and flaws) will need to be attached to it
        # see: https://art-docs.engineering.redhat.com/release/4.y-ga/#early-silent-operator-release
        "metadata": set(),
        "microshift": set(),
    }

    # for 3.x, all bugs should go to the rpm advisory
    if int(major_version) < 4:
        bugs_by_type["rpm"] = set(bugs)
        return bugs_by_type

    # for 4.x, first sort all non_tracker_bugs
    tracker_bugs: type_bug_set = set()
    non_tracker_bugs: type_bug_set = set()
    fake_trackers: type_bug_set = set()

    for b in bugs:
        if b.is_tracker_bug():
            tracker_bugs.add(b)
        else:
            non_tracker_bugs.add(b)
            if b.is_invalid_tracker_bug():
                fake_trackers.add(b)

    bugs_by_type["extras"] = extras_bugs(non_tracker_bugs)
    remaining = non_tracker_bugs - bugs_by_type["extras"]
    bugs_by_type["microshift"] = {b for b in remaining if b.component and b.component.startswith('MicroShift')}
    remaining = remaining - bugs_by_type["microshift"]
    bugs_by_type["image"] = remaining

    if fake_trackers:
        raise ElliottFatalError(f"Bug(s) {[t.id for t in fake_trackers]} look like CVE trackers, but really are not. Please fix.")

    if not tracker_bugs:
        return bugs_by_type

    logger.info(f"Tracker Bugs found: {len(tracker_bugs)}")

    for b in tracker_bugs:
        logger.info(f'Tracker bug, component: {(b.id, b.whiteboard_component)}')

    if not advisory_id_map:
        logger.info("Skipping sorting/attaching Tracker Bugs. Advisories with attached builds must be given to "
                    "validate trackers.")
        return bugs_by_type

    logger.info("Validating tracker bugs with builds in advisories..")
    found = set()
    for kind in bugs_by_type.keys():
        if len(found) == len(tracker_bugs):
            break
        advisory = advisory_id_map.get(kind)
        if not advisory:
            continue
        attached_builds = errata.get_advisory_nvrs(advisory)
        packages = list(attached_builds.keys())
        exception_packages = []
        if kind == 'image':
            # golang builder is a special tracker component
            # which applies to all our golang images
            exception_packages.append(constants.GOLANG_BUILDER_CVE_COMPONENT)

        for bug in tracker_bugs:
            package_name = bug.whiteboard_component
            if package_name == "microshift" and len(packages) == 0:
                # microshift is special since it has a separate advisory, and it's build is attached
                # after payload is promoted. So do not pre-emptively complain
                logger.info(f"skip attach microshift bug {bug.id} to {advisory} because this advisory has no builds attached")
                found.add(bug)
            elif (package_name in packages) or (package_name in exception_packages):
                if package_name in packages:
                    logger.info(f"{kind} build found for #{bug.id}, {package_name} ")
                if package_name in exception_packages:
                    logger.info(f"{package_name} bugs included by default")
                found.add(bug)
                bugs_by_type[kind].add(bug)

    not_found = set(tracker_bugs) - found
    if not_found:
        not_found_with_component = [(b.id, b.whiteboard_component) for b in not_found]
        red_prefix("Tracker Bugs Warning: ")
        click.echo("The following (tracker bug, package) were found BUT not attached,"
                   " since no corresponding brew build was found attached to any advisory. "
                   "First attach builds to the correct advisory and rerun to attach the bugs, "
                   "or exclude the bug ids in the assembly definition")
        click.echo(not_found_with_component)
        raise ValueError(f'No builds found for CVE (bug, package): {not_found_with_component}. Either attach '
                         f'builds or exclude the bugs in the assembly definition')

    return bugs_by_type


def extras_bugs(bugs: type_bug_set) -> type_bug_set:
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


async def get_sweep_cutoff_timestamp(runtime, cli_brew_event):
    sweep_cutoff_timestamp = 0
    if cli_brew_event:
        logger.info(f"Using command line specified cutoff event {runtime.assembly_basis_event}...")
        sweep_cutoff_timestamp = runtime.build_retrying_koji_client().getEvent(cli_brew_event)["ts"]
    elif runtime.assembly_basis_event:
        logger.info(f"Determining approximate cutoff timestamp from basis event {runtime.assembly_basis_event}...")
        brew_api = runtime.build_retrying_koji_client()
        sweep_cutoff_timestamp = await bzutil.approximate_cutoff_timestamp(runtime.assembly_basis_event, brew_api,
                                                                           runtime.rpm_metas() + runtime.image_metas())

    return sweep_cutoff_timestamp
