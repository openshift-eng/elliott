import unittest
import subprocess
from functional_tests import constants


class FindBugsSweepTestCase(unittest.TestCase):
    def test_attach_cve_flaws(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--assembly=rc.7", "--group=openshift-4.11", "attach-cve-flaws", "--advisory=97037", "--noop"
            ]
        )
        self.assertIn(out.decode("utf-8"), "Found \\d+ bugzilla tracker bugs attached")


if __name__ == '__main__':
    unittest.main()
