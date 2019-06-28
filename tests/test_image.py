#!/usr/bin/env python
"""
Test the ImageMetadata class
"""
import unittest

import os
import logging
import tempfile
import shutil
import mock

import image


class TestImageMetadata(unittest.TestCase):

    def test_base_only(self):
        """
        Some images are used only as a base for other images.  These base images
        are not included in a formal release.
        """

        rt = mock.Mock()

        data_obj = mock.Mock(**{"name": "test",
                                "distgit.namespace": "hello",
                                "key": "_irrelevant_",
                                "data": {"name": "_irrelevant_"}})

        base_data_obj = mock.Mock(**{"name": "test_base",
                                     "distgit.namespace": "hello",
                                     "key": "_irrelevant_",
                                     "data": {"name": "_irrelevant_",
                                              "base_only": True}})

        md = image.ImageMetadata(rt, data_obj)
        md_base = image.ImageMetadata(rt, base_data_obj)

        # Test the internal config value (will fail if implementation changes)
        # If the flag is absent, default to false
        self.assertFalse(md.config.base_only)
        self.assertTrue(md_base.config.base_only)

        # Test the base_only property of the ImageMetadata object
        self.assertFalse(md.base_only)
        self.assertTrue(md_base.base_only)


if __name__ == "__main__":
    unittest.main()
