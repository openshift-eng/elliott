import unittest
import subprocess
from functional_tests import constants


class PollSignedTestCase(unittest.TestCase):
    def test_poll_signed(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-3.10", "poll-signed", "--noop", "--use-default-advisory=rpm",
            ]
        )
        self.assertRegex(out.decode("utf-8"), "All builds signed|Signing incomplete")


if __name__ == '__main__':
    unittest.main()
