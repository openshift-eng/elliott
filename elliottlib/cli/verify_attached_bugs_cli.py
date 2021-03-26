import click
from kerberos import GSSError

from errata_tool import Erratum

from elliottlib import bzutil, errata
from elliottlib.cli.common import cli, pass_runtime
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import (exit_unauthenticated, red_print, green_print, minor_version_tuple)


@cli.command("verify-attached-bugs", short_help="Verify bugs in a release will not be regressed in the next version")
@click.option("--verify-bug-status", is_flag=True, help="Check that bugs of advisories are all VERIFIED or more", type=bool, default=False)
@click.argument("advisories", nargs=-1, type=click.IntRange(1), required=False)
@pass_runtime
def verify_attached_bugs_cli(runtime, verify_bug_status, advisories):
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
    BugValidator(runtime).validate(advisories, verify_bug_status)


class BugValidator:

    def __init__(self, runtime):
        self.runtime = runtime
        self.bz_data = runtime.gitdata.load_data(key='bugzilla').data
        self.target_releases = self.bz_data['target_release']
        self.product = self.bz_data['product']
        self.bzapi = bzutil.get_bzapi(self.bz_data)
        self.problems = []

    def validate(self, advisories, verify_bug_status):
        bugs = self._get_attached_filtered_bugs(advisories)
        blocking_bugs_for = self._get_blocking_bugs_for(bugs)
        self._verify_blocking_bugs(blocking_bugs_for)

        if verify_bug_status:
            self._verify_bug_status(bugs)
        if self.problems:
            red_print("Some bug problems were listed above. Please investigate.")
            exit(1)
        green_print("All bugs were verified.")

    def _get_attached_bugs(self, advisories):
        # get bugs attached to all advisories
        bugs = set()
        try:
            for advisory in advisories:
                green_print(f"Retrieving bugs for advisory {advisory}")
                bugs.update(errata.get_bug_ids(advisory))
        except GSSError:
            exit_unauthenticated()
        green_print(f"Found {len(bugs)} bugs")

        return list(bzutil.get_bugs(self.bzapi, list(bugs)).values())

    def _get_attached_filtered_bugs(self, advisories):
        # get bugs from advisories that are for the expected product and version
        candidates = self._get_attached_bugs(advisories)

        # filter out bugs for different product (presumably security flaw bugs)
        candidates = [b for b in candidates if b.product == self.product]

        # filter out bugs with an invalid target release (and complain)
        filtered_bugs = []
        for b in candidates:
            # b.target release is a list of size 0 or 1
            if any(target in self.target_releases for target in b.target_release):
                filtered_bugs.append(b)
            else:
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

        # retrieve blockers and filter to those with correct product and target version
        blocking_bugs = {
            bug.id: bug
            for bug in bzutil.get_bugs(self.bzapi, list(candidate_blockers)).values()
            # b.target release is a list of size 0 or 1
            if any(minor_version_tuple(target) == next_version for target in bug.target_release)
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

    def _complain(self, problem):
        red_print(problem)
        self.problems.append(problem)
