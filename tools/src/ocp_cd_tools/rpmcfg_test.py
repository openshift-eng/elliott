#!/usr/bin/env python
"""
Test the ImageMetadata class
"""
import unittest

import os
import logging
import StringIO
import tempfile
import shutil

import rpmcfg

TEST_YAML = """---
name: 'test'
content:
  source:
    alias: enterprise-images-upstream-example
distgit:
  namespace: 'hello'
"""


class MockRuntime(object):

    def __init__(self, tmpdir, logger):
        self.tmpdir = tmpdir
        self.logger = logger

    def resolve_source(self, alias):
        return self.tmpdir


class TestRPMMetadata(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="ocp-cd-test-logs")

        self.test_file = os.path.join(self.test_dir, "test_file")
        logging.basicConfig(filename=self.test_file, level=logging.DEBUG)
        self.logger = logging.getLogger()

        self.cwd = os.getcwd()
        os.chdir(self.test_dir)

        test_yml = open('test.yml', 'w')
        test_yml.write(TEST_YAML)
        test_yml.close()

        test_spec = open('test.spec', 'w')
        test_spec.write("")
        test_spec.close()

    def tearDown(self):
        os.chdir(self.cwd)

        logging.shutdown()
        reload(logging)
        shutil.rmtree(self.test_dir)

    def test_init(self):
        """
        The metadata object appears to need to be created while CWD is
        in the root of a git repo containing a file called '<name>.yml'
        This file must contain a structure:
           {'distgit': {'namespace': '<value>'}}

        The metadata object requires:
          a type string <image|rpm>
          a Runtime object placeholder

        """
        rt = MockRuntime(self.test_dir, self.logger)
        name = 'test.yml'

        md = rpmcfg.RPMMetadata(rt, name)

        #
        # Check the logs
        #
        logs = [l.rstrip() for l in open(self.test_file).readlines()]

        expected = 12
        actual = len(logs)

        self.assertEqual(
            expected, actual,
            "logging lines - expected: {}, actual: {}".
            format(expected, actual))


if __name__ == "__main__":
    unittest.main()
