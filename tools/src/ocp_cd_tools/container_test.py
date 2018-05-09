#!/usr/bin/env python
"""
Test Objects to manage Docker containers.
"""

import unittest

# Helper modules for testing
import string
import StringIO
import re
import logging

# The test module
import container


class TestDockerContainer(unittest.TestCase):
    """
    Test docker container object and methods
    """

    def setUp(self):
        """
        Define and provide mock logging for test/response
        """
        self.stream = StringIO.StringIO()
        logging.basicConfig(level=logging.DEBUG, stream=self.stream)
        self.logger = logging.getLogger()

    def tearDown(self):
        """
        Reset logging for each test.
        """
        logging.shutdown()
        reload(logging)

    def test_cmd_logging(self):
        """
        Test the internal wrapper function for exectools.cmd_gather().
        This method executes a command, logs both the command and stdout
        to the same log destination.

        For testing, just execute an echo and gather the output.
        """

        # The first two lines are RE patterns because the log entries
        # will contain the CWD path.
        expected = [
            "INFO:root:Executing:cmd_gather \[[^\]]+\]: \['echo', 'hello'\]",
            "INFO:root:Process \[[^\]]+\]: \['echo', 'hello'\]: exited with: 0",
            "stdout>>hello",
            "<<",
            "stderr>><<",
            "",
            ""
        ]

        c0 = container.DockerContainer("test/image")
        c0._cmd("echo hello")

        actual = self.stream.getvalue()
        lines = string.split(actual, "\n")
        self.assertEqual(len(lines), 7)

        # check that the first and second lines match the expected patterns.
        self.assertTrue(
            re.match(expected[0], lines[0]),
            "process exit line does not match: \n  actual: {}\n  expected {}".
            format(expected[1], lines[1])
        )
        self.assertTrue(
            re.match(expected[1], lines[1]),
            "process exit line does not match: \n  actual: {}\n  expected {}".
            format(expected[1], lines[1])
        )

        # The remainder of the output must match verbatim
        self.assertListEqual(lines[2:], expected[2:])

if __name__ == "__main__":
    unittest.main()
