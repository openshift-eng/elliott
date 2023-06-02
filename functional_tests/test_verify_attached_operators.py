import unittest
from unittest.mock import MagicMock, patch
from functional_tests import constants
import subprocess

from elliottlib.cli import verify_attached_operators_cli
from elliottlib.runtime import Runtime


class TestVerifyAttachedOperators(unittest.TestCase):

    def setUp(self):
        self.patchers = [
            patch(f"elliottlib.cli.verify_attached_operators_cli.{it}", lambda x: x)
            for it in ["red_print", "green_print"]
        ]
        for p in self.patchers:
            # disable the printed output during tests (remove this to debug...)
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()

    def test_nvr_for_operand_pullspec(self):
        runtime = Runtime(group="openshift-4.9", working_dir="/tmp", debug=False)
        runtime = MagicMock()
        runtime.group_config = MagicMock(urls=MagicMock(
            brew_image_host="registry-proxy.engineering.redhat.com",
            brew_image_namespace="rh-osbs",
        ))

        spec = "ose-csi-external-provisioner@sha256:cb191fcfe71ce6da60e73697aaa9b3164c1f0566150d3bffb8004598284d767a"
        self.assertEqual(
            "csi-provisioner-container-v4.9.0-202109302317.p0.git.7736e72.assembly.stream",
            verify_attached_operators_cli._nvr_for_operand_pullspec(runtime, spec)
        )

    def test_verify_attached_operators_ok(self):
        out = subprocess.run(
            constants.ELLIOTT_CMD
            + ["--group", "openshift-4.12", "verify-attached-operators", "110351"],
            capture_output=True,
            encoding='utf-8',
        )
        self.assertIn("All operator bundles were valid and references were found.", out.stdout)

    def test_verify_attached_operators_wrong(self):
        out = subprocess.run(
            constants.ELLIOTT_CMD
            + ["--group", "openshift-4.8", "verify-attached-operators", "--omit-shipped", "--omit-attached", "81215"],
            # 4.9.0 GA metadata advisory; will be missing operands from other advisories
            capture_output=True,
            encoding='utf-8',
        )
        self.assertIn("csi-provisioner-container-v4.9.0-202109302317.p0.git.7736e72.assembly.stream", out.stdout)
        self.assertEqual(1, out.returncode)


if __name__ == '__main__':
    unittest.main(verbosity=2)
