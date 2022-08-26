import unittest
from click.testing import CliRunner
from errata_tool import Erratum
from elliottlib.cli.common import cli, Runtime
from elliottlib.cli.verify_attached_bugs_cli import BugValidator, verify_bugs_cli
from elliottlib.errata_async import AsyncErrataAPI
from elliottlib.bzutil import JIRABugTracker, BugzillaBugTracker
from flexmock import flexmock
import asyncio
import traceback


def async_test(f):
    def wrapper(*args, **kwargs):
        coro = asyncio.coroutine(f)
        future = coro(*args, **kwargs)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(future)
    return wrapper


class VerifyAttachedBugs(unittest.TestCase):
    def test_validator_target_release(self):
        runtime = Runtime()
        flexmock(Runtime).should_receive("get_errata_config").and_return({})
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.9.z'], 'project': 'OpenShift Container Platform'})
        flexmock(AsyncErrataAPI).should_receive("__init__").and_return(None)
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        validator = BugValidator(runtime, True)
        self.assertEqual(validator.target_releases, ['4.9.z'])

    def test_verify_bugs_cli(self):
        runner = CliRunner()
        flexmock(Runtime).should_receive("initialize")
        flexmock(Runtime).should_receive("get_errata_config").and_return({})
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'project': 'OCPBUGS', 'target_release': [
            '4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")

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

    def test_verify_attached_bugs_cli(self):
        runner = CliRunner()
        advisory = flexmock(errata_id=123, jira_issues=["OCPBUGS-1", "OCPBUGS-2"], errata_bugs=[])
        flexmock(Runtime).should_receive("initialize")
        flexmock(Runtime).should_receive("get_errata_config").and_return({})
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'project': 'OCPBUGS', 'target_release': [
            '4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'project': 'OCPBUGS', 'target_release': [
            '4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")

        f = asyncio.Future()
        f.set_result(None)
        flexmock(AsyncErrataAPI).should_receive("login").and_return(f)
        flexmock(Erratum).new_instances(advisory).once()

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

        flexmock(JIRABugTracker).should_receive("get_bugs").with_args(["OCPBUGS-1", "OCPBUGS-2"],
                                                                      permissive=False).and_return(bugs).ordered()
        flexmock(JIRABugTracker).should_receive("get_bugs").with_args(["OCPBUGS-3", "OCPBUGS-4"]).and_return(depend_on_bugs).ordered()

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'verify-attached-bugs', str(advisory.errata_id)])
        # if result.exit_code != 0:
        #     exc_type, exc_value, exc_traceback = result.exc_info
        #     t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        #     self.fail(t)
        self.assertEqual(result.exit_code, 1)
        self.assertIn('Regression possible: ON_QA bug OCPBUGS-2 is a backport of bug OCPBUGS-3 which has status ON_QA',
                      result.output)


class TestGetAttachedBugs(unittest.TestCase):
    def test_get_attached_bugs_jira(self):
        runtime = Runtime()
        jira_bug_map = {
            'bug-1': flexmock(id='bug-1'),
            'bug-2': flexmock(id='bug-2'),
            'bug-3': flexmock(id='bug-3')
        }
        bz_bug_map = {
            1: flexmock(id=1),
            2: flexmock(id=2),
            3: flexmock(id=3)
        }
        flexmock(Runtime).should_receive("get_errata_config").and_return({})
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.9.z']})
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.9.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(AsyncErrataAPI).should_receive("__init__").and_return(None)

        advisory1 = flexmock(errata_id='123', jira_issues=['bug-1', 'bug-2'], errata_bugs=[1])
        advisory2 = flexmock(errata_id='145', jira_issues=['bug-3'], errata_bugs=[2, 3])
        flexmock(Erratum).new_instances(advisory1, advisory2)
        flexmock(JIRABugTracker).should_receive("get_bugs_map").with_args(list(jira_bug_map.keys())).and_return(
            jira_bug_map)
        flexmock(BugzillaBugTracker).should_receive("get_bugs_map").with_args(list(bz_bug_map.keys())).and_return(
            bz_bug_map)

        validator = BugValidator(runtime, True)
        actual = validator.get_attached_bugs(['123', '145'])
        expected = (
            {
                '123': {jira_bug_map['bug-1'], jira_bug_map['bug-2']},
                '145': {jira_bug_map['bug-3']}
            },
            {
                '123': {bz_bug_map[1]},
                '145': {bz_bug_map[2], bz_bug_map[3]}
            }
        )
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
