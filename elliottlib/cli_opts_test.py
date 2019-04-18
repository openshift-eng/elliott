"""
Test the cli options functions
"""
import unittest

import cli_opts


class TestCLI(unittest.TestCase):
    """
    Test the methods of the assertion module.

    Each raises an exception if the asserted test fails.
    """
    def test_id_convert(self):
        self.assertEqual(cli_opts.id_convert(["1", "2", "3,4,5"]), [1, 2, 3, 4, 5])
        self.assertEqual(cli_opts.id_convert(["1,2,3", "4", "5"]), [1, 2, 3, 4, 5])
        self.assertEqual(cli_opts.id_convert(["1", "2", "3", "4", "5"]), [1, 2, 3, 4, 5])
        self.assertEqual(cli_opts.id_convert(["1,2,3,4,5"]), [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
