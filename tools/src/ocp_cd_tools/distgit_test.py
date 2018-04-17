#!/usr/bin/env
"""
Test the management of distgit repositories for RPM and image builds
"""
import unittest

import StringIO
import logging

import ocp_cd_tools.metadata as metadata
import ocp_cd_tools.distgit as distgit

class MockDistgit(object):
    def __init__(self):
        self.branch = None
        
class MockConfig(object):

    def __init__(self):
        self.distgit = MockDistgit()
        
class MockRuntime(object):
    
    def __init__(self, logger):
        self.branch = None
        self.distgits_dir = "distgits_dir"
        self.logger = logger
        
class MockMetadata(object):

    def __init__(self, runtime):
        self.config = MockConfig()
        self.runtime = runtime
        self.name = "test"
        self.namespace = "namespace"
        self.distgit_key = "distgit_key"


class TestDistgit(unittest.TestCase):
    """
    Test the methods and functions used to manage and update distgit repos
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

    def test_init(self):
        """
        Ensure that pull_image logs properly
        """
        md = MockMetadata(MockRuntime(self.logger))
        d = distgit.DistGitRepo(md, autoclone=False)

        self.assertIsInstance(d, distgit.DistGitRepo)

    def test_logging(self):
        """
        Ensure that pull_image logs properly
        """
        md = MockMetadata(MockRuntime(self.logger))
        d = distgit.DistGitRepo(md, autoclone=False)

        d.logger.info("Hey there!")

        expected = "INFO:[namespace/distgit_key]:Hey there!\n"
        actual = self.stream.getvalue()

        self.assertEquals(actual, expected)

    
    def test_pull_image_logging(self):
        """
        Ensure that pull_image logs properly
        """
        self.skipTest("test not implemented")

        
if __name__ == "__main__":
    unittest.main()
