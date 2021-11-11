import unittest
import subprocess
from functional_tests import constants

# This test may start failing once this version is EOL and we either change the
# ocp-build-data bugzilla schema or all of the non-shipped builds are garbage-collected.
version = "4.3"


class FindBuildsTestCase(unittest.TestCase):
    def test_find_rpms(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                f"--group=openshift-{version}", "find-builds", "--kind=rpm",
            ]
        )
        self.assertIn("may be attached to an advisory", out.decode("utf-8"))

    def test_find_images(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                f"--group=openshift-{version}", "-i", "openshift-enterprise-cli", "find-builds", "--kind=image",
            ]
        )
        self.assertIn("may be attached to an advisory", out.decode("utf-8"))
