#!/usr/bin/env python
"""
Test functions related to controlled command execution
"""

from __future__ import print_function

import unittest

import os
import tempfile
import shutil

import logging

import exectools


class RetryTestCase(unittest.TestCase):
    """
    Test the exectools.retry() method
    """
    ERROR_MSG = r"Giving up after {} failed attempt\(s\)"

    def test_success(self):
        """
        Given a function that passes, make sure it returns successfully with
        a single retry or greater.
        """
        pass_function = lambda: True
        self.assertTrue(exectools.retry(1, pass_function))
        self.assertTrue(exectools.retry(2, pass_function))

    def test_failure(self):
        """
        Given a function that fails, make sure that it raise an exception
        correctly with a single retry limit and greater.
        """
        fail_function = lambda: False
        self.assertRaisesRegexp(
            Exception, self.ERROR_MSG.format(1), exectools.retry, 1, fail_function)
        self.assertRaisesRegexp(
            Exception, self.ERROR_MSG.format(2), exectools.retry, 2, fail_function)

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
            exectools.retry, 3, lambda: calls.append("f"),
            wait_f=lambda n: calls.extend(("w", str(n))))

        # check that the test and wait loop operated as expected
        self.assertEqual(calls, expected_calls)

    def test_return(self):
        """
        Verify that the retry task return value is passed back out faithfully.
        """
        obj = {}
        func = lambda: obj
        self.assertIs(exectools.retry(1, func, check_f=lambda _: True), obj)


class TestCmdExec(unittest.TestCase):
    """
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="ocp-cd-test-logs")
        self.test_file = os.path.join(self.test_dir, "test_file")
        logging.basicConfig(filename=self.test_file, level=logging.INFO)
        self.logger = logging.getLogger()

    def tearDown(self):
        logging.shutdown()
        reload(logging)
        shutil.rmtree(self.test_dir)

    def test_cmd_assert_success(self):
        """
        """

        try:
            exectools.cmd_assert("/bin/true")
        except IOError as error:
            self.Fail("/bin/truereturned failure: {}".format(error))

        # check that the log file has all of the tests.
        log_file = open(self.test_file, 'r')
        lines = log_file.readlines()
        log_file.close()

        self.assertEquals(len(lines), 4)

    def test_cmd_assert_fail(self):
        """
        """

        # Try a failing command 3 times, at 1 sec intervals
        with self.assertRaises(IOError):
            exectools.cmd_assert("/usr/bin/false", 3, 1)

        # check that the log file has all of the tests.
        log_file = open(self.test_file, 'r')
        lines = log_file.readlines()
        log_file.close()

        self.assertEquals(len(lines), 12)


class TestGather(unittest.TestCase):
    """
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="ocp-cd-test-logs")
        self.test_file = os.path.join(self.test_dir, "test_file")
        logging.basicConfig(filename=self.test_file, level=logging.INFO)
        self.logger = logging.getLogger()

    def tearDown(self):
        logging.shutdown()
        reload(logging)
        shutil.rmtree(self.test_dir)

    def test_gather_success(self):
        """
        """

        (status, stdout, stderr) = exectools.cmd_gather(
            "/usr/bin/echo hello there")
        status_expected = 0
        stdout_expected = "hello there\n"
        stderr_expected = ""

        self.assertEquals(status_expected, status)
        self.assertEquals(stdout, stdout_expected)
        self.assertEquals(stderr, stderr_expected)

        # check that the log file has all of the tests.

        log_file = open(self.test_file, 'r')
        lines = log_file.readlines()

        self.assertEquals(len(lines), 6)

    def test_gather_fail(self):
        """
        """

        (status, stdout, stderr) = exectools.cmd_gather(
            ["/usr/bin/sed", "-e", "f"])

        status_expected = 1
        stdout_expected = ""
        stderr_expected = "/usr/bin/sed: -e expression #1, char 1: unknown command: `f'\n"

        self.assertEquals(status_expected, status)
        self.assertEquals(stdout, stdout_expected)
        self.assertEquals(stderr, stderr_expected)

        # check that the log file has all of the tests.
        log_file = open(self.test_file, 'r')
        lines = log_file.readlines()

        self.assertEquals(len(lines), 6)


if __name__ == "__main__":

    unittest.main()
