#!/usr/bin/env python
"""
Test the ImageMetadata class
"""
import unittest

import flexmock

import image


class TestImageMetadata(unittest.TestCase):

    def test_base_only(self):
        """
        Some images are used only as a base for other images.  These base images
        are not included in a formal release.
        """

        rt = flexmock(logger=flexmock(debug=lambda *_: None))

        data_obj = flexmock(name="test",
                            distgit=flexmock(namespace="hello"),
                            key="_irrelevant_",
                            data=flexmock(items=lambda: [("name", "_irrelevant")]),
                            base_dir="_irrelevant_",
                            filename="_irrelevant_",
                            path="_irrelevant_")

        base_data_obj = flexmock(name="test",
                                 distgit=flexmock(namespace="hello"),
                                 key="_irrelevant_",
                                 data=flexmock(items=lambda: [("name", "_irrelevant"),
                                                              ("base_only", True)]),
                                 base_dir="_irrelevant_",
                                 filename="_irrelevant_",
                                 path="_irrelevant_")

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
