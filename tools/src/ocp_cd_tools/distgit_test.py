#!/usr/bin/env
"""
Test the management of distgit repositories for RPM and image builds
"""
import unittest

import ocp_cd_tools.distgit


class TestDistgit(unittest.TestCase):
    """
    Test the methods and functions used to manage and update distgit repos
    """

    def test_pull_image_logging(self):
        """
        Ensure that pull_image logs properly
        """
        self.fail("not tested")

if __name__ == "__main__":
    unittest.main()
