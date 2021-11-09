import unittest
import subprocess
import six
from functional_tests import constants


class PollSignedTestCase(unittest.TestCase):
    def test_poll_signed(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-3.10", "poll-signed", "--noop", "--use-default-advisory=rpm",
            ]
        )
        six.assertRegex(self, out.decode("utf-8"), "All builds signed|Signing incomplete")
