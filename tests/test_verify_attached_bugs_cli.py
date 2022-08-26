import unittest
from click.testing import CliRunner
from elliottlib.cli.common import cli, Runtime
from elliottlib.cli.verify_attached_bugs_cli import BugValidator
from elliottlib.errata_async import AsyncErrataAPI
from elliottlib import errata
from elliottlib.bzutil import JIRABugTracker, BugzillaBugTracker
from flexmock import flexmock
import asyncio


def async_test(f):
    def wrapper(*args, **kwargs):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(f(*args, **kwargs))
    return wrapper


class VerifyAttachedBugs(unittest.TestCase):
    def test_validator_target_release(self):
        runtime = Runtime()
        flexmock(Runtime).should_receive("get_errata_config").and_return({})
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.9.z'], 'project': 'OpenShift Container Platform'})
        flexmock(AsyncErrataAPI).should_receive("__init__").and_return(None)
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.9.z'], 'product': 'OpenShift Container Platform'})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        validator = BugValidator(runtime, True)
        self.assertEqual(validator.target_releases, ['4.9.z'])

    def test_verify_bugs_cli(self):
        runner = CliRunner()
        flexmock(Runtime).should_receive("initialize")
        flexmock(Runtime).should_receive("get_errata_config").and_return({})
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'project': 'OCPBUGS', 'target_release': [
            '4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'product': 'OCPBUGS', 'target_release': [
            '4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")

        bugs = [
            flexmock(id="OCPBUGS-1", product='OCPBUGS', target_release=['4.6.z'], depends_on=['OCPBUGS-4'],
                     status='ON_QA'),
            flexmock(id="OCPBUGS-2", product='OCPBUGS', target_release=['4.6.z'], depends_on=['OCPBUGS-3'],
                     status='ON_QA')
        ]
        depend_on_bugs = [
            flexmock(id="OCPBUGS-3", product='OCPBUGS', target_release=['4.7.z'], status='ON_QA'),
            flexmock(id="OCPBUGS-4", product='OCPBUGS', target_release=['4.7.z'], status='Release Pending')
        ]
        flexmock(JIRABugTracker).should_receive("get_bugs").with_args(("OCPBUGS-1", "OCPBUGS-2")).and_return(bugs).ordered()
        flexmock(JIRABugTracker).should_receive("get_bugs").with_args(["OCPBUGS-3", "OCPBUGS-4"]).and_return(
            depend_on_bugs).ordered()

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'verify-bugs', 'OCPBUGS-1', 'OCPBUGS-2'])
        self.assertEqual(result.exit_code, 1)
        self.assertIn('Regression possible: ON_QA bug OCPBUGS-2 is a backport of bug OCPBUGS-3 which has status ON_QA', result.output)


class TestGetAttachedBugs(unittest.TestCase):
    @async_test
    async def test_get_attached_bugs(self):
        runtime = Runtime()
        bug_map = {
            'bug-1': flexmock(id='bug-1'),
            'bug-2': flexmock(id='bug-2'),
        }

        async def get_ad():
            return {'bugs': {'bugs': []}, 'content': {'content': {'errata_id': '12345'}}}

        flexmock(Runtime).should_receive("get_errata_config").and_return({})
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.9.z'], 'project': 'OpenShift Container Platform'})
        flexmock(AsyncErrataAPI).should_receive("__init__").and_return(None)
        flexmock(AsyncErrataAPI).should_receive("get_advisory").with_args("12345").and_return(get_ad())
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        flexmock(JIRABugTracker).should_receive("get_bugs_map").with_args(['bug-1', 'bug-2']).and_return(bug_map)
        flexmock(errata).should_receive("get_jira_issue_from_advisory").with_args('12345').and_return([{'key': 'bug-1'}, {'key': 'bug-2'}])
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.9.z'], 'product': 'OpenShift Container Platform'})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("get_bugs_map").and_return({})
        validator = BugValidator(runtime, True)
        bz_bugs, advisory_bugs = await validator.get_attached_bugs(['12345'])
        self.assertEqual(advisory_bugs, {'12345': {bug_map['bug-1'], bug_map['bug-2']}})


if __name__ == '__main__':
    unittest.main()
