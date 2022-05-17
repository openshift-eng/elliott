import unittest
import subprocess
from functional_tests import constants


class FindBugsQETestCase(unittest.TestCase):
    def test_find_bugs_qe(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--assembly=stream", "--group=openshift-4.3", "find-bugs:qe", '--noop'
            ]
        )
        search_string = "Searching for bugs with status MODIFIED and target release(s): 4.3.z, 4.3.0"
        result = out.decode("utf-8")
        self.assertIn(search_string, result)
        self.assertRegex(self, result, "Found \\d+ bugs")


if __name__ == '__main__':
    unittest.main()
