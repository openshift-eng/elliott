#!/usr/bin/env python

import unittest
import bzutil

hostname = "bugzilla.redhat.com"


class TestSearchFilter(unittest.TestCase):

    def test_search_filter(self):
        """Verify the bugzilla SearchFilter works as expected"""
        field_name = "component"
        operator = "notequals"
        value = "RFE"
        expected = "&f1=component&o1=notequals&v1=RFE"

        sf = bzutil.SearchFilter(field_name, operator, value)
        self.assertEqual(sf.tostring(1), expected)

# class TestSearchURL(unittest.TestCase):

#     def test_searchurl(self):
#         """Verify SearchURL works as expected"""
#         t = bugzilla.SearchURL()

#         t.addFilter("component", "notequals", "RFE")
#         t.addFilter("component", "notequals", "Documentation")
#         t.addFilter("component", "notequals", "Security")
#         t.addFilter("cf_verified", "notequals", "FailedQA")
#         print "url = {}".format(t)
#         assert False

if __name__ == "__main__":
    unittest.main()
