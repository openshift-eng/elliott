#!/usr/bin/env python
"""
Test functions related to controlled command execution
"""

import asyncio
import unittest

from flexmock import flexmock
from unittest import mock

from elliottlib import exectools


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
        assertRaisesRegex = self.assertRaisesRegex if hasattr(self, 'assertRaisesRegex') else self.assertRaisesRegexp
        assertRaisesRegex(
            Exception, self.ERROR_MSG.format(1), exectools.retry, 1, fail_function)
        assertRaisesRegex(
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
        assertRaisesRegex = self.assertRaisesRegex if hasattr(self, 'assertRaisesRegex') else self.assertRaisesRegexp
        assertRaisesRegex(
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

    def test_cmd_assert_success(self):
        """
        """
        (flexmock(exectools.pushd.Dir)
            .should_receive("getcwd")
            .and_return("/my/path"))

        proc_mock = flexmock(returncode=0)
        proc_mock.should_receive("communicate").once().and_return((b"out", b"err"))

        (flexmock(exectools.subprocess)
            .should_receive("Popen")
            .and_return(proc_mock))

        (flexmock(exectools.logger)
            .should_receive("debug")
            .with_args('Executing:cmd_gather [cwd=/my/path]: ["/bin/true"]')
            .once()
            .ordered())

        (flexmock(exectools.logger)
            .should_receive("debug")
            .with_args('Process [cwd=/my/path]: ["/bin/true"]: exited with: 0\nstdout>>out<<\nstderr>>err<<\n')
            .once()
            .ordered())

        (flexmock(exectools.logger)
            .should_receive("debug")
            .with_args("cmd_assert: Final result = 0 in 0 tries.")
            .once()
            .ordered())

        try:
            exectools.cmd_assert("/bin/true")
        except IOError as error:
            self.Fail("/bin/truereturned failure: {}".format(error))

    def test_cmd_assert_fail(self):
        """
        """
        flexmock(exectools.time).should_receive("sleep").replace_with(lambda *_: None)

        (flexmock(exectools.pushd.Dir)
            .should_receive("getcwd")
            .and_return("/my/path"))

        proc_mock = flexmock(returncode=1)
        proc_mock.should_receive("communicate").times(3).and_return((b"out", b"err"))

        (flexmock(exectools.subprocess)
            .should_receive("Popen")
            .and_return(proc_mock))

        expected_log_calls = [
            "Executing:cmd_gather [cwd=/my/path]: [\"/usr/bin/false\"]",
            "Process [cwd=/my/path]: [\"/usr/bin/false\"]: exited with: 1\nstdout>>out<<\nstderr>>err<<\n",
            'cmd_assert: Failed 1 times. Retrying in 1 seconds: /usr/bin/false',
            "Executing:cmd_gather [cwd=/my/path]: [\"/usr/bin/false\"]",
            "Process [cwd=/my/path]: [\"/usr/bin/false\"]: exited with: 1\nstdout>>out<<\nstderr>>err<<\n",
            'cmd_assert: Failed 2 times. Retrying in 1 seconds: /usr/bin/false',
            "Executing:cmd_gather [cwd=/my/path]: [\"/usr/bin/false\"]",
            "Process [cwd=/my/path]: [\"/usr/bin/false\"]: exited with: 1\nstdout>>out<<\nstderr>>err<<\n",
            'cmd_assert: Final result = 1 in 2 tries.'
        ]

        for expected_log_call in expected_log_calls:
            (flexmock(exectools.logger)
                .should_receive("debug")
                .with_args(expected_log_call)
                .once()
                .ordered())

        self.assertRaises(IOError, exectools.cmd_assert, "/usr/bin/false", 3, 1)


class TestGather(unittest.IsolatedAsyncioTestCase):
    """
    """

    def test_gather_success(self):
        """
        """
        (flexmock(exectools.pushd.Dir)
            .should_receive("getcwd")
            .and_return("/my/path"))

        proc_mock = flexmock(returncode=0)
        proc_mock.should_receive("communicate").once().and_return((b"hello there\n", b""))

        (flexmock(exectools.subprocess)
            .should_receive("Popen")
            .and_return(proc_mock))

        (flexmock(exectools.logger)
            .should_receive("debug")
            .with_args('Executing:cmd_gather [cwd=/my/path]: ["/usr/bin/echo", "hello", "there"]')
            .once()
            .ordered())

        (flexmock(exectools.logger)
            .should_receive("debug")
            .with_args('Process [cwd=/my/path]: ["/usr/bin/echo", "hello", "there"]: exited with: 0\nstdout>>hello there\n<<\nstderr>><<\n')
            .once()
            .ordered())

        (status, stdout, stderr) = exectools.cmd_gather(
            "/usr/bin/echo hello there")
        status_expected = 0
        stdout_expected = "hello there\n"
        stderr_expected = ""

        self.assertEqual(status_expected, status)
        self.assertEqual(stdout, stdout_expected)
        self.assertEqual(stderr, stderr_expected)

    def test_gather_fail(self):
        """
        """
        flexmock(exectools.time).should_receive("sleep").replace_with(lambda *_: None)

        (flexmock(exectools.pushd.Dir)
            .should_receive("getcwd")
            .and_return("/my/path"))

        proc_mock = flexmock(returncode=1)
        (proc_mock
            .should_receive("communicate")
            .once()
            .and_return((b"", b"/usr/bin/sed: -e expression #1, char 1: unknown command: `f'\n")))

        (flexmock(exectools.subprocess)
            .should_receive("Popen")
            .and_return(proc_mock))

        (flexmock(exectools.logger)
            .should_receive("debug")
            .with_args('Executing:cmd_gather [cwd=/my/path]: ["/usr/bin/sed", "-e", "f"]')
            .once()
            .ordered())

        (flexmock(exectools.logger)
            .should_receive("debug")
            .with_args('Process [cwd=/my/path]: ["/usr/bin/sed", "-e", "f"]: exited with: 1\nstdout>><<\nstderr>>/usr/bin/sed: -e expression #1, char 1: unknown command: `f\'\n<<\n')
            .once()
            .ordered())

        (status, stdout, stderr) = exectools.cmd_gather(
            ["/usr/bin/sed", "-e", "f"])

        status_expected = 1
        stdout_expected = ""
        stderr_expected = "/usr/bin/sed: -e expression #1, char 1: unknown command: `f'\n"

        self.assertEqual(status_expected, status)
        self.assertEqual(stdout, stdout_expected)
        self.assertEqual(stderr, stderr_expected)

    async def test_cmd_gather_async(self):
        cmd = ["uname", "-a"]
        fake_cwd = "/foo/bar"
        fake_stdout = b"fake_stdout"
        fake_stderr = b"fake_stderr"
        with mock.patch("asyncio.create_subprocess_exec") as create_subprocess_exec, \
             mock.patch("elliottlib.pushd.Dir.getcwd", return_value=fake_cwd):
            proc = create_subprocess_exec.return_value
            proc.returncode = 0
            proc.communicate.return_value = (fake_stdout, fake_stderr)

            rc, out, err = await exectools.cmd_gather_async(cmd, text_mode=True)
            create_subprocess_exec.assert_called_once_with(*cmd, cwd=fake_cwd, stdout=asyncio.subprocess.PIPE,
                                                           stderr=asyncio.subprocess.PIPE)
            self.assertEqual(rc, 0)
            self.assertEqual(out, fake_stdout.decode("utf-8"))
            self.assertEqual(err, fake_stderr.decode("utf-8"))

            create_subprocess_exec.reset_mock()
            rc, out, err = await exectools.cmd_gather_async(cmd, text_mode=False)
            create_subprocess_exec.assert_called_once_with(*cmd, cwd=fake_cwd, stdout=asyncio.subprocess.PIPE,
                                                           stderr=asyncio.subprocess.PIPE)
            self.assertEqual(rc, 0)
            self.assertEqual(out, fake_stdout)
            self.assertEqual(err, fake_stderr)


if __name__ == "__main__":
    unittest.main()
