#!/usr/bin/env python
"""
Test functions related to controlled command execution
"""

from __future__ import print_function

import unittest

import tempfile
import shutil
import atexit

import logs

import exectools


class TestCmdLog(unittest.TestCase):
    """
    Test the cmd_log() function.
    This function executes a shell command and writes the stdout and stderr
    to a log file provided by the logs module
    """

    def setUp(self):
        logs._Log._reset()
        self.test_dir = tempfile.mkdtemp(prefix="oit-test-cmd-log")
        atexit.register(logs._cleanup_log_dir, self.test_dir)

    def tearDown(self):
        """
        This command requires an existing logger to operate.
        Create the logger before each test
        """
        self.logger._reset()

    def test_cmd_log(self):
        self.logger = logs.Log(log_dir=self.test_dir)
        self.logger.open()

        exectools.cmd_log("/usr/bin/echo this is the output line")

        self.logger.close()

        testfile = open(self.logger.log_path)
        lines = testfile.readlines()
        testfile.close()
        self.assertEquals(len(lines), 4)


class TestCmdExec(unittest.TestCase):
    """
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test-cmd-exec")
        atexit.register(logs._cleanup_log_dir, self.test_dir)
        self.logger = logs.Log(self.test_dir)
        self.logger.open()

    def tearDown(self):
        """
        This command requires an existing logger to operate.
        Create the logger before each test
        """
        self.logger.close()
        self.logger._reset()

    def test_cmd_assert_success(self):
        """
        """

        try:
            exectools.cmd_assert("/bin/true")
        except IOError as error:
            self.Fail("/bin/truereturned failure: {}".format(error))

        # check that the log file has all of the tests.
        log_file = open(self.logger.log_path, 'r')
        lines = log_file.readlines()

        self.assertEquals(len(lines), 4)

    def test_cmd_assert_fail(self):
        """
        """

        # Try a failing command 3 times, at 1 sec intervals
        with self.assertRaises(IOError):
            exectools.cmd_assert("/usr/bin/false", 3, 1)

        # check that the log file has all of the tests.
        log_file = open(self.logger.log_path, 'r')
        lines = log_file.readlines()
        self.assertEquals(len(lines), 12)


class TestGather(unittest.TestCase):
    """
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="oit-test-exectools")
        atexit.register(logs._cleanup_log_dir, self.test_dir)
        self.logger = logs.Log(self.test_dir)
        self.logger.open()

    def tearDown(self):
        """
        This command requires an existing logger to operate.
        Create the logger before each test
        """
        self.logger.close()
        self.logger._reset()

    def test_gather_success(self):
        """
        """

        (status, stdout, stderr) = exectools.cmd_gather("/usr/bin/echo hello there")
        self.logger.close()

        status_expected = 0
        stdout_expected = "hello there\n"
        stderr_expected = ""

        self.assertEquals(status_expected, status)
        self.assertEquals(stdout, stdout_expected)
        self.assertEquals(stderr, stderr_expected)

        # check that the log file has all of the tests.

        log_file = open(self.logger.log_path, 'r')
        lines = log_file.readlines()

        self.assertEquals(len(lines), 6)

    def test_gather_fail(self):
        """
        """

        (status, stdout, stderr) = exectools.cmd_gather(["/usr/bin/sed", "-e", "f"])

        self.logger.close()

        status_expected = 1
        stdout_expected = ""
        stderr_expected = "/usr/bin/sed: -e expression #1, char 1: unknown command: `f'\n"

        self.assertEquals(status_expected, status)
        self.assertEquals(stdout, stdout_expected)
        self.assertEquals(stderr, stderr_expected)

        # check that the log file has all of the tests.
        log_file = open(self.logger.log_path, 'r')
        lines = log_file.readlines()

        self.assertEquals(len(lines), 6)


if __name__ == "__main__":

    unittest.main()
