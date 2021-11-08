#!/usr/bin/env python
"""
Test the ImageMetadata class
"""
import unittest

from flexmock import flexmock

from elliottlib import imagecfg


class TestImageMetadata(unittest.TestCase):

    def test_base_only(self):
        """
        Some images are used only as a base for other images.  These base images
        are not included in a formal release.
        """

        rt = flexmock(logger=flexmock(debug=lambda *_: None), assembly=None)
        rt.should_receive("get_releases_config")

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

        md = imagecfg.ImageMetadata(rt, data_obj)
        md_base = imagecfg.ImageMetadata(rt, base_data_obj)

        # Test the internal config value (will fail if implementation changes)
        # If the flag is absent, default to false
        self.assertFalse(md.config.base_only)
        self.assertTrue(md_base.config.base_only)

        # Test the base_only property of the ImageMetadata object
        self.assertFalse(md.base_only)
        self.assertTrue(md_base.base_only)


if __name__ == "__main__":
    unittest.main()
