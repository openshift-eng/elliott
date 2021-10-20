import unittest
import subprocess
import six
from functional_tests import constants


class FindCVETrackersTestCase(unittest.TestCase):
    def test_find_cve_trackers(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-4.3", "find-cve-trackers",
            ]
        )
        six.assertRegex(self, out.decode("utf-8"), "Found \\d+ bugs")


if __name__ == '__main__':
    unittest.main()
