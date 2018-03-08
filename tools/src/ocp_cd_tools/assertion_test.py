"""
Test the task related functions for the OpenShift Image/RPM Build Tool
"""
import unittest

import assertion


class TestAssert(unittest.TestCase):
    """
    Test the methods of the assertion module.

    Each raises an exception if the asserted test fails.
    """
    def test_isdir(self):
        """
        Verify both positive and negative results for directory test
        """
        dir_exists = "/usr"
        dir_missing = "/tmp/doesnotexist"
        not_dir = "/etc/motd"

        try:
            assertion.isdir(dir_exists, "dir missing: {}".format(dir_exists))
        except assertion.FileNotFoundError as fnf_error:
            self.fail("asserted real directory does not exist: {}".
                      format(fnf_error))

        with self.assertRaises(assertion.FileNotFoundError):
            assertion.isdir(dir_missing, "dir missing: {}".format(dir_missing))

        # This should raise NotADirectory
        with self.assertRaises(assertion.FileNotFoundError):
            assertion.isdir(not_dir, "file, not dir: {}".format(not_dir))

    def test_isfile(self):
        """
        Verify both positive and negative results for file test
        """
        file_exists = "/etc/motd"
        file_missing = "/tmp/doesnotexist"
        not_file = "/usr"

        try:
            assertion.isfile(file_exists, "file missing: {}".format(file_exists))
        except assertion.FileNotFoundError as fnf_error:
            self.fail("asserted real file does not exist: {}".format(fnf_error))

        with self.assertRaises(assertion.FileNotFoundError):
            assertion.isfile(
                file_missing,
                "file missing: {}".format(file_missing)
            )

        # Should raise IsADirectory
        with self.assertRaises(assertion.FileNotFoundError):
            assertion.isfile(not_file, "dir, not file: {}".format(not_file))

    def test_success(self):
        """
        Verify that return codes indicating pass and fail respond correctly
        """

        # When we move to Python 3 this will raise ChildProcessError directly
        try:
            assertion.success(0, "this should not fail")
        except assertion.ChildProcessError as proc_fail:
            self.fail("success reported as fail: {}".format(proc_fail))

        with self.assertRaises(assertion.ChildProcessError):
            assertion.success(1, "process failed")


if __name__ == "__main__":
    unittest.main()
