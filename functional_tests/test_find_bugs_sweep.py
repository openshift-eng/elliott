import unittest
import subprocess
from functional_tests import constants


class FindBugsSweepTestCase(unittest.TestCase):
    def test_sweep_bugs(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--assembly=stream", "--group=openshift-4.6", "find-bugs:sweep",
            ]
        )
        self.assertRegex(out.decode("utf-8"), "Found \\d+ bugs")


if __name__ == '__main__':
    unittest.main()
