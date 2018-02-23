"""
 Test the task related functions for the OpenShift Image/RPM Build Tool
"""
import unittest

import task


class RetryTestCase(unittest.TestCase):
    """
    Test the task.retry() method
    """
    ERROR_MSG = r"Giving up after {} failed attempt\(s\)"

    def test_success(self):
        """
        Given a function that passes, make sure it returns successfully with
        a single retry or greater.
        """
        pass_function = lambda: True
        self.assertTrue(task.retry(1, pass_function))
        self.assertTrue(task.retry(2, pass_function))

    def test_failure(self):
        """
        Given a function that fails, make sure that it raise an exception
        correctly with a single retry limit and greater.
        """
        fail_function = lambda: False
        self.assertRaisesRegexp(
            Exception, self.ERROR_MSG.format(1), task.retry, 1, fail_function)
        self.assertRaisesRegexp(
            Exception, self.ERROR_MSG.format(2), task.retry, 2, fail_function)

    def test_wait(self):
        """
        Verify that the retry fails and raises an exception as needed.
        Further, verify that the indicated wait loops occurred.
        """

        expected_calls = list("fw0fw1f")

        # initialize a collector for loop information
        calls = []

        # loop 3 times, writing into the collector each try and wait
        self.assertRaisesRegexp(
            Exception, self.ERROR_MSG.format(3),
            task.retry, 3, lambda: calls.append("f"),
            wait_f=lambda n: calls.extend(("w", str(n))))

        # check that the test and wait loop operated as expected
        self.assertEqual(calls, expected_calls)

    def test_return(self):
        """
        Verify that the retry task return value is passed back out faithfully.
        """
        obj = {}
        func = lambda: obj
        self.assertIs(task.retry(1, func, check_f=lambda _: True), obj)


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


if __name__ == "__main__":
    unittest.main()
