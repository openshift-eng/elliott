"""
 Test the task related functions for the OpenShift Image/RPM Build Tool
"""
import unittest

import task


class ParseTaskinfoTestCase(unittest.TestCase):
    """
    Test the reduction of brew task list output to status values
    """
    def test_unknown(self):
        """
        Verify that an empty task output stream indicates "unknown"
        """
        self.assertEqual(task.parse_taskinfo(""), "unknown")

    def test_closed(self):
        """
        Detect state "closed" in brew output
        """

        closed_sample = """\
Task: 14892652
Type: newRepo
Owner: kojira
State: closed
Created: Mon Jan  8 12:47:05 2018
Started: Mon Jan  8 12:47:23 2018
Finished: Mon Jan  8 12:49:56 2018
Host: x86-019.build.eng.bos.redhat.com
"""
        expected = "closed"

        actual = task.parse_taskinfo(closed_sample)
        self.assertEqual(actual, expected)

    def test_open(self):
        """
        Test the state "open" in brew output"
        """

        open_sample = """\
Task: 14892672
Type: newRepo
Owner: kojira
State: open
Created: Mon Jan  8 12:48:43 2018
Started: Mon Jan  8 12:49:07 2018
Host: x86-034.build.eng.bos.redhat.com
"""
        expected = "open"

        actual = task.parse_taskinfo(open_sample)

        self.assertEqual(actual, expected)


class TestWatchTask(unittest.TestCase):

    def test_watch_task(self):
        """
        Check that a watched task completes as expected without timeout
        """
        self.fail("test not implemented")


if __name__ == "__main__":
    unittest.main()
