#!/usr/bin/env python
"""
Test functions related to controlled command execution
"""

import unittest

import mock

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

    @mock.patch("exectools.pushd.Dir.getcwd", return_value="/my/path")
    @mock.patch("exectools.subprocess.Popen")
    @mock.patch("exectools.logger.debug")
    def test_cmd_assert_success(self, logger_debug, popen_mock, *_):
        """
        """

        proc_mock = mock.Mock()
        proc_mock.communicate.return_value = ("out", "err")
        proc_mock.returncode = 0
        popen_mock.return_value = proc_mock

        try:
            exectools.cmd_assert("/bin/true")
        except IOError as error:
            self.Fail("/bin/truereturned failure: {}".format(error))

        expected_log_calls = [
            mock.call("Executing:cmd_gather [cwd=/my/path]: ['/bin/true']"),
            mock.call("Process [cwd=/my/path]: ['/bin/true']: exited with: 0\nstdout>>out<<\nstderr>>err<<\n"),
            mock.call("cmd_assert: Final result = 0 in 0 tries.")
        ]

        self.assertEqual(expected_log_calls, logger_debug.mock_calls)

    @mock.patch("exectools.time.sleep", return_value=None)
    @mock.patch("exectools.pushd.Dir.getcwd", return_value="/my/path")
    @mock.patch("exectools.subprocess.Popen")
    @mock.patch("exectools.logger.debug")
    def test_cmd_assert_fail(self, logger_debug, popen_mock, *_):
        """
        """
        proc_mock = mock.Mock()
        proc_mock.communicate.return_value = ("out", "err")
        proc_mock.returncode = 1
        popen_mock.return_value = proc_mock

        # Try a failing command 3 times, at 1 sec intervals
        with self.assertRaises(IOError):
            exectools.cmd_assert("/usr/bin/false", 3, 1)

        expected_log_calls = [
            mock.call("Executing:cmd_gather [cwd=/my/path]: ['/usr/bin/false']"),
            mock.call("Process [cwd=/my/path]: ['/usr/bin/false']: exited with: 1\nstdout>>out<<\nstderr>>err<<\n"),
            mock.call('cmd_assert: Failed 1 times. Retrying in 1 seconds: /usr/bin/false'),
            mock.call("Executing:cmd_gather [cwd=/my/path]: ['/usr/bin/false']"),
            mock.call("Process [cwd=/my/path]: ['/usr/bin/false']: exited with: 1\nstdout>>out<<\nstderr>>err<<\n"),
            mock.call('cmd_assert: Failed 2 times. Retrying in 1 seconds: /usr/bin/false'),
            mock.call("Executing:cmd_gather [cwd=/my/path]: ['/usr/bin/false']"),
            mock.call("Process [cwd=/my/path]: ['/usr/bin/false']: exited with: 1\nstdout>>out<<\nstderr>>err<<\n"),
            mock.call('cmd_assert: Final result = 1 in 2 tries.')
        ]

        self.assertEqual(expected_log_calls, logger_debug.mock_calls)


class TestGather(unittest.TestCase):
    """
    """

    @mock.patch("exectools.pushd.Dir.getcwd", return_value="/my/path")
    @mock.patch("exectools.subprocess.Popen")
    @mock.patch("exectools.logger.debug")
    def test_gather_success(self, logger_debug, popen_mock, *_):
        """
        """

        proc_mock = mock.Mock()
        proc_mock.communicate.return_value = ("hello there\n", "")
        proc_mock.returncode = 0
        popen_mock.return_value = proc_mock

        (status, stdout, stderr) = exectools.cmd_gather(
            "/usr/bin/echo hello there")
        status_expected = 0
        stdout_expected = "hello there\n"
        stderr_expected = ""

        self.assertEquals(status_expected, status)
        self.assertEquals(stdout, stdout_expected)
        self.assertEquals(stderr, stderr_expected)

        expected_log_calls = [
            mock.call("Executing:cmd_gather [cwd=/my/path]: ['/usr/bin/echo', 'hello', 'there']"),
            mock.call("Process [cwd=/my/path]: ['/usr/bin/echo', 'hello', 'there']: exited with: 0\nstdout>>hello there\n<<\nstderr>><<\n")
        ]

        self.assertEqual(expected_log_calls, logger_debug.mock_calls)

    @mock.patch("exectools.time.sleep", return_value=None)
    @mock.patch("exectools.pushd.Dir.getcwd", return_value="/my/path")
    @mock.patch("exectools.subprocess.Popen")
    @mock.patch("exectools.logger.debug")
    def test_gather_fail(self, logger_debug, popen_mock, *_):
        """
        """

        proc_mock = mock.Mock()
        proc_mock.communicate.return_value = ("", "/usr/bin/sed: -e expression #1, char 1: unknown command: `f'\n")
        proc_mock.returncode = 1
        popen_mock.return_value = proc_mock

        (status, stdout, stderr) = exectools.cmd_gather(
            ["/usr/bin/sed", "-e", "f"])

        status_expected = 1
        stdout_expected = ""
        stderr_expected = "/usr/bin/sed: -e expression #1, char 1: unknown command: `f'\n"

        self.assertEquals(status_expected, status)
        self.assertEquals(stdout, stdout_expected)
        self.assertEquals(stderr, stderr_expected)

        expected_log_calls = [
            mock.call("Executing:cmd_gather [cwd=/my/path]: ['/usr/bin/sed', '-e', 'f']"),
            mock.call("Process [cwd=/my/path]: ['/usr/bin/sed', '-e', 'f']: exited with: 1\nstdout>><<\nstderr>>/usr/bin/sed: -e expression #1, char 1: unknown command: `f'\n<<\n")
        ]

        self.assertEqual(expected_log_calls, logger_debug.mock_calls)


if __name__ == "__main__":

    unittest.main()
