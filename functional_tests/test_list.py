from __future__ import absolute_import, print_function, unicode_literals
import unittest
import subprocess
from functional_tests import constants


class ListTestCase(unittest.TestCase):
    def test_sweep_bugs(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "list", "-n 1",
            ]
        )
        self.assertIn(constants.ERRATA_TOOL_URL, out.decode("utf-8"))
