from __future__ import absolute_import, print_function, unicode_literals
import unittest
import subprocess
from functional_tests import constants


class FindBuildsTestCase(unittest.TestCase):
    def test_find_rpms(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-3.10", "find-builds", "--kind=rpm",
            ]
        )
        self.assertIn("may be attached to an advisory", out.decode("utf-8"))

    def test_find_images(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-3.10", "find-builds", "--kind=image",
            ]
        )
        self.assertIn("may be attached to an advisory", out.decode("utf-8"))
