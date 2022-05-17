import unittest
import subprocess
from functional_tests import constants


class FindBugsBlockerTestCase(unittest.TestCase):
    def test_find_bugs_blocker(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--assembly=stream", "--group=openshift-4.3", "find-bugs:blocker", '--exclude-status=ON_QA'
            ]
        )
        search_string = "Searching for bugs with status ASSIGNED MODIFIED NEW ON_DEV POST and target release(s): " \
                        "4.3.z, 4.3.0"
        result = out.decode("utf-8")
        self.assertIn(search_string, result)
        self.assertRegex(self, result, "Found \\d+ bugs")


if __name__ == '__main__':
    unittest.main()
