import unittest
import subprocess
import six
from functional_tests import constants


class FindBugsTestCase(unittest.TestCase):
    def test_sweep_bugs(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-4.3", "find-bugs", "--mode=sweep",
            ]
        )
        six.assertRegex(self, out.decode("utf-8"), "Found \\d+ bugs")
