from __future__ import absolute_import, print_function, unicode_literals
import unittest
import subprocess
from functional_tests import constants


class GreateTestCase(unittest.TestCase):
    def test_create_rhba(self):
        out = subprocess.check_output(
            constants.ELLIOTT_CMD
            + [
                "--group=openshift-4.2", "create", "--type=RHBA", "--impetus=standard", "--kind=rpm",
                "--date=2020-Jan-1", "--assigned-to=openshift-qe-errata@redhat.com", "--manager=vlaad@redhat.com", "--package-owner=lmeyer@redhat.com"
            ]
        )
        self.assertIn("Would have created advisory:", out.decode("utf-8"))
