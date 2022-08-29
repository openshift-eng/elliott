import asyncio
import re
from typing import Any, Dict, Iterable, List, Set, Tuple
import click
from spnego.exceptions import GSSError


from elliottlib import bzutil, constants, util, errata
from elliottlib.cli.common import cli, click_coroutine, pass_runtime
from elliottlib.errata_async import AsyncErrataAPI, AsyncErrataUtils
from elliottlib.runtime import Runtime
from elliottlib.util import (exit_unauthenticated, green_print,
                             minor_version_tuple, red_print)
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker, Bug


@cli.command("verify-attached-bugs", short_help="Verify bugs in a release will not be regressed in the next version")
@click.option("--verify-bug-status", is_flag=True, help="Check that bugs of advisories are all VERIFIED or more", type=bool, default=False)
@click.option("--verify-flaws", is_flag=True, help="Check that flaw bugs are attached and associated with specific builds", type=bool, default=False)
@click.argument("advisories", nargs=-1, type=click.IntRange(1), required=False)
@pass_runtime
@click_coroutine
async def verify_attached_bugs_cli(runtime: Runtime, verify_bug_status: bool, advisories: Tuple[int, ...], verify_flaws: bool):
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
    await verify_attached_bugs(runtime, verify_bug_status, advisories, verify_flaws, runtime.use_jira)


async def verify_attached_bugs(runtime: Runtime, verify_bug_status: bool, advisories: Tuple[int, ...], verify_flaws: bool, use_jira: bool):
    validator = BugValidator(runtime, use_jira, output="text")
    try:
        await validator.errata_api.login()
        bz_bugs, jira_bugs = await validator.get_attached_bugs(advisories)
        non_flaw_bz_bugs = validator.filter_bugs_by_product({b for bugs in bz_bugs.values() for b in bugs})
        non_flaw_jira_bugs = validator.filter_bugs_by_product({b for bugs in jira_bugs.values() for b in bugs})
        validator.validate(non_flaw_bz_bugs, non_flaw_jira_bugs, verify_bug_status)
        if verify_flaws:
            await validator.verify_attached_flaws(bz_bugs, jira_bugs, use_jira)
    except GSSError:
        exit_unauthenticated()
    finally:
        await validator.close()


@cli.command("verify-bugs", short_help="Same as verify-attached-bugs, but for bugs that are not (yet) attached to advisories")
@click.option("--verify-bug-status", is_flag=True, help="Check that bugs of advisories are all VERIFIED or more", type=bool, default=False)
@click.option('--output', '-o',
              required=False,
              type=click.Choice(['text', 'json', 'slack']),
              default='text',
              help='Applies chosen format to command output')
@click.argument("bug_ids", nargs=-1, required=False)
@pass_runtime
@click_coroutine
async def verify_bugs_cli(runtime, verify_bug_status, output, bug_ids):
    runtime.initialize()
    if runtime.use_jira:
        await verify_bugs(runtime, verify_bug_status, output, bug_ids, True)
    else:
        await verify_bugs(runtime, verify_bug_status, output, bug_ids, False)


async def verify_bugs(runtime, verify_bug_status, output, bug_ids, use_jira):
    validator = BugValidator(runtime, use_jira, output)
    if use_jira:
        jira_bugs = validator.filter_bugs_by_product(validator.jira_tracker.get_bugs(bug_ids))
        bz_bugs = []
    else:
        bz_bugs = validator.filter_bugs_by_product(validator.bz_tracker.get_bugs(bug_ids))
        jira_bugs = []
    try:
        validator.validate(bz_bugs, jira_bugs, verify_bug_status)
    finally:
        await validator.close()


class BugValidator:

    def __init__(self, runtime: Runtime, use_jira: bool = False, output: str = 'text'):
        self.runtime = runtime
        self.use_jira = use_jira
        if use_jira:
            self.jira_config = JIRABugTracker.get_config(runtime)
            self.jira_tracker = JIRABugTracker(self.jira_config)
            self.jira_product = self.jira_config['project']
        self.bz_config = BugzillaBugTracker.get_config(runtime)
        self.bz_tracker = BugzillaBugTracker(self.bz_config)
        self.bz_product = self.bz_config['product']
        self.target_releases: List[str] = self.bz_config['target_release']
        self.et_data: Dict[str, Any] = runtime.get_errata_config()
        self.errata_api = AsyncErrataAPI(self.et_data.get("server", constants.errata_url))
        self.problems: List[str] = []
        self.output = output

    async def close(self):
        await self.errata_api.close()

    def validate(self, non_flaw_bz_bugs: Iterable[Bug], non_flaw_jira_bugs: Iterable[Bug], verify_bug_status: bool,):
        non_flaw_bz_bugs = self.filter_bugs_by_release(non_flaw_bz_bugs, complain=True)
        non_flaw_jira_bugs = self.filter_bugs_by_release(non_flaw_jira_bugs, complain=True)
        blocking_bugs_for_bz = self._get_blocking_bugs_for(non_flaw_bz_bugs, False)
        blocking_bugs_for_jira = self._get_blocking_bugs_for(non_flaw_jira_bugs, True)
        self._verify_blocking_bugs({**blocking_bugs_for_bz, **blocking_bugs_for_jira})

        if verify_bug_status:
            self._verify_bug_status({**blocking_bugs_for_bz, **blocking_bugs_for_jira})

        if self.problems:
            if self.output != 'slack':
                red_print("Some bug problems were listed above. Please investigate.")
            exit(1)
        green_print("All bugs were verified. This check doesn't cover CVE flaw bugs.")

    async def verify_attached_flaws(self, bz_bugs: Dict[int, List[Bug]], jira_bugs: Dict[int, List[Bug]], use_jira: bool,):
        futures = []
        for advisory_id, attached_bugs in bz_bugs.items():
            attached_bz_trackers = [b for b in attached_bugs if b.is_tracker_bug()]
            attached_bz_flaws = [b for b in attached_bugs if b.is_flaw_bug()]
            if use_jira:
                attached_jira_trackers = [b for b in jira_bugs[advisory_id] if b.is_tracker_bug()]
                attached_jira_flaws = [b for b in jira_bugs[advisory_id] if b.is_flaw_bug()]
                futures.append(self._verify_attached_flaws_for(advisory_id, attached_bz_trackers, attached_bz_flaws, attached_jira_trackers, attached_jira_flaws, use_jira))
            else:
                futures.append(self._verify_attached_flaws_for(advisory_id, attached_bz_trackers, attached_bz_flaws, [], [], use_jira))
        await asyncio.gather(*futures)
        if self.problems:
            red_print("Some bug problems were listed above. Please investigate.")
            exit(1)
        green_print("All CVE flaw bugs were verified.")

    def _check_attached_flaws_match_trackers(self, attached_flaws: Iterable[Bug], first_fix_flaw_ids: List[str], advisory_id: str):
        # Check if attached flaws match attached trackers
        attached_flaw_ids = {b.id for b in attached_flaws}
        missing_flaw_ids = attached_flaw_ids - first_fix_flaw_ids
        if missing_flaw_ids:
            self._complain(f"On advisory {advisory_id}, {len(missing_flaw_ids)} flaw bugs are not attached but they are referenced by attached tracker bugs: {', '.join(sorted(map(str, missing_flaw_ids)))}."
                           " You probably need to attach those flaw bugs or drop the corresponding tracker bugs.")
        extra_flaw_ids = first_fix_flaw_ids - attached_flaw_ids
        if extra_flaw_ids:
            self._complain(f"On advisory {advisory_id}, {len(extra_flaw_ids)} flaw bugs are attached but there are no tracker bugs referencing them: {', '.join(sorted(map(str, extra_flaw_ids)))}."
                           " You probably need to drop those flaw bugs or attach the corresponding tracker bugs.")

    async def _get_first_fix_flaws_from_trackers(self, advisory_id: str, advisory_info: Dict, attached_trackers: Iterable[Bug], use_jira: bool):
        # Retrieve flaw bugs in Bugzilla for attached_tracker_bugs
        tracker = self.jira_tracker if use_jira else self.bz_tracker
        tracker_flaws, flaw_id_bugs = tracker.get_corresponding_flaw_bugs(attached_trackers)

        # Find first-fix flaws
        first_fix_flaw_ids = set()
        if attached_trackers:
            current_target_release = bzutil.Bug.get_target_release(attached_trackers)
            if current_target_release[-1] == 'z':
                first_fix_flaw_ids = flaw_id_bugs.keys()
            else:
                first_fix_flaw_ids = {
                    flaw_bug.id for flaw_bug in flaw_id_bugs.values()
                    if bzutil.is_first_fix_any(tracker.client(), flaw_bug, current_target_release)
                }
        if not first_fix_flaw_ids:
            return first_fix_flaw_ids

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
                self._complain(f"On advisory {advisory_id}, {cve} is not associated with Brew components {', '.join(sorted(cve_package_exclusions))}."
                               " You may need to associate the CVE with the components in the CVE mapping or drop the tracker bugs.")
        for cve, cve_package_exclusions in missing_cve_package_exclusions.items():
            if cve_package_exclusions:
                self._complain(f"On advisory {advisory_id}, {cve} is associated with Brew components {', '.join(sorted(cve_package_exclusions))} without a tracker bug."
                               " You may need to explictly exclude those Brew components from the CVE mapping or attach the corresponding tracker bugs.")

        # Check if flaw bugs match the CVE field of the advisory
        advisory_cves = advisory_info["content"]["content"]["cve"].split()
        extra_cves = cve_components_mapping.keys() - advisory_cves
        if extra_cves:
            self._complain(f"On advisory {advisory_id}, bugs for the following CVEs are already attached but they are not listed in advisory's `CVE Names` field: {', '.join(sorted(extra_cves))}")
        missing_cves = advisory_cves - cve_components_mapping.keys()
        if missing_cves:
            self._complain(f"On advisory {advisory_id}, bugs for the following CVEs are not attached but listed in advisory's `CVE Names` field: {', '.join(sorted(missing_cves))}")

        return first_fix_flaw_ids

    async def _verify_attached_flaws_for(self, advisory_id: int, attached_bz_trackers: Iterable[Bug], attached_bz_flaws: Iterable[Bug],
                                         attached_jira_trackers: Iterable[Bug], attached_jira_flaws: Iterable[Bug], use_jira: bool):
        advisory_info = await self.errata_api.get_advisory(advisory_id)
        advisory_type = next(iter(advisory_info["errata"].keys())).upper()  # should be one of [RHBA, RHSA, RHEA]

        first_fix_flaws_bz = await self._get_first_fix_flaws_from_trackers(advisory_id, advisory_info, attached_bz_trackers, False)
        first_fix_flaws_jira = set()
        if use_jira:
            first_fix_flaws_jira = await self._get_first_fix_flaws_from_trackers(advisory_id, advisory_info, attached_jira_trackers, use_jira)
            self._check_attached_flaws_match_trackers(attached_jira_flaws, first_fix_flaws_jira, advisory_id)

        self._check_attached_flaws_match_trackers(attached_bz_flaws, first_fix_flaws_bz, advisory_id)

        # Check if advisory is of the expected type
        if not first_fix_flaws_bz and not first_fix_flaws_jira:
            if advisory_type == "RHSA":
                self._complain(f"Advisory {advisory_id} is of type {advisory_type} but has no first-fix flaw bugs. It should be converted to RHBA or RHEA.")
            return  # The remaining checks are not needed for a non-RHSA.
        if advisory_type != "RHSA":
            self._complain(f"Advisory {advisory_id} is of type {advisory_type} but has first-fix flaw bugs {first_fix_flaws_bz} {first_fix_flaws_jira}. It should be converted to RHSA.")

    async def get_attached_bugs(self, advisory_ids: Iterable[str]) -> Dict[int, Set[Bug]]:
        """ Get bugs attached to specified advisories
        :return: a dict with advisory id as key and set of bug objects as value {et_id:{bug_id:bug_obj,...},...}
        """
        green_print(f"Retrieving bugs for advisory {advisory_ids}")
        tasks = [self.errata_api.get_advisory(advisory_id) for advisory_id in advisory_ids]
        advisories = await asyncio.gather(*tasks)
        bug_map = self.bz_tracker.get_bugs_map(list({b["bug"]["id"] for ad in advisories for b in ad["bugs"]["bugs"]}))
        result = {ad["content"]["content"]["errata_id"]: {bug_map[b["bug"]["id"]] for b in ad["bugs"]["bugs"]} for ad
                  in advisories}
        if self.use_jira:
            issue_keys = {advisory_id: [issue["key"] for issue in errata.get_jira_issue_from_advisory(advisory_id)] for advisory_id in advisory_ids}
            bug_map = self.jira_tracker.get_bugs_map([key for keys in issue_keys.values() for key in keys])
            jira_result = {advisory_id: {bug_map[key] for key in issue_keys[advisory_id]} for advisory_id in advisory_ids}
            return result, jira_result
        return result, {}

    def filter_bugs_by_product(self, bugs):
        # filter out bugs for different product (presumably security flaw bugs)
        if self.use_jira:
            return [b for b in bugs if b.product == self.bz_product or b.product == self.jira_product]
        else:
            return [b for b in bugs if b.product == self.bz_product]

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

    def _get_blocking_bugs_for(self, bugs, use_jira):
        bug_tracker = self.jira_tracker if use_jira else self.bz_tracker
        # get blocker bugs in the next version for all bugs we are examining
        candidate_blockers = [b.depends_on for b in bugs if b.depends_on]
        candidate_blockers = {b for deps in candidate_blockers for b in deps}

        v = minor_version_tuple(self.target_releases[0])
        next_version = (v[0], v[1] + 1)

        def is_next_target(target_v):
            pattern = re.compile(r'^\d+\.\d+\.(0|z)$')
            return pattern.match(target_v) and minor_version_tuple(target_v) == next_version

        # retrieve blockers and filter to those with correct product and target version
        if use_jira:
            blockers = [b for b in bug_tracker.get_bugs(sorted(list(candidate_blockers))) if b.product == self.jira_product]
        else:
            blockers = [b for b in bug_tracker.get_bugs(sorted(list(candidate_blockers))) if b.product == self.bz_product]
        blocking_bugs = {}
        for bug in blockers:
            if any(is_next_target(target) for target in bug.target_release):
                blocking_bugs[bug.id] = bug

        return {bug: [blocking_bugs[b] for b in bug.depends_on if b in blocking_bugs] for bug in bugs}

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
                    blocker.resolution not in ['CURRENTRELEASE', 'NEXTRELEASE', 'ERRATA', 'DUPLICATE', 'NOTABUG',
                                               'WONTFIX', 'Done', "Won't Do", 'Errata', 'Duplicate', 'Not a Bug']:
                    if self.output == 'text':
                        message = f"Regression possible: {bug.status} bug {bug.id} is a backport of bug " \
                            f"{blocker.id} which was CLOSED {blocker.resolution}"
                    elif self.output == 'slack':
                        message = f"`{bug.status}` bug <{bug.weburl}|{bug.id}> is a backport of bug " \
                            f"<{blocker.weburl}|{blocker.id}> which was CLOSED `{blocker.resolution}`"
                    self._complain(message)
                else:
                    green_print(f"Verify blocking bugs for {bug.id} Passed")

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
