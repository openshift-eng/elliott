import unittest
import subprocess
from functional_tests import constants


class ChangeStateTestCase(unittest.TestCase):
    def test_change_state(self):
        p = subprocess.Popen(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-3.9", "change-state", "--state=QE", "--advisory=47924",
            ],
            stdout=subprocess.PIPE
        )
        out, _ = p.communicate()
        self.assertIn("current state is SHIPPED_LIVE", out.decode("utf-8"))
