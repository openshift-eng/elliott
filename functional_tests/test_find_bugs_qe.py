import unittest
import subprocess
from functional_tests import constants


class FindBugsQETestCase(unittest.TestCase):
    def test_find_bugs_qe(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-4.3", "find-bugs:qe", '--noop'
            ]
        )
        search_string = "Searching for bugs with status MODIFIED and target release(s): 4.3.z, 4.3.0"
        self.assertTrue(search_string in out.decode("utf-8"))


if __name__ == '__main__':
    unittest.main()
