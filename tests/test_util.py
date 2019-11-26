#!/usr/bin/env python
import unittest
from elliottlib import util


class UtilTestCase(unittest.TestCase):
    def test_override_product_version(self):
        ret = util.override_product_version('RHEL-7-OSE-4.1', 'rhaos-4.1-rhel-8-candidate')
        self.assertEqual(ret, 'OSE-4.1-RHEL-8')

        ret = util.override_product_version('RHEL-7-OSE-4.1', 'rhaos-4.2-rhel-8')
        self.assertEqual(ret, 'OSE-4.2-RHEL-8')

        ret = util.override_product_version('RHEL-7-OSE-4.1', 'rhaos-4.2-rhel-7')
        self.assertEqual(ret, 'RHEL-7-OSE-4.2')

        ret = util.override_product_version('RHEL-7-OSE-4.1', 'rhaos-4.1-rhel-7')
        self.assertEqual(ret, 'RHEL-7-OSE-4.1')


if __name__ == "__main__":
    unittest.main()
