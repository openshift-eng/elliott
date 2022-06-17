import unittest
import subprocess
from functional_tests import constants


class ChangeStateTestCase(unittest.TestCase):
    def test_change_state(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-3.9", "change-state", "--state=QE", "--advisory=47924",
            ],
        )
        self.assertIn("current state is SHIPPED_LIVE", out.decode("utf-8"))


if __name__ == '__main__':
    unittest.main()
