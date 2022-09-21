import asyncio
import re
from typing import Any, Dict, Iterable, List, Set, Tuple
import click
from spnego.exceptions import GSSError
from errata_tool import Erratum


from elliottlib import bzutil, constants, logutil
from elliottlib.cli.common import cli, click_coroutine, pass_runtime
from elliottlib.errata_async import AsyncErrataAPI, AsyncErrataUtils
from elliottlib.runtime import Runtime
from elliottlib.util import (exit_unauthenticated, green_print,
                             minor_version_tuple, red_print)
from elliottlib.bzutil import Bug, BugTracker
from elliottlib.cli.find_bugs_sweep_cli import get_bugs_sweep, FindBugsSweep

logger = logutil.getLogger(__name__)


@cli.command("verify-attached-bugs", short_help="Verify bugs in a release will not be regressed in the next version")
@click.option("--verify-bug-status", is_flag=True, help="Check that bugs of advisories are all VERIFIED or more", type=bool, default=False)
@click.option("--verify-flaws", is_flag=True, help="Check that flaw bugs are attached and associated with specific builds", type=bool, default=False)
@click.option("--no-verify-blocking-bugs", is_flag=True, help="Don't check if there are open bugs for the next minor version blocking bugs for this minor version", type=bool, default=False)
@click.argument("advisories", nargs=-1, type=click.IntRange(1), required=False)
@pass_runtime
@click_coroutine
async def verify_attached_bugs_cli(runtime: Runtime, verify_bug_status: bool, advisories: Tuple[int, ...], verify_flaws: bool, no_verify_blocking_bugs: bool):
    """
    Verify the bugs in the advisories (specified as arguments or in group.yml) for a release.
    Requires a runtime to ensure that all bugs in the advisories match the runtime version.
    Also ensures that bugs in the next release which block bugs in these advisories have
    been verified, as those represent backports we do not want to regress in upgrades.

    If any verification fails, a text explanation is given and the return code is 1.
    Otherwise, prints the number of bugs in the advisories and exits with success.
    """
    runtime.initialize()
    advisories = advisories or [a for a in runtime.group_config.get('advisories', {}).values()]
    if not advisories:
        red_print("No advisories specified on command line or in group.yml")
        exit(1)
    await verify_attached_bugs(runtime, verify_bug_status, advisories, verify_flaws, no_verify_blocking_bugs)


async def verify_attached_bugs(runtime: Runtime, verify_bug_status: bool, advisories: Tuple[int, ...], verify_flaws: bool, no_verify_blocking_bugs: bool):
    validator = BugValidator(runtime, output="text")
    try:
        await validator.errata_api.login()
        advisory_bug_map = validator.get_attached_bugs(advisories)
        bugs = {b for bugs in advisory_bug_map.values() for b in bugs}

        # bug.is_ocp_bug() filters by product/project, so we don't get flaw bugs or bugs of other products
        non_flaw_bugs = {b for b in bugs if b.is_ocp_bug()}

        validator.validate(non_flaw_bugs, verify_bug_status, no_verify_blocking_bugs)
        if verify_flaws:
            await validator.verify_attached_flaws(advisory_bug_map)
    except GSSError:
        exit_unauthenticated()
    finally:
        await validator.close()


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
    Verify the bugs that qualify as being part of an assembly (specified as --assembly)
    By default --assembly=stream
    Checks are similar to verify-attached-bugs
    """
    runtime.initialize()
    await verify_bugs(runtime, verify_bug_status, output, no_verify_blocking_bugs)


async def verify_bugs(runtime, verify_bug_status, output, no_verify_blocking_bugs):
    validator = BugValidator(runtime, output)
    find_bugs_obj = FindBugsSweep()
    ocp_bugs = []
    logger.info(f'Using {runtime.assembly} assembly to search bugs')
    for b in [runtime.bug_trackers('jira'), runtime.bug_trackers('bugzilla')]:
        bugs = get_bugs_sweep(runtime, find_bugs_obj, None, b)
        logger.info(f"Found {len(bugs)} {b.type} bugs: {[b.id for b in bugs]}")
        ocp_bugs.extend(bugs)
    try:
        validator.validate(ocp_bugs, verify_bug_status, no_verify_blocking_bugs)
    finally:
        await validator.close()


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

    def validate(self, non_flaw_bugs: Iterable[Bug], verify_bug_status: bool, no_verify_blocking_bugs: bool):
        non_flaw_bugs = self.filter_bugs_by_release(non_flaw_bugs, complain=True)

        if not no_verify_blocking_bugs:
            blocking_bugs_for = self._get_blocking_bugs_for(non_flaw_bugs)
            self._verify_blocking_bugs(blocking_bugs_for)

        if verify_bug_status:
            self._verify_bug_status(non_flaw_bugs)

        if self.problems:
            if self.output != 'slack':
                red_print("Some bug problems were listed above. Please investigate.")
            exit(1)
        green_print("All bugs were verified. This check doesn't cover CVE flaw bugs.")

    async def verify_attached_flaws(self, advisory_bugs: Dict[int, List[Bug]]):
        futures = []
        for advisory_id, attached_bugs in advisory_bugs.items():
            attached_trackers = [b for b in attached_bugs if b.is_tracker_bug()]
            attached_flaws = [b for b in attached_bugs if b.is_flaw_bug()]
            self.runtime.logger.info(f"Verifying advisory {advisory_id}: attached-trackers: "
                                     f"{[b.id for b in attached_trackers]} "
                                     f"attached-flaws: {[b.id for b in attached_flaws]}")
            futures.append(self._verify_attached_flaws_for(advisory_id, attached_trackers, attached_flaws))
        await asyncio.gather(*futures)
        if self.problems:
            red_print("Some bug problems were listed above. Please investigate.")
            exit(1)
        green_print("All CVE flaw bugs were verified.")

    async def _verify_attached_flaws_for(self, advisory_id: int, attached_trackers: Iterable[Bug], attached_flaws: Iterable[Bug]):
        # Retrieve flaw bugs for attached_tracker_bugs
        tracker_flaws, flaw_id_bugs = BugTracker.get_corresponding_flaw_bugs(attached_trackers,
                                                                             self.runtime.bug_trackers('bugzilla'))

        # Find first-fix flaws
        first_fix_flaw_ids = set()
        if attached_trackers:
            current_target_release = bzutil.Bug.get_target_release(attached_trackers)
            if current_target_release[-1] == 'z':
                first_fix_flaw_ids = flaw_id_bugs.keys()
            else:
                first_fix_flaw_ids = {
                    flaw_bug.id for flaw_bug in flaw_id_bugs.values()
                    # We are passing in bugzilla as a bug tracker since flaw bugs are
                    # always bugzilla bugs their links ("depends_on"/"blocked") fields
                    # which we use to find its trackers - will always link to other bz bugs
                    # This is a gap in our first fix logic since we won't be able to get to
                    # jira tracker bugs for bz flaws and determine first fix at GA time
                    # TODO: https://issues.redhat.com/browse/ART-4347
                    if bzutil.is_first_fix_any(self.runtime.bug_trackers('bugzilla'), flaw_bug, current_target_release)
                }

        # Check if attached flaws match attached trackers
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

        # Check if flaw bugs are associated with specific builds
        cve_components_mapping: Dict[str, Set[str]] = {}
        for tracker in attached_trackers:
            component_name = tracker.whiteboard_component
            if not component_name:
                raise ValueError(f"Tracker bug {tracker.id} doesn't have a valid component name in its whiteboard field.")
            flaw_ids = tracker_flaws[tracker.id]
            for flaw_id in flaw_ids:
                if len(flaw_id_bugs[flaw_id].alias) != 1:
                    raise ValueError(f"Flaw bug {flaw_id} should have exact 1 alias.")
                cve = flaw_id_bugs[flaw_id].alias[0]
                cve_components_mapping.setdefault(cve, set()).add(component_name)
        current_cve_package_exclusions = await AsyncErrataUtils.get_advisory_cve_package_exclusions(self.errata_api, advisory_id)
        attached_builds = await self.errata_api.get_builds_flattened(advisory_id)
        expected_cve_packages_exclusions = AsyncErrataUtils.compute_cve_package_exclusions(attached_builds, cve_components_mapping)
        extra_cve_package_exclusions, missing_cve_package_exclusions = AsyncErrataUtils.diff_cve_package_exclusions(current_cve_package_exclusions, expected_cve_packages_exclusions)
        for cve, cve_package_exclusions in extra_cve_package_exclusions.items():
            if cve_package_exclusions:
                self._complain(f"On advisory {advisory_id}, {cve} is not associated with Brew components "
                               f"{', '.join(sorted(cve_package_exclusions))}."
                               " You may need to associate the CVE with the components "
                               "in the CVE mapping or drop the tracker bugs.")
        for cve, cve_package_exclusions in missing_cve_package_exclusions.items():
            if cve_package_exclusions:
                self._complain(f"On advisory {advisory_id}, {cve} is associated with Brew components "
                               f"{', '.join(sorted(cve_package_exclusions))} without a tracker bug."
                               " You may need to explicitly exclude those Brew components from the CVE "
                               "mapping or attach the corresponding tracker bugs.")

        # Check if flaw bugs match the CVE field of the advisory
        advisory_cves = advisory_info["content"]["content"]["cve"].split()
        extra_cves = cve_components_mapping.keys() - advisory_cves
        if extra_cves:
            self._complain(f"On advisory {advisory_id}, bugs for the following CVEs are already attached "
                           f"but they are not listed in advisory's `CVE Names` field: {', '.join(sorted(extra_cves))}")
        missing_cves = advisory_cves - cve_components_mapping.keys()
        if missing_cves:
            self._complain(f"On advisory {advisory_id}, bugs for the following CVEs are not attached but listed in "
                           f"advisory's `CVE Names` field: {', '.join(sorted(missing_cves))}")

    def get_attached_bugs(self, advisory_ids: Iterable[str]) -> (Dict[int, Set[Bug]], Dict[int, Set[Bug]]):
        """ Get bugs attached to specified advisories
        :return: 2 dicts (one for jira bugs, one for bz bugs) with advisory id as key and set of bug objects as value
        """
        green_print(f"Retrieving bugs for advisories: {advisory_ids}")
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

    def filter_bugs_by_release(self, bugs: Iterable[Bug], complain: bool = False) -> List[Bug]:
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

        # retrieve blockers and filter to those with correct product and target version
        blockers = []
        if jira_ids:
            blockers.extend(self.runtime.bug_trackers('jira')
                            .get_bugs(jira_ids))
        if bz_ids:
            blockers.extend(self.runtime.bug_trackers('bugzilla')
                            .get_bugs(bz_ids))
        blocking_bugs = {}
        for bug in blockers:
            if bug.is_ocp_bug() and any(is_next_target(target) for target in bug.target_release):
                blocking_bugs[bug.id] = bug
        logger.info(f"Blocking bugs for next target release ({next_version[0]}.{next_version[1]}): "
                    f"{list(blocking_bugs.keys())}")

        k = {bug: [blocking_bugs[b] for b in bug.depends_on if b in blocking_bugs] for bug in bugs}
        return k

    def _verify_blocking_bugs(self, blocking_bugs_for):
        # complain about blocker bugs that aren't verified or shipped
        for bug, blockers in blocking_bugs_for.items():
            for blocker in blockers:
                message = str()
                if blocker.status not in ['VERIFIED', 'RELEASE_PENDING', 'CLOSED', 'Release Pending', 'Verified',
                                          'Closed']:
                    if self.output == 'text':
                        message = f"Regression possible: {bug.status} bug {bug.id} is a backport of bug " \
                            f"{blocker.id} which has status {blocker.status}"
                    elif self.output == 'slack':
                        message = f"`{bug.status}` bug <{bug.weburl}|{bug.id}> is a backport of " \
                                  f"`{blocker.status}` bug <{blocker.weburl}|{blocker.id}>"
                    self._complain(message)
                if blocker.status in ['CLOSED', 'Closed'] and \
                    blocker.resolution not in ['CURRENTRELEASE', 'NEXTRELEASE', 'ERRATA', 'DUPLICATE', 'NOTABUG', 'WONTFIX',
                                               'Done', 'Fixed', 'Done-Errata'
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
            self._complain(f"Bug {bug.id} has status {status}")

    def _complain(self, problem: str):
        red_print(problem)
        self.problems.append(problem)
