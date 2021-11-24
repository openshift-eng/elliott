import asyncio
import re
from typing import Any, Dict, Iterable, List, Set, Tuple

import click
from bugzilla.bug import Bug
from spnego.exceptions import GSSError

from elliottlib import attach_cve_flaws, bzutil, constants, util
from elliottlib.cli.common import cli, click_coroutine, pass_runtime
from elliottlib.errata_async import AsyncErrataAPI, AsyncErrataUtils
from elliottlib.runtime import Runtime
from elliottlib.util import (exit_unauthenticated, green_print,
                             minor_version_tuple, red_print)


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
    validator = BugValidator(runtime)
    try:
        await validator.errata_api.login()
        advisory_bugs = await validator.get_attached_bugs(advisories)
        non_flaw_bugs = validator.filter_bugs_by_product({b for bugs in advisory_bugs.values() for b in bugs})
        validator.validate(non_flaw_bugs, verify_bug_status)
        if verify_flaws:
            await validator.verify_attached_flaws(advisory_bugs)
    except GSSError:
        exit_unauthenticated()
    finally:
        await validator.close()


@cli.command("verify-bugs", short_help="Same as verify-attached-bugs, but for bugs that are not (yet) attached to advisories")
@click.option("--verify-bug-status", is_flag=True, help="Check that bugs of advisories are all VERIFIED or more", type=bool, default=False)
@click.argument("bug_ids", nargs=-1, type=click.IntRange(1), required=False)
@pass_runtime
@click_coroutine
async def verify_bugs_cli(runtime, verify_bug_status, bug_ids):
    runtime.initialize()
    validator = BugValidator(runtime)
    bugs = validator.filter_bugs_by_product(bzutil.get_bugs(validator.bzapi, bug_ids).values())
    try:
        validator.validate(bugs, verify_bug_status)
    finally:
        await validator.close()


class BugValidator:

    def __init__(self, runtime: Runtime):
        self.runtime = runtime
        self.bz_data: Dict[str, Any] = runtime.gitdata.load_data(key='bugzilla').data
        self.target_releases: List[str] = self.bz_data['target_release']
        self.product: str = self.bz_data['product']
        self.bzapi = bzutil.get_bzapi(self.bz_data)
        self.et_data: Dict[str, Any] = runtime.gitdata.load_data(key='erratatool').data
        self.errata_api = AsyncErrataAPI(self.et_data.get("server", constants.errata_url))
        self.problems: List[str] = []

    async def close(self):
        await self.errata_api.close()

    def validate(self, non_flaw_bugs: Iterable[Bug], verify_bug_status: bool,):
        non_flaw_bugs = self.filter_bugs_by_release(non_flaw_bugs, complain=True)
        blocking_bugs_for = self._get_blocking_bugs_for(non_flaw_bugs)
        self._verify_blocking_bugs(blocking_bugs_for)

        if verify_bug_status:
            self._verify_bug_status(non_flaw_bugs)

        if self.problems:
            red_print("Some bug problems were listed above. Please investigate.")
            exit(1)
        green_print("All bugs were verified.")

    async def verify_attached_flaws(self, advisory_bugs: Dict[int, List[Bug]]):
        futures = []
        for advisory_id, attached_bugs in advisory_bugs.items():
            attached_trackers = [b for b in attached_bugs if bzutil.is_cve_tracker(b)]
            attached_flaws = [b for b in attached_bugs if bzutil.is_flaw_bug(b)]
            futures.append(self._verify_attached_flaws_for(advisory_id, attached_trackers, attached_flaws))
        await asyncio.gather(*futures)

    async def _verify_attached_flaws_for(self, advisory_id: int, attached_trackers: Iterable[Bug], attached_flaws: Iterable[Bug]):
        # Retrieve flaw bugs in Bugzilla for attached_tracker_bugs
        tracker_flaws, flaw_id_bugs = attach_cve_flaws.get_corresponding_flaw_bugs(
            self.bzapi,
            attached_trackers,
            fields=["depends_on", "alias", "severity", "summary"]
        )

        # Find first-fix flaws
        current_target_release, err = util.get_target_release(attached_trackers)
        if err:
            self._complain(f"Couldn't determine target release for attached trackers: {err}")
            return
        if current_target_release[-1] == 'z':
            first_fix_flaw_ids = flaw_id_bugs.keys()
        else:
            first_fix_flaw_ids = {
                flaw_bug.id for flaw_bug in flaw_id_bugs.values()
                if attach_cve_flaws.is_first_fix_any(self.bzapi, flaw_bug, current_target_release)
            }

        # Check if attached flaws match attached trackers
        attached_flaw_ids = {b.id for b in attached_flaws}
        missing_flaw_ids = attached_flaw_ids - first_fix_flaw_ids
        if missing_flaw_ids:
            self._complain(f"{len(missing_flaw_ids)} flaw bugs are missing: {', '.join(sorted(map(str, missing_flaw_ids)))}")
        extra_flaw_ids = first_fix_flaw_ids - attached_flaw_ids
        if extra_flaw_ids:
            self._complain(f"{len(extra_flaw_ids)} flaw bugs are redundant: {', '.join(sorted(map(str, extra_flaw_ids)))}")

        # Check if flaw bugs are associated with specific builds
        cve_components_mapping: Dict[str, Set[str]] = {}
        for tracker in attached_trackers:
            component_name = bzutil.get_whiteboard_component(tracker)
            if not component_name:
                raise ValueError(f"Bug {tracker.id} doesn't have a valid component name in its whiteboard field.")
            flaw_ids = tracker_flaws[tracker.id]
            for flaw_id in flaw_ids:
                if len(flaw_id_bugs[flaw_id].alias) != 1:
                    raise ValueError(f"Bug {flaw_id} should have exact 1 alias.")
                cve = flaw_id_bugs[flaw_id].alias[0]
                cve_components_mapping.setdefault(cve, set()).add(component_name)
        current_cve_package_exclusions = await AsyncErrataUtils.get_advisory_cve_package_exclusions(self.errata_api, advisory_id)
        attached_builds = await self.errata_api.get_builds_flattened(advisory_id)
        expected_cve_packages_exclusions = AsyncErrataUtils.compute_cve_package_exclusions(attached_builds, cve_components_mapping)
        extra_cve_package_exclusions, missing_cve_package_exclusions = AsyncErrataUtils.diff_cve_package_exclusions(current_cve_package_exclusions, expected_cve_packages_exclusions)
        for cve, cve_package_exclusions in extra_cve_package_exclusions.items():
            if cve_package_exclusions:
                self._complain(f"{cve} is not associated with Brew components {', '.join(sorted(cve_package_exclusions))}")
        for cve, cve_package_exclusions in missing_cve_package_exclusions.items():
            if cve_package_exclusions:
                self._complain(f"{cve} is associated with Brew components {', '.join(sorted(cve_package_exclusions))} without tracker bugs. You may need to explictly exclude those Brew components from the CVE mapping.")

        # Check if flaw bugs match the CVE field of the advisory
        advisory_cves = await self.errata_api.get_cves(advisory_id)
        extra_cves = cve_components_mapping.keys() - advisory_cves
        if extra_cves:
            self._complain(f"The following CVEs are not associated with advisory {advisory_id}: {', '.join(sorted(extra_cves))}")
        missing_cves = advisory_cves - cve_components_mapping.keys()
        if missing_cves:
            self._complain(f"Tracker bugs for the following CVEs associated with advisory {advisory_id} are not attached: {', '.join(sorted(extra_cves))}")

    async def get_attached_bugs(self, advisory_ids: Iterable[int]) -> Dict[int, Set[Bug]]:
        """ Get bugs attached to specified advisories
        :return: a dict with advisory id as key and set of bug objects as value
        """
        green_print(f"Retrieving bugs for advisory {advisory_ids}")
        advisories = await asyncio.gather(*[self.errata_api.get_advisory(advisory_id) for advisory_id in advisory_ids])
        bug_objects = bzutil.get_bugs(self.bzapi, list({b["bug"]["id"] for ad in advisories for b in ad["bugs"]["bugs"]}))
        result = {ad["content"]["content"]["errata_id"]: {bug_objects[b["bug"]["id"]] for b in ad["bugs"]["bugs"]} for ad in advisories}
        return result

    def filter_bugs_by_product(self, bugs):
        # filter out bugs for different product (presumably security flaw bugs)
        return [b for b in bugs if b.product == self.product]

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
        candidate_blockers = [b.depends_on for b in bugs if b.depends_on]
        candidate_blockers = {b for deps in candidate_blockers for b in deps}

        v = minor_version_tuple(self.target_releases[0])
        next_version = (v[0], v[1] + 1)

        pattern = re.compile(r'^[0-9]+\.[0-9]+\.(0|z)$')

        # retrieve blockers and filter to those with correct product and target version
        blocking_bugs = {
            bug.id: bug
            for bug in bzutil.get_bugs(self.bzapi, list(candidate_blockers)).values()
            # b.target release is a list of size 0 or 1
            if any(minor_version_tuple(target) == next_version for target in bug.target_release if pattern.match(target))
            and bug.product == self.product
        }

        return {bug.id: [blocking_bugs[b] for b in bug.depends_on if b in blocking_bugs] for bug in bugs}

    def _verify_blocking_bugs(self, blocking_bugs_for):
        # complain about blocker bugs that aren't verified or shipped
        for bug, blockers in blocking_bugs_for.items():
            for blocker in blockers:
                if blocker.status not in ['VERIFIED', 'RELEASE_PENDING', 'CLOSED']:
                    self._complain(
                        f"Regression possible: bug {bug} is a backport of bug "
                        f"{blocker.id} which has status {blocker.status}"
                    )
                if blocker.status == 'CLOSED' and blocker.resolution not in ['CURRENTRELEASE', 'NEXTRELEASE', 'ERRATA', 'DUPLICATE', 'NOTABUG']:
                    self._complain(
                        f"Regression possible: bug {bug} is a backport of bug "
                        f"{blocker.id} which was CLOSED {blocker.resolution}"
                    )

    def _verify_bug_status(self, bugs):
        # complain about bugs that are not yet VERIFIED or more.
        for bug in bugs:
            if bzutil.is_flaw_bug(bug):
                continue
            if bug.status in ["VERIFIED", "RELEASE_PENDING"]:
                continue
            if bug.status == "CLOSED" and bug.resolution == "ERRATA":
                continue
            status = f"{bug.status}"
            if bug.status == 'CLOSED':
                status = f"{bug.status}: {bug.resolution}"
            self._complain(f"Bug {bug.id} has status {status}")

    def _complain(self, problem: str):
        red_print(problem)
        self.problems.append(problem)
