import unittest
import subprocess
from functional_tests import constants

# this test may break for EOL releases - apparently the CDN repos for
# some images may become undefined after the fact.


class AdvisoryImagesTestCase(unittest.TestCase):
    def test_advisory_images_with_group(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--assembly=test",
                "--group=openshift-4.2", "advisory-images",
            ]
        )
        self.assertIn("\n#########\n", out.decode("utf-8"))

    def test_advisory_images_with_given_advisory(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--assembly=test",
                "advisory-images", "--advisory", "65127"
            ]
        )
        self.assertIn("\n#########\n", out.decode("utf-8"))


if __name__ == '__main__':
    unittest.main()
