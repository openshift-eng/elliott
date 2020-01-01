from __future__ import absolute_import, print_function, unicode_literals
import unittest
import subprocess
from functional_tests import constants


class FindCVETrackersTestCase(unittest.TestCase):
    def test_find_cve_trackers(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-4.3", "find-cve-trackers",
            ]
        )
        self.assertRegexpMatches(out.decode("utf-8"), "Found \\d+ bugs")
