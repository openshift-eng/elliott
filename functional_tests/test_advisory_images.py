from __future__ import absolute_import, print_function, unicode_literals
import unittest
import subprocess
from functional_tests import constants


class AdvisoryImagesTestCase(unittest.TestCase):
    def test_advisory_images_with_group(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-4.2", "advisory-images"
            ]
        )
        self.assertIn("\n#########\n", out.decode("utf-8"))

    def test_advisory_images_with_given_advisory(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "advisory-images", "--advisory", "49645"
            ]
        )
        self.assertIn("\n#########\n", out.decode("utf-8"))
