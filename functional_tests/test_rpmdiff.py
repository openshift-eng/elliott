import unittest
import subprocess
import six
from functional_tests import constants


class RPMDiffTestCase(unittest.TestCase):
    def test_rpmdiff_show_with_group(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-4.2", "rpmdiff", "show",
            ]
        )
        six.assertRegex(self, out.decode("utf-8"), "good: \\d+, bad: \\d+, incomplete: \\d+")

    def test_rpmdiff_show_with_specified_advisory(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "rpmdiff", "show", "49981"
            ]
        )
        six.assertRegex(self, out.decode("utf-8"), "good: \\d+, bad: \\d+, incomplete: \\d+")
