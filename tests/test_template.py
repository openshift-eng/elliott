"""
Test the template functions
"""
import unittest

from elliottlib import template


class TestTemplate(unittest.TestCase):

    """
    Test the methods of the template module.

    Each raises an exception if the asserted test fails.
    """
    def test_render(self):
        topic_template = "Red Hat Product Security has rated this update as having a security impact of ${impact}."
        result = template.render_topic(topic_template, impact="Moderate")
        self.assertEqual(result, "Red Hat Product Security has rated this update as having a security impact of Moderate.")

    def test_render_no_template(self):
        topic_no_template = "Red Hat Product Security has rated this update as having a security impact of [[Important]]"
        result = template.render_topic(topic_no_template, impact="Moderate")
        self.assertEqual(result, "Red Hat Product Security has rated this update as having a security impact of [[Important]]")

    def test_render_brew_tag_product_version_mapping(self):
        product_map_template = "RHEL-7-OSE-${MAJOR}.${MINOR}"
        result = template.render(product_map_template, MAJOR="4", MINOR="7")
        self.assertEqual(result, "RHEL-7-OSE-4.7")

    def test_render_brew_tag_product_version_mapping(self):
        product_map_template = "RHEL-7-OSE-${MAJOR}.${MINOR}"
        kwargs = {"MAJOR": "4", "MINOR": "7"}
        result = template.render(product_map_template, **kwargs)
        self.assertEqual(result, "RHEL-7-OSE-4.7")


if __name__ == "__main__":
    unittest.main()
