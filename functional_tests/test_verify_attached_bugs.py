from unittest import TestCase
from mock import MagicMock, patch
from functional_tests import constants
import subprocess

from elliottlib.cli.verify_attached_bugs_cli import BugValidator
from elliottlib import bzutil


class VerifyBugs(TestCase):

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
        # fixture because it does have a real BZ server. everything else is dummy content to be overridden.
        rt = MagicMock()
        rt.gitdata.load_data().data = dict(
            target_release=[],
            product="dummy product",
            server="bugzilla.redhat.com",
        )
        return rt

    def _test_get_attached_bugs(self):
        bugs = BugValidator(self.runtime_fixture())._get_attached_bugs([60085])
        self.assertEqual(20, len(bugs))
        self.assertIn(1812663, {bug.id for bug in bugs})
        print(f"{list(bugs)[0].product}")

    def test_get_attached_filtered_bugs(self):
        bv = BugValidator(self.runtime_fixture())
        bv.product = "OpenShift Container Platform"
        bv.target_releases = ['4.5.0', '4.5.z']
        bugs = {bug.id for bug in bv._get_attached_filtered_bugs([60089])}  # SHIPPED_LIVE RHSA
        self.assertIn(1856529, bugs)  # security tracker
        self.assertNotIn(1858981, bugs)  # flaw bug
        self.assertFalse(bv.problems, "There should be no problems")

    def test_get_attached_filtered_bugs_problems(self):
        bv = BugValidator(self.runtime_fixture())
        bv.product = "OpenShift Container Platform"
        bv.target_releases = ['4.6.0', '4.6.z']
        bv._get_attached_filtered_bugs([60089])  # SHIPPED_LIVE RHSA
        self.assertTrue(bv.problems, "Should find version mismatch")
        self.assertTrue(
            any("1856529" in problem for problem in bv.problems),
            "Should find version mismatch for 1856529"
        )

    def test_get_and_verify_blocking_bugs(self):
        bv = BugValidator(self.runtime_fixture())
        bv.product = "OpenShift Container Platform"
        bv.target_releases = ['4.4.0', '4.4.z']
        bugs = bzutil.get_bugs(bv.bzapi, [1875258, 1878798, 1881212, 1869790, 1840719])

        bbf = bv._get_blocking_bugs_for(list(bugs.values()))
        self.assertTrue(bbf[1875258], "CVE tracker with blocking bug")
        self.assertTrue(any(bug.id == 1875259 for bug in bbf[1875258]), "1875259 blocks 1875258")
        self.assertTrue(bbf[1878798], "regular bug with blocking bug")
        self.assertTrue(any(bug.id == 1872337 for bug in bbf[1878798]), "1872337 blocks 1878798")
        self.assertFalse(bbf[1881212], "placeholder bug w/o blocking")
        self.assertTrue(bbf[1869790], "bug with several blocking bugs, one DUPLICATE")
        self.assertTrue(any(bug.id == 1868735 for bug in bbf[1869790]), "DUPLICATE 1868735 blocks 1869790")
        self.assertTrue(all(bug.id != 1868158 for bug in bbf[1869790]), "4.6 1868158 blocks 1869790")
        self.assertFalse(bbf[1840719], "bug with 4.6 blocking bug")

        # having acquired these bugs, might as well use them to test verification
        bv._verify_blocking_bugs(bbf)
        self.assertIn(
            "Regression possible: bug 1869790 is a backport of bug 1868735 which was CLOSED DUPLICATE",
            bv.problems
        )
        for bug in [1875258, 1878798, 1881212, 1840719]:
            self.assertFalse(
                any(str(bug) in problem for problem in bv.problems),
                f"{bug} blocker status {bbf[bug]}"
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
