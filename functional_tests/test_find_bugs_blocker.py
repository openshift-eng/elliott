import unittest
import subprocess
from functional_tests import constants


class FindBugsBlockerTestCase(unittest.TestCase):
    def test_find_bugs_blocker(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--assembly=stream", "--group=openshift-4.6", "find-bugs:blocker", '--exclude-status=ON_QA'
            ]
        )
        result = out.decode("utf-8")
        self.assertRegex(result, "Found \\d+ bugs")


if __name__ == '__main__':
    unittest.main()
