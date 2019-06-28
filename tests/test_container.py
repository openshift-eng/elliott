#!/usr/bin/env python
"""
Test Objects to manage Docker containers.
"""

import unittest

import mock

# The test module
import container


class TestDockerContainer(unittest.TestCase):
    """
    Test docker container object and methods
    """

    @mock.patch("container.exectools.pushd.Dir.getcwd", return_value="/my/path")
    @mock.patch("container.exectools.subprocess.Popen")
    @mock.patch("container.exectools.logger.debug")
    def test_cmd_logging(self, logger_debug, popen_mock, *_):
        """
        Test the internal wrapper function for exectools.cmd_gather().
        This method executes a command, logs both the command and stdout
        to the same log destination.

        For testing, just execute an echo and gather the output.
        """

        proc_mock = mock.Mock()
        proc_mock.communicate.return_value = ("out", "err")
        proc_mock.returncode = 999
        popen_mock.return_value = proc_mock

        expected_log_calls = [
            mock.call("Executing:cmd_gather [cwd=/my/path]: ['echo', 'hello']"),
            mock.call("Process [cwd=/my/path]: ['echo', 'hello']: exited with: 999\nstdout>>out<<\nstderr>>err<<\n")
        ]

        c0 = container.DockerContainer("test/image")
        c0._cmd("echo hello")

        self.assertEqual(expected_log_calls, logger_debug.mock_calls)


if __name__ == "__main__":
    unittest.main()
