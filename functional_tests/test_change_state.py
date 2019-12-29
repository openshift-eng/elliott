from __future__ import absolute_import, print_function, unicode_literals
import unittest
import subprocess
from functional_tests import constants


class ChangeStateTestCase(unittest.TestCase):
    def test_change_state(self):
        p = subprocess.Popen(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-3.9", "change-state", "--state=QE", "--advisory=47924",
            ],
            stdout=subprocess.PIPE
        )
        out, _ = p.communicate()
        self.assertIn("Cannot change state from SHIPPED_LIVE to QE", out.decode("utf-8"))
