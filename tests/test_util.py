#!/usr/bin/env python
import unittest
from elliottlib import util


class UtilTestCase(unittest.TestCase):
    def test_override_product_version(self):
        """ if user specify -b branch will override product_version of erratatool.yml"""
        ret = util.override_product_version('RHEL-7-OSE-4.1', 'rhaos-4.1-rhel-8-candidate')
        self.assertEqual(ret, 'RHEL-8-OSE-4.1')

        ret = util.override_product_version('RHEL-7-OSE-4.1', 'rhaos-4.2-rhel-8')
        self.assertEqual(ret, 'RHEL-8-OSE-4.2')

        ret = util.override_product_version('RHEL-7-OSE-4.1', 'rhaos-4.1-rhel-7')
        self.assertEqual(ret, 'RHEL-7-OSE-4.1')


if __name__ == "__main__":
    unittest.main()
