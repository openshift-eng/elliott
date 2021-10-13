import json
import unittest
from unittest.mock import MagicMock, patch

from elliottlib.cli import verify_attached_operators_cli


class TestVerifyAttachedOperators(unittest.TestCase):

    @patch("elliottlib.exectools.cmd_assert", autospec=True)
    def test_nvr_for_operand_pullspec(self, mock_cmd):
        runtime = MagicMock()
        img_info = dict(config=dict(config=dict(Labels={
            "com.redhat.component": "csi-provisioner-container",
            "release": "42",
            "version": "v4.9.0",
        })))
        mock_cmd.return_value = (json.dumps(img_info), "")

        self.assertEqual(
            "csi-provisioner-container-v4.9.0-42",
            verify_attached_operators_cli._nvr_for_operand_pullspec(runtime, "something")
        )
