import asyncio
import unittest
from collections import namedtuple

from unittest.mock import MagicMock, patch

from functional_tests import constants
import subprocess

from elliottlib.cli.verify_attached_bugs_cli import BugValidator


class VerifyBugs(unittest.TestCase):

    def setUp(self):
        self.patchers = [
            patch(f"elliottlib.cli.verify_attached_bugs_cli.{it}", lambda x: x)
            for it in ["red_print", "green_print"]
        ]
        for p in self.patchers:
            # disable the printed output during tests (remove this to debug...)
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()

    def runtime_fixture(self):
        GitData = namedtuple('GitData', ['data'])

        def mock_gitdata(**kwargs):
            if kwargs['key'] == 'bugzilla':
                return GitData(
                    dict(
                        target_release=[],
                        product="dummy product",
                        server="bugzilla.redhat.com"
                    )
                )
            elif kwargs['key'] == 'erratatool':
                return GitData(
                    dict(
                        target_release=[],
                        product="dummy product",
                        server="https://errata.devel.redhat.com"
                    )
                )

        rt = MagicMock()
        rt.gitdata.load_data = mock_gitdata
        return rt

    def test_get_attached_bugs(self):
        # Create event loop
        loop = asyncio.get_event_loop()

        bv = BugValidator(self.runtime_fixture())

        # Get attached bugs
        result = loop.run_until_complete(bv.get_attached_bugs([60085]))
        bugs = result[60085]

        self.assertEqual(20, len(bugs))
        self.assertIn(1812663, {bug.id for bug in bugs})

    def test_get_attached_filtered_bugs(self):
        # Create event loop
        loop = asyncio.get_event_loop()

        # Initialize validator
        bv = BugValidator(self.runtime_fixture())
        bv.product = "OpenShift Container Platform"
        bv.target_releases = ['4.5.0', '4.5.z']

        # Get attached bugs
        result = loop.run_until_complete(bv.get_attached_bugs([60089]))
        self.assertTrue(result, "Should find attached bugs")
        advisory_bugs = result[60089]

        # Filter bugs by release and product
        bugs = bv.filter_bugs_by_release(advisory_bugs)
        bugs = bv.filter_bugs_by_product(bugs)
        bug_ids = {bug.id for bug in bugs}

        # Check filtered bug IDs
        self.assertIn(1856529, bug_ids)  # security tracker
        self.assertNotIn(1858981, bug_ids)  # flaw bug

    def test_get_attached_filtered_bugs_problems(self):
        # Create event loop
        loop = asyncio.get_event_loop()

        # Initialize validator
        bv = BugValidator(self.runtime_fixture())
        bv.product = "OpenShift Container Platform"
        bv.target_releases = ['4.5.0', '4.5.z']

        # Get attached bugs
        result = loop.run_until_complete(bv.get_attached_bugs([60089]))
        self.assertTrue(result, "Should find attached bugs")
        advisory_bugs = result[60089]

        # Filter bugs by release and product
        bv.filter_bugs_by_release(advisory_bugs, True)
        bv.filter_bugs_by_product(advisory_bugs)

        # Check validation problems
        self.assertTrue(bv.problems, "Should find version mismatch")
        self.assertTrue(
            any("1858981" in problem for problem in bv.problems),
            "Should find version mismatch for 1858981"
        )

    def test_get_and_verify_blocking_bugs(self):
        bv = BugValidator(self.runtime_fixture())
        bv.product = "OpenShift Container Platform"
        bv.target_releases = ['4.4.0', '4.4.z']
        bugs = bv.bug_tracker.get_bugs([1875258, 1878798, 1881212, 1869790, 1840719])
        bug_blocking_map = bv._get_blocking_bugs_for(bugs)
        id_bug_map = {b.id: b for b in bug_blocking_map}
        bbf = lambda bugid: bug_blocking_map[id_bug_map[bugid]]

        self.assertTrue(bbf(1875258), "CVE tracker with blocking bug")
        self.assertTrue(any(bug.id == 1875259 for bug in bbf(1875258)), "1875259 blocks 1875258")
        self.assertTrue(bbf(1878798), "regular bug with blocking bug")
        self.assertTrue(any(bug.id == 1872337 for bug in bbf(1878798)), "1872337 blocks 1878798")
        self.assertFalse(bbf(1881212), "placeholder bug w/o blocking")
        self.assertTrue(bbf(1869790), "bug with several blocking bugs, one DUPLICATE")
        self.assertTrue(any(bug.id == 1868735 for bug in bbf(1869790)), "DUPLICATE 1868735 blocks 1869790")
        self.assertTrue(all(bug.id != 1868158 for bug in bbf(1869790)), "4.6 1868158 blocks 1869790")
        self.assertFalse(bbf(1840719), "bug with 4.6 blocking bug")

        # having acquired these bugs, might as well use them to test verification
        bv._verify_blocking_bugs(bug_blocking_map)
        self.assertIn(
            "Regression possible: CLOSED bug 1869790 is a backport of bug 1881143 which was CLOSED WONTFIX",
            bv.problems
        )
        for bugid in [1875258, 1878798, 1881212, 1840719]:
            self.assertFalse(
                any(str(bugid) in problem for problem in bv.problems),
                f"{bugid} blocker status {bbf(bugid)}"
            )

    def test_verify_attached_bugs_ok(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + ["--group", "openshift-4.5", "verify-attached-bugs", "60085", "60089"]
        )
        self.assertIn("All bugs were verified", out.decode("utf-8"))

    def test_verify_attached_bugs_wrong(self):
        out = subprocess.run(
            constants.ELLIOTT_CMD
            + ["--group", "openshift-4.6", "verify-attached-bugs", "60089"],  # 4.5 RHSA
            capture_output=True,
            encoding='utf-8',
        )
        self.assertIn("bug 1856529 target release ['4.5.z'] is not in", out.stdout)
        self.assertEqual(1, out.returncode)


if __name__ == '__main__':
    unittest.main()
