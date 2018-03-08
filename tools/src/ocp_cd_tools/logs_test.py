#!/usr/bin/env python
"""
"""

from __future__ import print_function

import unittest

import os
import tempfile
import atexit

import logs


class TestLog(unittest.TestCase):
    """
    Test the OIT logging system.  This is a "borg" pattern that simulates
    a singleton with shared data, but does not offer the equality test
    for the object that a proper singleton does.
    """

    def setUp(self):
        """
        Create a temporary directory as a destination for the log files.
        Make sure it is cleaned up and deleted when each test completes.

        Also since this is a borg, reset the state between tests so that
        each test is distinct.
        """
        logs.Log._reset()

        self.test_dir = tempfile.mkdtemp(prefix="ocp-cd-test-logs")
        atexit.register(logs._cleanup_log_dir, self.test_dir)

    def tearDown(self):
        logs.Log._reset()

    def test_init(self):
        """
        """
        log0 = logs.Log(self.test_dir)
        self.assertIsNotNone(log0.log_dir)
        self.assertEqual(logs.INFO, log0._log_level)

        self.assertTrue(os.path.isdir(log0.log_dir))

        self.assertIsNone(log0._record_file)

        logs.Log._reset()

        self.assertIsNone(log0._record_file)

    def test_singleton(self):
        log0 = logs.Log(self.test_dir)

        with self.assertRaises(OSError):
            logs.Log(log_dir="/tmp/bad_directory")

        try:
            logs.Log()
        except OSError as error:
            self.fail("creating a second borg raised: {}".format(error))

        current_log_dir = log0.log_dir

        log0._reset()

        with self.assertRaises(ValueError):
            logs.Log()

        tmpdir2 = tempfile.mkdtemp(prefix="ocp-cd-test-logs")
        atexit.register(logs._cleanup_log_dir, tmpdir2)
        log2 = logs.Log(tmpdir2)

        self.assertNotEquals(log2.log_dir, current_log_dir)

    def test_missing_dir(self):

        with self.assertRaises(OSError):
            logs.Log("/no/such/directory")

        logs.Log._reset()

        try:
            logs.Log("/not/a/directory")
        except OSError as error:
            expected = "directory not found: /not/a/directory"
            actual = error.message
            self.assertEquals(actual, expected)

    def test_open(self):
        log0 = logs.Log(self.test_dir)

        self.assertIsNone(log0._log_file)
        self.assertIsNone(log0._record_file)

        log0.open()

        self.assertIsInstance(log0._log_file, file)
        self.assertFalse(log0._log_file.closed)

        self.assertIsInstance(log0._record_file, file)
        self.assertFalse(log0._record_file.closed)

    def test_close(self):

        log0 = logs.Log(self.test_dir)
        log0.open()

        log0.close()

        self.assertIsInstance(log0._log_file, file)
        self.assertTrue(log0._log_file.closed)

        self.assertIsInstance(log0._record_file, file)
        self.assertTrue(log0._record_file.closed)

    def test_log_level_debug(self):
        log0 = logs.Log(log_dir=self.test_dir, log_level=logs.DEBUG)

        self.assertEquals(log0._log_level, logs.DEBUG)

        log_file = log0.log_path

        log0.open()

        log0.debug("a debug message")
        log0.info("an informational message")
        log0.warning("a warning message")
        log0.error("an error message")

        log0.close()

        text = open(log_file, 'r').readlines()

        # There should only be one line, marked DEBUG
        self.assertEquals(len(text), 4)

        self.assertRegexpMatches(text[0], "DEBUG")
        self.assertRegexpMatches(text[1], "INFO")
        self.assertRegexpMatches(text[2], "WARNING")
        self.assertRegexpMatches(text[3], "ERROR")

    def test_log_level_info(self):
        log0 = logs.Log(log_dir=self.test_dir, log_level=logs.INFO)

        self.assertEquals(log0._log_level, logs.INFO)

        log_file = log0.log_path

        log0.open()

        log0.debug("a debug message")
        log0.info("an informational message")
        log0.warning("a warning message")
        log0.error("an error message")

        log0.close()

        text = open(log_file, 'r').readlines()

        # There should only be one line, marked DEBUG
        self.assertEquals(len(text), 3)

        self.assertRegexpMatches(text[0], "INFO")
        self.assertRegexpMatches(text[1], "WARNING")
        self.assertRegexpMatches(text[2], "ERROR")

    def test_log_level_warning(self):
        log0 = logs.Log(log_dir=self.test_dir, log_level=logs.WARNING)

        self.assertEquals(log0._log_level, logs.WARNING)

        log_file = log0.log_path

        log0.open()

        log0.debug("a debug message")
        log0.info("an informational message")
        log0.warning("a warning message")
        log0.error("an error message")

        log0.close()

        text = open(log_file, 'r').readlines()

        # There should only be one line, marked DEBUG
        self.assertEquals(len(text), 2)

        self.assertRegexpMatches(text[0], "WARNING")
        self.assertRegexpMatches(text[1], "ERROR")

    def test_log_level_error(self):
        log0 = logs.Log(log_dir=self.test_dir, log_level=logs.ERROR)

        self.assertEquals(log0._log_level, logs.ERROR)

        log_file = log0.log_path

        log0.open()

        log0.debug("a debug message")
        log0.info("an informational message")
        log0.warning("a warning message")
        log0.error("an error message")

        log0.close()

        text = open(log_file, 'r').readlines()

        # There should only be one line, marked DEBUG
        self.assertEquals(len(text), 1)

        self.assertRegexpMatches(text[0], "ERROR")


class TestRecord(unittest.TestCase):

    def setUp(self):
        logs.Log._reset()
        # This is the first one and the user did not provide a location
        self.test_dir = tempfile.mkdtemp(prefix="oit-test-logs")
        atexit.register(logs._cleanup_log_dir, self.test_dir)

    def tearDown(self):
        logs.Log._reset()

    def test_record(self):

        expected = ['TEST|value2=foo|value1=this is a test record|\n']

        log0 = logs.Log(log_dir=self.test_dir)
        log0.open()
        record_file = log0.record_path
        log0.record("TEST", value1="this is a test record", value2="foo")
        log0.close()

        record_text = open(record_file, 'r').readlines()

        self.assertEqual(expected, record_text)


if __name__ == "__main__":
    unittest.main()
