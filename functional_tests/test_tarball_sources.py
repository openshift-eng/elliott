import unittest
import subprocess
import shutil
import tempfile
from functional_tests import constants


class TarballSourcesTestCase(unittest.TestCase):
    def setUp(self):
        self.out_dir = tempfile.mkdtemp(prefix="tmp-elliott-functional-test-")

    def tearDown(self):
        shutil.rmtree(self.out_dir)

    def test_tarball_sources_create(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "tarball-sources", "create", "--component=logging-fluentd-container",
                "--out-dir", self.out_dir, "--force", "45606",
            ]
        )
        self.assertIn("All tarball sources are successfully created.", out.decode("utf-8"))


if __name__ == '__main__':
    unittest.main()
