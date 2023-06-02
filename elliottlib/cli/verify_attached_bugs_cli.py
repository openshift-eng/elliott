import asyncio
import re
from typing import Any, Dict, Iterable, List, Set, Tuple
import click
from errata_tool import Erratum

from elliottlib import bzutil, constants, logutil
from elliottlib.cli.common import cli, click_coroutine, pass_runtime
from elliottlib.errata_async import AsyncErrataAPI, AsyncErrataUtils
from elliottlib.runtime import Runtime
from elliottlib.util import (minor_version_tuple, red_print)
from elliottlib.bzutil import Bug
from elliottlib.cli.attach_cve_flaws_cli import get_flaws
from elliottlib.cli.find_bugs_sweep_cli import FindBugsSweep, categorize_bugs_by_type

logger = logutil.getLogger(__name__)


@cli.command("verify-attached-bugs",
             short_help="Run validations on bugs attached to release advisories and report results")
@click.option("--verify-bug-status", is_flag=True,
              help="Check that bugs of advisories are all VERIFIED or more",
              type=bool, default=False)
@click.option("--verify-flaws", is_flag=True,
              help="Check that flaw bugs are attached and associated with respective builds",
              type=bool, default=False)
@click.option("--no-verify-blocking-bugs", is_flag=True,
              help="Don't check if there are open bugs for the next minor version blocking bugs for this minor version",
              type=bool, default=False)
@click.option("--skip-multiple-advisories-check", is_flag=True,
              help="Do not check if bugs are attached to multiple advisories",
              type=bool, default=False)
@click.argument("advisories", nargs=-1, type=click.IntRange(1), required=False)
@pass_runtime
@click_coroutine
async def verify_attached_bugs_cli(runtime: Runtime, verify_bug_status: bool, advisories: Tuple[int, ...], verify_flaws: bool,
                                   no_verify_blocking_bugs: bool, skip_multiple_advisories_check: bool):
    """
    Validate bugs in release advisories (specified in arguments or as part of an assembly).
    Requires group param (-g openshift-X.Y)

    Default validations:
    - Target Release: All bugs belong to the group's target release.
    - Bug Sorting: Bugs are attached to the correct advisory type (image/rpm/extras) using
    find-bugs:sweep logic. This only runs with --assembly. To skip manually specify advisories.
    - Improper Tracker Bugs: Bugs that have CVE in their title but do not have Tracker Bug labels set.
    - Regression Check: If there are any backport bugs, make sure they don't get ahead of their original bug.
    This is to make sure we don't regress when upgrading from OCP X.Y to X.Y+1. To skip use --no-verify-blocking-bugs.
    - Bugs aren't attached to multiple advisories. To skip use --skip-multiple-advisories-check.

    Additional validations:
    - Bug Status (--verify-bug-status): All bugs are in at least in VERIFIED state
    - Flaw Bugs (--verify-flaws): All flaw bugs are attached to advisories (using attach-cve-flaws logic) and
    associated with respective builds. Verify advisory type is RHSA when applicable, and CVE names field is correct.

    If any verification fails, a text explanation is given and the return code is 1.
    Otherwise, prints the number of bugs in the advisories and exits with success.
    """
    runtime.initialize()
    if advisories:
        click.echo("WARNING: Cannot verify advisory bug sorting. To verify that bugs are attached to the "
                   "correct release advisories, run with --assembly=<release>")
        advisory_id_map = {'?': a for a in advisories}
    else:
        advisory_id_map = runtime.get_default_advisories()
    if not advisory_id_map:
        red_print("No advisories specified on command line or in [group.yml|releases.yml]")
        exit(1)
    await verify_attached_bugs(runtime, verify_bug_status, advisory_id_map, verify_flaws, no_verify_blocking_bugs, skip_multiple_advisories_check)


async def verify_attached_bugs(runtime: Runtime, verify_bug_status: bool, advisory_id_map: Dict[str, int], verify_flaws:
                               bool, no_verify_blocking_bugs: bool, skip_multiple_advisories_check: bool):
    validator = BugValidator(runtime, output="text")
    advisory_bug_map = validator.get_attached_bugs(list(advisory_id_map.values()))
    bugs = {b for bugs in advisory_bug_map.values() for b in bugs}

    # bug.is_ocp_bug() filters by product/project, so we don't get flaw bugs or bugs of other products or
    # placeholder
    non_flaw_bugs = [b for b in bugs if b.is_ocp_bug()]

    validator.validate(non_flaw_bugs, verify_bug_status, no_verify_blocking_bugs)

    # skip advisory type check if advisories are
    # manually passed in, and we don't know their type
    if '?' not in advisory_id_map.keys():
        validator.verify_bugs_advisory_type(non_flaw_bugs, advisory_id_map, advisory_bug_map)

    if not skip_multiple_advisories_check:
        await validator.verify_bugs_multiple_advisories(non_flaw_bugs)

    if verify_flaws:
        await validator.verify_attached_flaws(advisory_bug_map)

    # Close client session
    await validator.close()

    if validator.problems:
        if validator.output != 'slack':
            red_print(f"Found the following problems: {validator.problems}")
            red_print("Some bug problems were listed above. Please investigate.")
        exit(1)


@cli.command("verify-bugs", short_help="Verify bugs included in an assembly (default --assembly=stream)")
@click.option("--verify-bug-status", is_flag=True, help="Check that bugs of advisories are all VERIFIED or more",
              type=bool, default=False)
@click.option("--no-verify-blocking-bugs", is_flag=True,
              help="Don't check if there are open bugs for the next minor version blocking bugs for this minor version",
              type=bool, default=False)
@click.option('--output', '-o',
              required=False,
              type=click.Choice(['text', 'json', 'slack']),
              default='text',
              help='Applies chosen format to command output')
@pass_runtime
@click_coroutine
async def verify_bugs_cli(runtime, verify_bug_status, output, no_verify_blocking_bugs: bool):
    """
    Validate bugs that qualify as being part of an assembly (specified as --assembly)
    Requires group param (-g openshift-X.Y). By default runs for --assembly=stream

    Default validations:
    - Target Release: All bugs belong to the group's target release.
    - Improper Tracker Bugs: Bugs that have CVE in their title but do not have Tracker Bug labels set.
    - Regression Check: If there are any backport bugs, make sure they don't get ahead of their original bug.
    This is to make sure we don't regress when upgrading from OCP X.Y to X.Y+1. To skip use --no-verify-blocking-bugs.

    Additional validations:
    - Bug Status (--verify-bug-status): All bugs are at least in VERIFIED state

    """
    runtime.initialize()
    await verify_bugs(runtime, verify_bug_status, output, no_verify_blocking_bugs)


async def verify_bugs(runtime, verify_bug_status, output, no_verify_blocking_bugs):
    validator = BugValidator(runtime, output)
    find_bugs_obj = FindBugsSweep(cve_only=False)
    ocp_bugs = []
    logger.info(f'Using {runtime.assembly} assembly to search bugs')
    for b in [runtime.bug_trackers('jira'), runtime.bug_trackers('bugzilla')]:
        bugs = find_bugs_obj.search(bug_tracker_obj=b, verbose=runtime.debug)
        logger.info(f"Found {len(bugs)} {b.type} bugs: {[b.id for b in bugs]}")
        ocp_bugs.extend(bugs)

    validator.validate(ocp_bugs, verify_bug_status, no_verify_blocking_bugs)

    # Close client session
    await validator.close()

    if validator.problems:
        if validator.output != 'slack':
            red_print("Some bug problems were listed above. Please investigate.")
        exit(1)


class BugValidator:

    def __init__(self, runtime: Runtime, output: str = 'text'):
        self.runtime = runtime
        self.target_releases: List[str] = runtime.bug_trackers('jira').config['target_release']
        self.et_data: Dict[str, Any] = runtime.get_errata_config()
        self.errata_api = AsyncErrataAPI(self.et_data.get("server", constants.errata_url))
        self.problems: List[str] = []
        self.output = output

    async def close(self):
        await self.errata_api.close()

    def validate(self, non_flaw_bugs: List[Bug], verify_bug_status: bool, no_verify_blocking_bugs: bool):
        non_flaw_bugs = self.filter_bugs_by_release(non_flaw_bugs, complain=True)
        self._find_invalid_trackers(non_flaw_bugs)
        if not no_verify_blocking_bugs:
            blocking_bugs_for = self._get_blocking_bugs_for(non_flaw_bugs)
            self._verify_blocking_bugs(blocking_bugs_for)

        if verify_bug_status:
            self._verify_bug_status(non_flaw_bugs)

    def verify_bugs_advisory_type(self, non_flaw_bugs, advisory_id_map, advisory_bug_map):
        bugs_by_type = categorize_bugs_by_type(non_flaw_bugs, advisory_id_map)
        for kind, advisory_id in advisory_id_map.items():
            actual = {b for b in advisory_bug_map[advisory_id] if b.is_ocp_bug()}
            expected = bugs_by_type[kind]
            if actual != expected:
                bugs_not_found = expected - actual
                extra_bugs = actual - expected
                if bugs_not_found:
                    self._complain(f'Expected Bugs not found in {kind} advisory ({advisory_id}):'
                                   f' {[b.id for b in bugs_not_found]}')
                if extra_bugs:
                    self._complain(f'Unexpected Bugs found in {kind} advisory ({advisory_id}):'
                                   f' {[b.id for b in extra_bugs]}')

    async def verify_bugs_multiple_advisories(self, non_flaw_bugs: List[Bug]):
        logger.info(f'Checking {len(non_flaw_bugs)} bugs, if any bug is attached to multiple advisories')

        async def get_all_advisory_ids(bug):
            all_advisories_id = bug.all_advisory_ids()
            if len(all_advisories_id) > 1:
                return f'Bug <{bug.weburl}|{bug.id}> is attached in multiple advisories: {all_advisories_id}'
            return None

        results = await asyncio.gather(*[asyncio.create_task(get_all_advisory_ids(bug)) for bug in non_flaw_bugs])
        for message in results:
            if message:
                self._complain(message)

    async def verify_attached_flaws(self, advisory_bugs: Dict[int, List[Bug]]):
        futures = []
        for advisory_id, attached_bugs in advisory_bugs.items():
            attached_trackers = [b for b in attached_bugs if b.is_tracker_bug()]
            attached_flaws = [b for b in attached_bugs if b.is_flaw_bug()]
            logger.info(f"Verifying advisory {advisory_id}: attached-trackers: "
                        f"{[b.id for b in attached_trackers]} "
                        f"attached-flaws: {[b.id for b in attached_flaws]}")
            futures.append(self._verify_attached_flaws_for(advisory_id, attached_trackers, attached_flaws))
        await asyncio.gather(*futures)

    async def _verify_attached_flaws_for(self, advisory_id: int, attached_trackers: Iterable[Bug], attached_flaws: Iterable[Bug]):
        flaw_bug_tracker = self.runtime.bug_trackers('bugzilla')
        brew_api = self.runtime.build_retrying_koji_client()
        tracker_flaws, first_fix_flaw_bugs = get_flaws(flaw_bug_tracker, attached_trackers, brew_api,
                                                       self.runtime.logger)

        # Check if attached flaws match expected flaws
        first_fix_flaw_ids = {b.id for b in first_fix_flaw_bugs}
        attached_flaw_ids = {b.id for b in attached_flaws}
        missing_flaw_ids = first_fix_flaw_ids - attached_flaw_ids
        if missing_flaw_ids:
            self._complain(f"On advisory {advisory_id}, these flaw bugs are not attached: "
                           f"{', '.join(sorted(map(str, missing_flaw_ids)))} but "
                           "they are referenced by attached tracker bugs. "
                           "You need to attach those flaw bugs or drop corresponding tracker bugs.")
        extra_flaw_ids = attached_flaw_ids - first_fix_flaw_ids
        if extra_flaw_ids:
            self._complain(f"On advisory {advisory_id}, these flaw bugs are attached: "
                           f"{', '.join(sorted(map(str, extra_flaw_ids)))} but "
                           f"there are no tracker bugs referencing them. "
                           "You need to drop those flaw bugs or attach corresponding tracker bugs.")

        # Check if advisory is of the expected type
        advisory_info = await self.errata_api.get_advisory(advisory_id)
        advisory_type = next(iter(advisory_info["errata"].keys())).upper()  # should be one of [RHBA, RHSA, RHEA]
        if not first_fix_flaw_ids:
            if advisory_type == "RHSA":
                self._complain(f"Advisory {advisory_id} is of type {advisory_type} "
                               f"but has no first-fix flaw bugs. It should be converted to RHBA or RHEA.")
            return  # The remaining checks are not needed for a non-RHSA.
        if advisory_type != "RHSA":
            self._complain(f"Advisory {advisory_id} is of type {advisory_type} but has first-fix flaw bugs "
                           f"{first_fix_flaw_ids}. It should be converted to RHSA.")

        # Validate CVE mappings (of CVEs and builds)
        flaw_id_bugs = {f.id: f for f in first_fix_flaw_bugs}
        cve_components_mapping: Dict[str, Set[str]] = {}
        for tracker in attached_trackers:
            component_name = tracker.whiteboard_component
            flaw_ids = tracker_flaws[tracker.id]
            for flaw_id in flaw_ids:
                if flaw_id not in flaw_id_bugs:  # This means associated flaw wasn't considered a first fix
                    continue

                if len(flaw_id_bugs[flaw_id].alias) != 1:
                    raise ValueError(f"Flaw bug {flaw_id} should have exact 1 alias.")
                cve = flaw_id_bugs[flaw_id].alias[0]
                cve_components_mapping.setdefault(cve, set()).add(component_name)

        attached_builds = await self.errata_api.get_builds_flattened(advisory_id)
        try:
            extra_exclusions, missing_exclusions = await AsyncErrataUtils.validate_cves_and_get_exclusions_diff(
                self.errata_api,
                advisory_id, attached_builds,
                cve_components_mapping)
        except ValueError as e:
            self._complain(e)

        for cve, cve_package_exclusions in extra_exclusions.items():
            if cve_package_exclusions:
                self._complain(f"On advisory {advisory_id}, {cve} is not associated with Brew components "
                               f"{', '.join(sorted(cve_package_exclusions))}."
                               " You may need to associate the CVE with the components "
                               "in the CVE mapping or drop the tracker bugs.")
        for cve, cve_package_exclusions in missing_exclusions.items():
            if cve_package_exclusions:
                self._complain(f"On advisory {advisory_id}, {cve} is associated with Brew components "
                               f"{', '.join(sorted(cve_package_exclusions))} without a tracker bug."
                               " You may need to explicitly exclude those Brew components from the CVE "
                               "mapping or attach the corresponding tracker bugs.")

        # Validate `CVE Names` field of the advisory
        advisory_cves = advisory_info["content"]["content"]["cve"].split()
        extra_cves = cve_components_mapping.keys() - advisory_cves
        if extra_cves:
            self._complain(f"On advisory {advisory_id}, bugs for the following CVEs are already attached "
                           f"but they are not listed in advisory's `CVE Names` field: {', '.join(sorted(extra_cves))}")
        missing_cves = advisory_cves - cve_components_mapping.keys()
        if missing_cves:
            self._complain(f"On advisory {advisory_id}, bugs for the following CVEs are not attached but listed in "
                           f"advisory's `CVE Names` field: {', '.join(sorted(missing_cves))}")

    def get_attached_bugs(self, advisory_ids: List[str]) -> Dict[int, Set[Bug]]:
        """ Get bugs attached to specified advisories
        :return: a dict with advisory id as key and set of bug objects as value
        """
        logger.info(f"Retrieving bugs for advisories: {advisory_ids}")
        advisories = [Erratum(errata_id=advisory_id) for advisory_id in advisory_ids]

        attached_bug_map = {advisory_id: set() for advisory_id in advisory_ids}
        for bug_tracker_type in ['jira', 'bugzilla']:
            bug_tracker = self.runtime.bug_trackers(bug_tracker_type)
            advisory_bug_id_map = {advisory.errata_id: bug_tracker.advisory_bug_ids(advisory)
                                   for advisory in advisories}
            bug_map = bug_tracker.get_bugs_map([bug_id for bug_list in advisory_bug_id_map.values()
                                                for bug_id in bug_list])
            for advisory_id in advisory_ids:
                set_of_bugs = {bug_map[bid] for bid in advisory_bug_id_map[advisory_id] if bid in bug_map}
                attached_bug_map[advisory_id] = attached_bug_map[advisory_id] | set_of_bugs
        return attached_bug_map

    def filter_bugs_by_release(self, bugs: List[Bug], complain: bool = False) -> List[Bug]:
        # filter out bugs with an invalid target release
        filtered_bugs = []
        for b in bugs:
            # b.target release is a list of size 0 or 1
            if any(target in self.target_releases for target in b.target_release):
                filtered_bugs.append(b)
            elif complain:
                self._complain(
                    f"bug {b.id} target release {b.target_release} is not in "
                    f"{self.target_releases}. Does it belong in this release?"
                )
        return filtered_bugs

    def _get_blocking_bugs_for(self, bugs):
        # get blocker bugs in the next version for all bugs we are examining
        candidate_blockers = []
        for b in bugs:
            if b.depends_on:
                candidate_blockers.extend(b.depends_on)
        jira_ids, bz_ids = bzutil.get_jira_bz_bug_ids(set(candidate_blockers))

        v = minor_version_tuple(self.target_releases[0])
        next_version = (v[0], v[1] + 1)

        def is_next_target(target_v):
            pattern = re.compile(r'^\d+\.\d+\.(0|z)$')
            return pattern.match(target_v) and minor_version_tuple(target_v) == next_version

        def managed_by_art(b: Bug):
            components_not_managed_by_art = self.runtime.bug_trackers('jira').component_filter()
            return b.component not in components_not_managed_by_art

        # retrieve blockers and filter to those with correct product and target version
        blockers = []
        if jira_ids:
            blockers.extend(self.runtime.bug_trackers('jira')
                            .get_bugs(jira_ids))
        if bz_ids:
            blockers.extend(self.runtime.bug_trackers('bugzilla')
                            .get_bugs(bz_ids))
        logger.debug(f"Candidate Blocker bugs found: {[b.id for b in blockers]}")
        blocking_bugs = {}
        for bug in blockers:
            if not bug.is_ocp_bug() or not managed_by_art(bug):
                continue
            target_release = []
            # A bug without `Target Version` shouldn't be considered as a blocking bug
            try:
                target_release = bug.target_release
            except ValueError as err:  # bug.target_release will raise ValueError if Target Version is not set
                if "does not have `Target Version` field set" not in str(err):
                    raise
            next_target = any(is_next_target(target) for target in target_release)
            if next_target:
                blocking_bugs[bug.id] = bug
        logger.info(f"Blocking bugs for next target release ({next_version[0]}.{next_version[1]}): "
                    f"{list(blocking_bugs.keys())}")

        k = {bug: [blocking_bugs[b] for b in bug.depends_on if b in blocking_bugs] for bug in bugs}
        return k

    def _verify_blocking_bugs(self, blocking_bugs_for):
        # complain about blocking bugs that aren't verified or shipped
        for bug, blockers in blocking_bugs_for.items():
            for blocker in blockers:
                message = str()
                if blocker.status not in ['VERIFIED', 'RELEASE_PENDING', 'CLOSED', 'Release Pending', 'Verified',
                                          'Closed'] and not (blocker.status == bug.status == "ON_QA"):
                    if self.output == 'text':
                        message = f"Regression possible: {bug.status} bug {bug.id} is a backport of bug " \
                            f"{blocker.id} which has status {blocker.status}"
                    elif self.output == 'slack':
                        message = f"`{bug.status}` bug <{bug.weburl}|{bug.id}> is a backport of " \
                                  f"`{blocker.status}` bug <{blocker.weburl}|{blocker.id}>"
                    self._complain(message)
                if blocker.status in ['CLOSED', 'Closed'] and \
                    blocker.resolution not in ['CURRENTRELEASE', 'NEXTRELEASE', 'ERRATA', 'DUPLICATE', 'NOTABUG', 'WONTFIX',
                                               'Done', 'Fixed', 'Done-Errata',
                                               'Current Release', 'Errata', 'Next Release',
                                               "Won't Do", "Won't Fix",
                                               'Duplicate', 'Duplicate Issue',
                                               'Not a Bug']:
                    if self.output == 'text':
                        message = f"Regression possible: {bug.status} bug {bug.id} is a backport of bug " \
                            f"{blocker.id} which was CLOSED {blocker.resolution}"
                    elif self.output == 'slack':
                        message = f"`{bug.status}` bug <{bug.weburl}|{bug.id}> is a backport of bug " \
                            f"<{blocker.weburl}|{blocker.id}> which was CLOSED `{blocker.resolution}`"
                    self._complain(message)

    def _verify_bug_status(self, bugs):
        # complain about bugs that are not yet VERIFIED or more.
        for bug in bugs:
            if bug.is_flaw_bug():
                continue
            if bug.status in ["VERIFIED", "RELEASE_PENDING", "Verified", "Release Pending"]:
                continue
            if bug.status in ["CLOSED", "Closed"] and bug.resolution in ["ERRATA", 'Errata']:
                continue
            status = f"{bug.status}"
            if bug.status in ['CLOSED', 'Closed']:
                status = f"{bug.status}: {bug.resolution}"
            self._complain(f"Bug <{bug.weburl}|{bug.id}> has status {status}")

    def _find_invalid_trackers(self, bugs):
        logger.info("Checking for invalid tracker bugs")
        # complain about invalid tracker bugs
        for bug in bugs:
            if bug.is_invalid_tracker_bug():
                self._complain(f"Bug <{bug.weburl}|{bug.id}> is an invalid tracker bug. Please fix")

    def _complain(self, problem: str):
        red_print(problem)
        self.problems.append(problem)
