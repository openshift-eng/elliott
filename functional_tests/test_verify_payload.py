from __future__ import absolute_import, print_function, unicode_literals
import unittest
import subprocess
from functional_tests import constants


class VerifyPayloadTestCase(unittest.TestCase):
    def test_verify_payload(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "verify-payload",
                "quay.io/openshift-release-dev/ocp-release:4.2.12",
                "49645",
            ]
        )
        self.assertIn("Summary results:", out.decode("utf-8"))
