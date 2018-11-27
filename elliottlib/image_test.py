#!/usr/bin/env python
"""
Test the ImageMetadata class
"""
import unittest

import os
import logging
import tempfile
import shutil

import image

TEST_YAML = """---
name: 'test'
distgit:
  namespace: 'hello'"""

# base only images have have an additional flag
TEST_BASE_YAML = """---
name: 'test_base'
base_only: true
distgit:
  namespace: 'hello'"""

class MockRuntime(object):

    def __init__(self, logger):
        self.logger = logger


class TestImageMetadata(unittest.TestCase):

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
        rt = MockRuntime(self.logger)
        name = 'test.yml'

        md = image.ImageMetadata(rt, name)

        #
        # Check the logs
        #
        logs = [l.rstrip() for l in open(self.test_file).readlines()]

        expected = 1
        actual = len(logs)
        self.assertEqual(
            expected, actual,
            "logging lines - expected: {}, actual: {}".
            format(expected, actual))



    def test_base_only(self):
        """
        Some images are used only as a base for other images.  These base images
        are not included in a formal release.
        """

        test_base_yml = open('test_base.yml', 'w')
        test_base_yml.write(TEST_BASE_YAML)
        test_base_yml.close()

        rt = MockRuntime(self.logger)
        name = 'test.yml'
        name_base = 'test_base.yml'

        md = image.ImageMetadata(rt, name)
        md_base = image.ImageMetadata(rt, name_base)

        # Test the internal config value (will fail if implementation changes)
        # If the flag is absent, default to false
        self.assertFalse(md.config.base_only)
        self.assertTrue(md_base.config.base_only)

        # Test the base_only property of the ImageMetadata object
        self.assertFalse(md.base_only)
        self.assertTrue(md_base.base_only)

if __name__ == "__main__":
    unittest.main()
