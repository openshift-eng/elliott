import unittest
import subprocess
from functional_tests import constants


class GetTestCase(unittest.TestCase):
    def test_get_errutum(self):
        out = subprocess.check_output(constants.ELLIOTT_CMD + ["get", "49982"])
        self.assertIn("49982", out.decode("utf-8"))

    def test_get_errutum_with_group(self):
        out = subprocess.check_output(constants.ELLIOTT_CMD + ["--assembly=stream", "--group=openshift-4.2", "get", "--use-default-advisory", "rpm"])
        self.assertIn(constants.ERRATA_TOOL_URL, out.decode("utf-8"))


if __name__ == '__main__':
    unittest.main()
