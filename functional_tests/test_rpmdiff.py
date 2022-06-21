import unittest
import subprocess
from functional_tests import constants


class RPMDiffTestCase(unittest.TestCase):
    def test_rpmdiff_show_with_group(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-4.2", "rpmdiff", "show",
            ]
        )
        self.assertRegex(out.decode("utf-8"), "good: \\d+, bad: \\d+, incomplete: \\d+")

    def test_rpmdiff_show_with_specified_advisory(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "rpmdiff", "show", "49981"
            ]
        )
        self.assertRegex(out.decode("utf-8"), "good: \\d+, bad: \\d+, incomplete: \\d+")


if __name__ == '__main__':
    unittest.main()
