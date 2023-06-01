from click.testing import CliRunner
from errata_tool import Erratum
from unittest.mock import patch
from elliottlib.cli.common import cli, Runtime
from elliottlib.cli.verify_attached_bugs_cli import BugValidator
import elliottlib.cli.verify_attached_bugs_cli as verify_attached_bugs_cli
from elliottlib.errata_async import AsyncErrataAPI
from elliottlib.bzutil import JIRABugTracker, BugzillaBugTracker
from flexmock import flexmock
from unittest import IsolatedAsyncioTestCase


class VerifyAttachedBugs(IsolatedAsyncioTestCase):
    async def test_validator_target_release(self):
        runtime = Runtime()
        flexmock(Runtime).should_receive("get_errata_config").and_return({})
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.9.z']})

        flexmock(AsyncErrataAPI).should_receive("__init__").and_return(None)
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        validator = BugValidator(runtime, True)
        self.assertEqual(validator.target_releases, ['4.9.z'])

    def test_verify_bugs_with_sweep_cli(self):
        runner = CliRunner()
        flexmock(Runtime).should_receive("initialize")
        flexmock(Runtime).should_receive("get_errata_config").and_return({})
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")

        bugs = [
            flexmock(id="OCPBUGS-1", target_release=['4.6.z'], depends_on=['OCPBUGS-4'],
                     status='ON_QA', is_ocp_bug=lambda: True, is_tracker_bug=lambda: False, is_invalid_tracker_bug=lambda: False),
            flexmock(id="OCPBUGS-2", target_release=['4.6.z'], depends_on=['OCPBUGS-3'],
                     status='ON_QA', is_ocp_bug=lambda: True, is_tracker_bug=lambda: False, is_invalid_tracker_bug=lambda: False)
        ]
        depend_on_bugs = [
            flexmock(id="OCPBUGS-3", target_release=['4.7.z'], status='MODIFIED',
                     is_ocp_bug=lambda: True, is_tracker_bug=lambda: False, is_invalid_tracker_bug=lambda: False),
            flexmock(id="OCPBUGS-4", target_release=['4.7.z'], status='Release Pending',
                     is_ocp_bug=lambda: True, is_tracker_bug=lambda: False, is_invalid_tracker_bug=lambda: False)
        ]
        blocking_bugs_map = {
            bugs[0]: [depend_on_bugs[1]],
            bugs[1]: [depend_on_bugs[0]],
        }

        flexmock(JIRABugTracker).should_receive("search").and_return(bugs)
        flexmock(BugzillaBugTracker).should_receive("search").and_return([])
        flexmock(BugValidator).should_receive("_get_blocking_bugs_for")\
            .and_return(blocking_bugs_map)

        result = runner.invoke(cli, ['-g', 'openshift-4.6', '--assembly=4.6.6', 'verify-bugs'])
        self.assertEqual(result.exit_code, 1)
        self.assertIn('Regression possible: ON_QA bug OCPBUGS-2 is a backport of bug OCPBUGS-3 which has status MODIFIED',
                      result.output)

    @patch('elliottlib.cli.verify_attached_bugs_cli.BugValidator.verify_bugs_multiple_advisories')
    @patch('elliottlib.errata_async.AsyncErrataAPI._generate_auth_header')
    def test_verify_attached_bugs_cli_fail(self, *_):
        runner = CliRunner()
        flexmock(Runtime).should_receive("initialize")
        flexmock(Runtime).should_receive("get_errata_config").and_return({})
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'project': 'OCPBUGS', 'target_release': [
            '4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'project': 'OCPBUGS', 'target_release': [
            '4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")

        bugs = [
            flexmock(id="OCPBUGS-1", target_release=['4.6.z'], depends_on=['OCPBUGS-4'],
                     status='ON_QA', is_ocp_bug=lambda: True, is_tracker_bug=lambda: False, is_invalid_tracker_bug=lambda: False),
            flexmock(id="OCPBUGS-2", target_release=['4.6.z'], depends_on=['OCPBUGS-3'],
                     status='ON_QA', is_ocp_bug=lambda: True, is_tracker_bug=lambda: False, is_invalid_tracker_bug=lambda: False)
        ]
        depend_on_bugs = [
            flexmock(id="OCPBUGS-3", target_release=['4.7.z'], status='MODIFIED',
                     is_ocp_bug=lambda: True, is_tracker_bug=lambda: False, is_invalid_tracker_bug=lambda: False),
            flexmock(id="OCPBUGS-4", target_release=['4.7.z'], status='Release Pending',
                     is_ocp_bug=lambda: True, is_tracker_bug=lambda: False, is_invalid_tracker_bug=lambda: False)
        ]
        blocking_bugs_map = {
            bugs[0]: [depend_on_bugs[1]],
            bugs[1]: [depend_on_bugs[0]],
        }

        advisory_id = 123
        flexmock(BugValidator).should_receive("get_attached_bugs").with_args([advisory_id])\
            .and_return({123: {bugs[0], bugs[1]}}).ordered()
        flexmock(BugValidator).should_receive("_get_blocking_bugs_for").and_return(blocking_bugs_map).ordered()
        flexmock(BugValidator).should_receive("verify_bugs_advisory_type")

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'verify-attached-bugs', str(advisory_id)])
        # if result.exit_code != 0:
        #     exc_type, exc_value, exc_traceback = result.exc_info
        #     t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        #     self.fail(t)
        self.assertEqual(result.exit_code, 1)
        self.assertIn('Regression possible: ON_QA bug OCPBUGS-2 is a backport of bug OCPBUGS-3 which has status '
                      'MODIFIED', result.output)

    @patch('elliottlib.cli.verify_attached_bugs_cli.BugValidator.verify_bugs_multiple_advisories')
    @patch('elliottlib.cli.verify_attached_bugs_cli.AsyncErrataAPI')
    def test_verify_attached_bugs_cli_fail_on_type(self, *_):
        runner = CliRunner()
        flexmock(Runtime).should_receive("initialize")
        flexmock(Runtime).should_receive("get_errata_config").and_return({})
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'project': 'OCPBUGS', 'target_release': [
            '4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'project': 'OCPBUGS', 'target_release': [
            '4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(Runtime).should_receive("get_default_advisories")\
            .and_return({'image': 1, 'rpm': 2, 'extras': 3, 'metadata': 4})

        bugs = [
            flexmock(id="OCPBUGS-1", is_ocp_bug=lambda: True),
            flexmock(id="OCPBUGS-2", is_ocp_bug=lambda: True),
            flexmock(id="OCPBUGS-3", is_ocp_bug=lambda: True)
        ]
        flexmock(BugValidator).should_receive("get_attached_bugs").and_return(
            {1: {bugs[0]}, 2: {bugs[1]}, 3: {bugs[2]}}
        )
        flexmock(BugValidator).should_receive("validate").and_return()
        flexmock(verify_attached_bugs_cli).should_receive("categorize_bugs_by_type").and_return(
            {'image': {bugs[2]}, 'rpm': {bugs[1]}, 'extras': {bugs[0]}}
        )

        result = runner.invoke(cli, ['-g', 'openshift-4.6', '--assembly', '4.6.50', 'verify-attached-bugs'])
        # if result.exit_code != 0:
        #     exc_type, exc_value, exc_traceback = result.exc_info
        #     t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        #     self.fail(t)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Expected Bugs not found in image advisory (1): ['OCPBUGS-3']",
                      result.output)
        self.assertIn("Unexpected Bugs found in image advisory (1): ['OCPBUGS-1']",
                      result.output)
        self.assertIn("Expected Bugs not found in extras advisory (3): ['OCPBUGS-1']",
                      result.output)
        self.assertIn("Unexpected Bugs found in extras advisory (3): ['OCPBUGS-3']",
                      result.output)


class TestBugValidator(IsolatedAsyncioTestCase):
    async def test_get_attached_bugs_jira(self):
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
        flexmock(JIRABugTracker).should_receive("get_bugs")\
            .with_args(list(jira_bug_map.keys()), permissive=False)\
            .and_return(jira_bug_map.values())
        flexmock(BugzillaBugTracker).should_receive("get_bugs")\
            .with_args(list(bz_bug_map.keys()), permissive=False)\
            .and_return(bz_bug_map.values())

        validator = BugValidator(runtime, True)
        actual = validator.get_attached_bugs(['123', '145'])
        expected = (
            {
                '123': {jira_bug_map['bug-1'], jira_bug_map['bug-2'], bz_bug_map[1]},
                '145': {jira_bug_map['bug-3'], bz_bug_map[2], bz_bug_map[3]}
            }
        )
        self.assertEqual(actual, expected)

    async def test_get_blocking_bugs_for(self):
        runtime = Runtime()
        flexmock(Runtime).should_receive("get_errata_config").and_return({})
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)

        bugs = [
            flexmock(id="OCPBUGS-1", target_release=['4.6.z'], depends_on=['OCPBUGS-4']),
            flexmock(id="OCPBUGS-2", target_release=['4.6.z'], depends_on=['OCPBUGS-3', 4]),
            flexmock(id=2, target_release=['4.6.z'], depends_on=[1, 3])
        ]
        depend_on_jira_bugs = [
            flexmock(id="OCPBUGS-3", target_release=['4.6.z'], component='foo', is_ocp_bug=lambda: True),
            flexmock(id="OCPBUGS-4", target_release=['4.7.z'], component='foo', is_ocp_bug=lambda: True)
        ]
        depend_on_bz_bugs = [
            flexmock(id=1, target_release=['4.7.z'], component='foo', is_ocp_bug=lambda: True),
            flexmock(id=3, target_release=['4.7.z'], component='not_managed_by_art', is_ocp_bug=lambda: True),
            flexmock(id=4, target_release=['4.7.z'], component='foo', is_ocp_bug=lambda: True),
        ]

        flexmock(JIRABugTracker).should_receive("get_bugs") \
            .with_args({b.id for b in depend_on_jira_bugs}) \
            .and_return(depend_on_jira_bugs)
        flexmock(JIRABugTracker).should_receive("component_filter").and_return(['not_managed_by_art'])
        flexmock(BugzillaBugTracker).should_receive("get_bugs") \
            .with_args({b.id for b in depend_on_bz_bugs}) \
            .and_return(depend_on_bz_bugs)

        validator = BugValidator(runtime, True)
        actual = validator._get_blocking_bugs_for(bugs)
        expected = {
            bugs[0]: [depend_on_jira_bugs[1]],
            bugs[1]: [depend_on_bz_bugs[2]],
            bugs[2]: [depend_on_bz_bugs[0]]
        }
        self.assertEqual(actual, expected)
        await validator.close()
