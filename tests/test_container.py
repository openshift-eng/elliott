#!/usr/bin/env python
"""
Test Objects to manage Docker containers.
"""

import unittest

import flexmock

# The test module
import container


class TestDockerContainer(unittest.TestCase):
    """
    Test docker container object and methods
    """

    def test_cmd_logging(self):
        """
        Test the internal wrapper function for exectools.cmd_gather().
        This method executes a command, logs both the command and stdout
        to the same log destination.

        For testing, just execute an echo and gather the output.
        """

        (flexmock(container.exectools.pushd.Dir)
            .should_receive("getcwd")
            .and_return("/my/path"))

        proc_mock = flexmock(returncode=999)
        proc_mock.should_receive("communicate").once().and_return(("out", "err"))

        (flexmock(container.exectools.subprocess)
            .should_receive("Popen")
            .and_return(proc_mock))

        (flexmock(container.exectools.logger)
            .should_receive("debug")
            .with_args("Executing:cmd_gather [cwd=/my/path]: ['echo', 'hello']")
            .once()
            .ordered())

        (flexmock(container.exectools.logger)
            .should_receive("debug")
            .with_args("Process [cwd=/my/path]: ['echo', 'hello']: exited with: 999\nstdout>>out<<\nstderr>>err<<\n")
            .once()
            .ordered())

        c0 = container.DockerContainer("test/image")
        c0._cmd("echo hello")


if __name__ == "__main__":
    unittest.main()
