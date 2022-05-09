import unittest
from unittest import mock
from unittest.mock import MagicMock, patch
from elliottlib.cli.verify_attached_bugs_cli import BugValidator
from elliottlib.errata_async import AsyncErrataAPI, AsyncErrataUtils
from elliottlib import errata
from elliottlib.bzutil import JIRABugTracker
from flexmock import flexmock
import asyncio


def async_test(f):
    def wrapper(*args, **kwargs):
        coro = asyncio.coroutine(f)
        future = coro(*args, **kwargs)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(future)
    return wrapper


class VerifyAttachedBugs(unittest.TestCase):
    def test_validator_target_release(self):
        runtime = MagicMock()
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.9.z'], 'product': 'OpenShift Container Platform'})
        flexmock(AsyncErrataAPI).should_receive("__init__").and_return(None)
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        validator = BugValidator(runtime, True)
        self.assertEqual(validator.target_releases, ['4.9.z'])


class TestGetAttachedBugs(unittest.TestCase):
    @async_test
    async def test_get_attached_bugs(self):
        runtime = MagicMock()
        bug_map = {
            'bug-1': flexmock(id='bug-1'),
            'bug-2': flexmock(id='bug-2'),
        }
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.9.z'], 'product': 'OpenShift Container Platform'})
        flexmock(AsyncErrataAPI).should_receive("__init__").and_return(None)
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        flexmock(JIRABugTracker).should_receive("get_bugs_map").with_args(['bug-1', 'bug-2']).and_return(bug_map)
        flexmock(errata).should_receive("get_jira_issue_from_advisory").with_args('12345').and_return([{'key': 'bug-1'}, {'key': 'bug-2'}])
        validator = BugValidator(runtime, True)
        advisory_bugs = await validator.get_attached_bugs(['12345'])
        self.assertEqual(advisory_bugs, {'12345': {bug_map['bug-1'], bug_map['bug-2']}})


if __name__ == '__main__':
    unittest.main()
