#!/usr/bin/env python
import unittest
from runtime import Runtime


class RuntimeTestCase(unittest.TestCase):
    def test_parallel_exec(self):
        ret = Runtime._parallel_exec(lambda x: x * 2, xrange(5), n_threads=20)
        self.assertEqual(ret.get(), [0, 2, 4, 6, 8])


if __name__ == "__main__":
    unittest.main()
