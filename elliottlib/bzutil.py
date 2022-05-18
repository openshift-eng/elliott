"""
Utility functions and object abstractions for general interactions
with BugTrackers
"""
import asyncio
import itertools
import re
import urllib.parse
import xmlrpc.client
from datetime import datetime, timezone
from time import sleep
from typing import Dict, Iterable, List, Optional
from jira import JIRA, Issue

import bugzilla
import click
import os
from bugzilla.bug import Bug
from koji import ClientSession

from elliottlib import constants, exceptions, exectools, logutil, bzutil, errata, util
from elliottlib.metadata import Metadata
from elliottlib.util import isolate_timestamp_in_release, red_print

logger = logutil.getLogger(__name__)


# This is easier to patch in unit tests
def datetime_now():
    return datetime.now(timezone.utc)


class Bug:
    def __init__(self, bug_obj):
        self.bug = bug_obj

    def created_days_ago(self):
        created_date = self.creation_time_parsed()
        return (datetime_now() - created_date).days

    def creation_time_parsed(self):
        raise NotImplementedError

    def is_tracker_bug(self):
        return set(constants.TRACKER_BUG_KEYWORDS).issubset(set(self.bug.keywords))

    def is_flaw_bug(self):
        return self.bug.product == "Security Response" and self.bug.component == "vulnerability"

    @staticmethod
    def get_target_release(bugs: List[bzutil.Bug]) -> str:
        """
        Pass in a list of bugs and get their target release version back.
        Raises exception if they have different target release versions set.

        :param bugs: List[Bug] instance
        """
        invalid_bugs = []
        target_releases = set()

        if not bugs:
            raise ValueError("bugs should be a non empty list")

        for bug in bugs:
            # make sure it's a list with a valid str value
            valid_target_rel = isinstance(bug.target_release, list) and len(bug.target_release) > 0 and \
                re.match(r'(\d+.\d+.[0|z])', bug.target_release[0])
            if not valid_target_rel:
                invalid_bugs.append(bug)
            else:
                target_releases.add(bug.target_release[0])

        if invalid_bugs:
            err = 'target_release should be a list with a string matching regex (digit+.digit+.[0|z])'
            for b in invalid_bugs:
                err += f'\n bug: {b.id}, target_release: {b.target_release} '
            raise ValueError(err)

        if len(target_releases) != 1:
            err = f'Found different target_release values for bugs: {target_releases}. ' \
                'There should be only 1 target release for all bugs. Fix the offending bug(s) and try again.'
            raise ValueError(err)

        return target_releases.pop()


class BugzillaBug(Bug):
    def __getattr__(self, attr):
        if attr in self.__dict__:
            return getattr(self, attr)
        return getattr(self.bug, attr)

    def __init__(self, bug_obj):
        super().__init__(bug_obj)
        self.id = self.bug.id

    @property
    def target_release(self):
        return self.bug.target_release

    def creation_time_parsed(self):
        return datetime.strptime(str(self.bug.creation_time), '%Y%m%dT%H:%M:%S').replace(tzinfo=timezone.utc)


class JIRABug(Bug):
    def __init__(self, bug_obj: Issue):
        super().__init__(bug_obj)
        self.id = self.bug.key

    @property
    def weburl(self):
        return self.bug.permalink()

    @property
    def component(self):
        return self.bug.fields.components[0].name

    @property
    def status(self):
        return self.bug.fields.status.name

    @property
    def summary(self):
        return self.bug.fields.summary

    @property
    def blocks(self):
        return self._get_blocks()

    @property
    def keywords(self):
        return self.bug.fields.labels

    @property
    def version(self):
        return [x.name for x in self.bug.fields.versions]

    @property
    def target_release(self):
        return [x.name for x in self.bug.fields.fixVersions]

    @property
    def sub_component(self):
        return [c.name for c in self.bug.fields.components]

    @property
    def resolution(self):
        return self.bug.fields.resolution

    @property
    def depends_on(self):
        return self._get_depends()

    @property
    def release_blocker(self):
        return self._get_release_blocker()

    @property
    def severity(self):
        return self._get_severity()

    @property
    def produc(self):
        return self.bug.fields.project.key

    @property
    def alias(self):
        return self.bug.fields.labels

    @property
    def whiteboard(self):
        return self.bug.fields.labels

    def _get_release_blocker(self):
        # release blocker can be ['None','Approved'=='+','Proposed'=='?','Rejected'=='-']
        if self.bug.fields.customfield_12319743:
            return self.bug.fields.customfield_12319743.value
        return None

    def _get_blocked_reason(self):
        if self.bug.fields.customfield_12316544:
            return self.bug.fields.customfield_12316544.value
        return None

    def _get_severity(self):
        if self.bug.fields.customfield_12316142:
            if "Urgent" in self.bug.fields.customfield_12316142.value:
                return "Urgent"
            if "High" in self.bug.fields.customfield_12316142.value:
                return "High"
            if "Medium" in self.bug.fields.customfield_12316142.value:
                return "Medium"
            if "Low" in self.bug.fields.customfield_12316142.value:
                return "Low"
        return None

    def creation_time_parsed(self):
        return datetime.strptime(str(self.bug.fields.created), '%Y-%m-%dT%H:%M:%S.%f%z')

    def _get_blocks(self):
        blocks = []
        for link in self.bug.fields.issuelinks:
            if link.type.name == "Blocks" and hasattr(link, "outwardIssue"):
                blocks.append(link.outwardIssue.key)
        return blocks

    def _get_depends(self):
        depends = []
        for link in self.bug.fields.issuelinks:
            if link.type.name == "Blocks" and hasattr(link, "inwardIssue"):
                depends.append(link.inwardIssue.key)
        return depends


class BugTracker:
    def __init__(self, config):
        self.config = config
        self._server = config['bugzilla_config'].get('server', '') if config.get('bugzilla_config') else ''
        self._jira_server = config['jira_config'].get('server', '') if config.get('jira_config') else ''

    def target_release(self) -> List:
        return self.config.get('target_release')

    def search(self, status, search_filter, verbose=False, **kwargs):
        raise NotImplementedError

    def blocker_search(self, status, search_filter, verbose=False, **kwargs):
        raise NotImplementedError

    def get_bug(self, bugid, **kwargs):
        raise NotImplementedError

    def get_bugs(self, bugids: List, permissive=False, **kwargs):
        raise NotImplementedError

    def get_bugs_map(self, bugids: List, permissive: bool = False, **kwargs) -> Dict:
        id_bug_map = {}
        bugs = self.get_bugs(bugids, permissive=permissive, **kwargs)
        for i, bug in enumerate(bugs):
            id_bug_map[bugids[i]] = bug
        return id_bug_map

    def attach_bugs(self, advisory_id: int, bugids: List, noop=False, verbose=False):
        raise NotImplementedError

    def add_comment(self, bugid, comment: str, private: bool, noop=False):
        raise NotImplementedError

    def create_bug(self, bug_title, bug_description, target_status, keywords: List, noop=False):
        raise NotImplementedError

    def _update_bug_status(self, bugid, target_status):
        raise NotImplementedError

    def create_placeholder(self, kind, noop=False):
        title = f"Placeholder bug for OCP {self.config.get('target_release')[0]} {kind} release"
        return self.create_bug(title, title, "VERIFIED", ["Automation"], noop)

    def create_textonly(self, bug_title, bug_description, noop=False):
        return self.create_bug(bug_title, bug_description, "VERIFIED", [], noop)

    def update_bug_status(self, bug: Bug, target_status: str,
                          comment: Optional[str] = None, log_comment: bool = True, noop=False):
        current_status = bug.status
        action = f'changed {bug.id} from {current_status} to {target_status}'
        if current_status == target_status:
            click.echo(f'{bug.id} is already on {target_status}')
            return
        elif noop:
            click.echo(f"Would have {action}")
        else:
            self._update_bug_status(bug.id, target_status)
            click.echo(action)

        comment_lines = []
        if log_comment:
            comment_lines.append(f'Elliott changed bug status from {current_status} to {target_status}.')
        if comment:
            comment_lines.append(comment)
        if comment_lines:
            self.add_comment(bug.id, '\n'.join(comment_lines), private=True, noop=noop)


class JIRABugTracker(BugTracker):
    @staticmethod
    def get_config(runtime) -> Dict:
        major, minor = runtime.get_major_minor()
        version = f'{major}.{minor}'
        # TODO: have jira.yml file for all versions 4.6-4.11
        if version != '4.11':
            return {
                'server': "https://issues.stage.redhat.com",
                'project': 'OCPBUGS',
                'target_release': [f"{version}.0", f"{version}.z"]
            }
        return runtime.gitdata.load_data(key='bug').data

    def login(self, token_auth=None) -> JIRA:
        if not token_auth:
            token_auth = os.environ.get("JIRA_TOKEN")
            if not token_auth:
                raise ValueError(f"elliott requires login credentials for {self._jira_server}. Set a JIRA_TOKEN env var ")
        client = JIRA(self._jira_server, token_auth=token_auth)
        return client

    def __init__(self, config):
        super().__init__(config)
        self._project = config['jira_config'].get('project', '') if config.get('jira_config') else ''
        self._client: JIRA = self.login()

    def get_bug(self, bugid: str, **kwargs) -> JIRABug:
        return JIRABug(self._client.issue(bugid, **kwargs))

    def get_bugs(self, bugids: List[str], permissive=False, verbose=False, check_tracker=False, **kwargs) -> List[JIRABug]:
        query = self._query(bugids=bugids, with_target_release=False)
        if verbose:
            click.echo(query)
        bugs = self._search(query, **kwargs)
        if not permissive and len(bugs) < len(bugids):
            raise ValueError(f"Not all bugs were not found, {len(bugs)} out of {len(bugids)}")
        if check_tracker:
            bugs = [bug for bug in bugs if bug.is_tracker_bug()]
        return bugs

    def get_bug_remote_links(self, bug: JIRABug):
        remote_links = self._client.remote_links(bug)
        link_dict = {}
        for link in remote_links:
            if link.__contains__('relationship'):
                link_dict[link.relationship] = link.object.url
        return link_dict

    def create_bug(self, bug_title: str, bug_description: str, target_status: str, keywords: List, noop=False) -> \
            JIRABug:
        fields = {
            'project': {'key': self._project},
            'issuetype': {'name': 'Bug'},
            'fixVersions': {'name': self.config.get('version')[0]},
            'components': {'name': 'Release'},
            'summary': bug_title,
            'labels': keywords,
            'description': bug_description
        }
        if noop:
            logger.info(f"Would have created JIRA Issue with status={target_status} and fields={fields}")
            return
        bug = self._client.create_issue(fields=fields)
        self._client.transition_issue(bug, target_status)
        return JIRABug(bug)

    def _update_bug_status(self, bugid, target_status):
        return self._client.transition_issue(bugid, target_status)

    def add_comment(self, bugid: str, comment: str, private: bool, noop=False):
        if noop:
            click.echo(f"Would have added a private={private} comment to {bugid}")
            return
        if private:
            self._client.add_comment(bugid, comment, visibility={'type': 'group', 'value': 'Red Hat Employee'})
        else:
            self._client.add_comment(bugid, comment)

    def _query(self, bugids: Optional[List] = None,
               status: Optional[List] = None,
               target_release: Optional[List] = None,
               include_labels: Optional[List] = None,
               exclude_labels: Optional[List] = None,
               with_target_release: bool = True,
               search_filter: str = None) -> str:

        if target_release and with_target_release:
            raise ValueError("cannot use target_release and with_target_release together")
        if not target_release and with_target_release:
            target_release = self.target_release()

        exclude_components = []
        if search_filter:
            exclude_components = self.config.get('filters', {}).get(search_filter)

        query = f"project={self._project}"
        if bugids:
            query += f" and issue in ({','.join(bugids)})"
        if status:
            query += f" and status in ({','.join(status)})"
        if target_release:
            query += f" and fixVersion in ({','.join(target_release)})"
        if include_labels:
            query += f" and labels in ({','.join(exclude_labels)})"
        if exclude_labels:
            query += f" and labels not in ({','.join(exclude_labels)})"
        if exclude_components:
            val = ','.join(f'"{c}"' for c in exclude_components)
            query += f" and component not in ({val})"
        return query

    def _search(self, query, verbose=False, **kwargs) -> List[JIRABug]:
        if verbose:
            click.echo(query)
        return [JIRABug(j) for j in self._client.search_issues(query, maxResults=False, **kwargs)]

    def blocker_search(self, status, search_filter='default', verbose=False, **kwargs):
        # TODO this would be the release_blocker custom field instead of label
        include_labels = ['blocker+']
        query = self._query(
            status=status,
            include_labels=include_labels,
            target_release=self.target_release(),
            search_filter=search_filter
        )
        return self._search(query, verbose=verbose, **kwargs)

    def search(self, status, search_filter='default', verbose=False, **kwargs):
        query = self._query(
            status=status,
            search_filter=search_filter
        )
        return self._search(query, verbose=verbose, **kwargs)

    def attach_bugs(self, advisory_id: int, bugids: List, noop=False, verbose=False):
        return errata.add_jira_bugs_with_retry(advisory_id, bugids, noop=noop)

    def filter_bugs_by_cutoff_event(self, bugs: Iterable, desired_statuses: Iterable[str],
                                    sweep_cutoff_timestamp: float) -> List:
        dt = datetime.utcfromtimestamp(sweep_cutoff_timestamp).strftime("%Y/%m/%d %H:%M")
        query = f"issue in ({','.join([b.id for b in bugs])}) " \
                f"and status was in ({','.join(desired_statuses)}) " \
                f'before("{dt}")'
        return self._search(query, verbose=True)


class BugzillaBugTracker(BugTracker):
    @staticmethod
    def get_config(runtime):
        return runtime.gitdata.load_data(key='bug').data

    def login(self):
        client = bugzilla.Bugzilla(self._server)
        if not client.logged_in:
            raise ValueError(f"elliott requires cached login credentials for {self._server}. Login using 'bugzilla "
                             "login --api-key")
        return client

    def __init__(self, config):
        super().__init__(config)
        self._client = self.login()

    def get_bug(self, bugid, **kwargs):
        return BugzillaBug(self._client.getbug(bugid, **kwargs))

    def get_bugs(self, bugids, permissive=False, check_tracker=False, **kwargs):
        if check_tracker:
            return [BugzillaBug(b) for b in self._client.getbugs(bugids, permissive=permissive, **kwargs) if BugzillaBug(b).is_tracker_bug()]
        return [BugzillaBug(b) for b in self._client.getbugs(bugids, permissive=permissive, **kwargs)]

    def client(self):
        return self._client

    def blocker_search(self, status, search_filter='default', verbose=False):
        query = _construct_query_url(self.config, status, search_filter, flag='blocker+')
        fields = ['id', 'status', 'summary', 'creation_time', 'cf_pm_score', 'component', 'sub_component', 'external_bugs', 'whiteboard',
                  'keywords', 'target_release']
        return self._search(query, fields, verbose)

    def search(self, status, search_filter='default', verbose=False):
        query = _construct_query_url(self.config, status, search_filter)
        fields = ['id', 'status', 'summary', 'creation_time', 'cf_pm_score', 'component', 'sub_component', 'external_bugs', 'whiteboard',
                  'keywords', 'target_release']
        return self._search(query, fields, verbose)

    def _search(self, query, fields, verbose=False):
        if verbose:
            click.echo(query)
        return [BugzillaBug(b) for b in _perform_query(self._client, query, include_fields=fields)]

    def attach_bugs(self, advisory_id: int, bugids: List, noop=False, verbose=False):
        return errata.add_bugzilla_bugs_with_retry(advisory_id, bugids, noop=noop)

    def create_bug(self, title, description, target_status, keywords: List, noop=False) -> BugzillaBug:
        create_info = self._client.build_createbug(
            product=self.config.get('bugzilla_config').get('product'),
            version=self.config.get('version')[0],
            target_release=self.config.get('target_release')[0],
            component="Release",
            summary=title,
            keywords=keywords,
            description=description)
        if noop:
            logger.info(f"Would have created BugzillaBug with status={target_status} and fields={create_info}")
            return
        new_bug = self._client.createbug(create_info)
        # change state to VERIFIED
        try:
            update = self._client.build_update(status=target_status)
            self._client.update_bugs([new_bug.id], update)
        except Exception as ex:  # figure out the actual bugzilla error. it only happens sometimes
            sleep(5)
            self._client.update_bugs([new_bug.id], update)
            print(ex)

        return BugzillaBug(new_bug)

    def _update_bug_status(self, bugid, target_status):
        return self._client.update_bugs([bugid], self._client.build_update(status=target_status))

    def add_comment(self, bugid, comment: str, private, noop=False):
        self._client.update_bugs([bugid], self._client.build_update(comment=comment, comment_private=private))

    def filter_bugs_by_cutoff_event(self, bugs: Iterable, desired_statuses: Iterable[str],
                                    sweep_cutoff_timestamp: float) -> List:
        """ Given a list of bugs, finds those that have changed to one of the desired statuses before the given timestamp.

        According to @jupierce:

        Let:
        - Z be a non-closed BZ in a monitored component
        - S2 be the current state (as in the moment we are scanning) of Z
        - S1 be the state of the Z at the moment of the cutoff
        - A be the set of state changes Z after the cutoff
        - F be the sweep states (MODIFIED, ON_QA, VERIFIED)

        Then Z is swept in if all the following are true:
        - S1 ∈ F
        - S2 ∈ F
        - A | ∄v : v <= S1

        In prose: if a BZ seems to qualify for a sweep currently and at the cutoff event, then all state changes after the cutoff event must be to a greater than the state which qualified the BZ at the cutoff event.

        :param bugs: a list of bugs
        :param desired_statuses: desired bug statuses
        :param sweep_cutoff_timestamp: a unix timestamp
        :return: a list of found bugs
        """
        qualified_bugs = []
        desired_statuses = set(desired_statuses)

        # Filters out bugs that are created after the sweep cutoff timestamp
        before_cutoff_bugs = [bug for bug in bugs if to_timestamp(bug.creation_time) <= sweep_cutoff_timestamp]
        if len(before_cutoff_bugs) < len(bugs):
            logger.info(
                f"{len(bugs) - len(before_cutoff_bugs)} of {len(bugs)} bugs are ignored because they were created after the sweep cutoff timestamp {sweep_cutoff_timestamp} ({datetime.utcfromtimestamp(sweep_cutoff_timestamp)})")

        # Queries bug history
        bugs_history = self._client.bugs_history_raw([bug.id for bug in before_cutoff_bugs])

        class BugStatusChange:
            def __init__(self, timestamp: int, old: str, new: str) -> None:
                self.timestamp = timestamp  # when this change is made?
                self.old = old  # old status
                self.new = new  # new status

            @classmethod
            def from_history_ent(cls, history):
                """ Converts from bug history dict returned from Bugzilla to BugStatusChange object.
                The history dict returned from Bugzilla includes bug changes on all fields, but we are only interested in the "status" field change.
                :return: BugStatusChange object, or None if the history doesn't include a "status" field change.
                """
                status_change = next(filter(lambda change: change["field_name"] == "status", history["changes"]), None)
                if not status_change:
                    return None
                return cls(to_timestamp(history["when"]), status_change["removed"], status_change["added"])

        for bug, bug_history in zip(before_cutoff_bugs, bugs_history["bugs"]):
            assert bug.id == bug_history[
                "id"]  # `bugs_history["bugs"]` returned from Bugzilla API should have the same order as `before_cutoff_bugs`, but be safe

            # We are only interested in "status" field changes
            status_changes = filter(None, map(BugStatusChange.from_history_ent, bug_history["history"]))

            # status changes after the cutoff event
            after_cutoff_status_changes = list(
                itertools.dropwhile(lambda change: change.timestamp <= sweep_cutoff_timestamp, status_changes))

            # determines the status of the bug at the moment of the sweep cutoff event
            if not after_cutoff_status_changes:
                sweep_cutoff_status = bug.status  # no status change after the cutoff event; use current status
            else:
                sweep_cutoff_status = after_cutoff_status_changes[
                    0].old  # sweep_cutoff_status should be the old status of the first status change after the sweep cutoff event

            if sweep_cutoff_status not in desired_statuses:
                logger.info(
                    f"BZ {bug.id} is ignored because its status was {sweep_cutoff_status} at the moment of sweep cutoff ({datetime.utcfromtimestamp(sweep_cutoff_timestamp)})")
                continue

            # Per @Justin Pierce: If a BZ seems to qualify for a sweep currently and at the sweep cutoff event, then all state changes after the sweep cutoff event must be to a greater than the state which qualified the BZ at the sweep cutoff event.
            regressed_changes = [change.new for change in after_cutoff_status_changes if
                                 constants.VALID_BUG_STATES.index(change.new) <= constants.VALID_BUG_STATES.index(
                                     sweep_cutoff_status)]
            if regressed_changes:
                logger.warning(
                    f"BZ {bug.id} is ignored because its status was {sweep_cutoff_status} at the moment of sweep cutoff ({datetime.utcfromtimestamp(sweep_cutoff_timestamp)})"
                    f", however its status changed back to {regressed_changes} afterwards")
                continue

            qualified_bugs.append(bug)

        return qualified_bugs


def get_corresponding_flaw_bugs(bug_tracker, tracker_bugs: List, fields: List, strict: bool = False):
    """
    Get corresponding flaw bugs objects for the
    given tracker bug objects
    :return (tracker_flaws, flaw_id_bugs): tracker_flaws is a dict with tracker bug id as key and list of flaw bug id as value,
                                        flaw_bugs is a dict with flaw bug id as key and flaw bug object as value
    """
    # fields needed for is_flaw_bug()
    if "product" not in fields:
        fields.append("product")
    if "component" not in fields:
        fields.append("component")

    blocking_bugs = bug_tracker.get_bugs(list(set(sum([t.blocks for t in tracker_bugs], []))), include_fields=fields)
    flaw_id_bugs: Dict[int, Bug] = {bug.id: bug for bug in blocking_bugs if bug.is_flaw_bug()}

    # Validate that each tracker has a corresponding flaw bug
    flaw_ids = set(flaw_id_bugs.keys())
    no_flaws = set()
    for tracker in tracker_bugs:
        if not set(tracker.blocks).intersection(flaw_ids):
            no_flaws.add(tracker.id)
    if no_flaws:
        msg = f'No flaw bugs could be found for these trackers: {no_flaws}'
        if strict:
            raise exceptions.ElliottFatalError(msg)
        else:
            logger.warn(msg)

    tracker_flaws: Dict[int, List[int]] = {
        tracker.id: [blocking for blocking in tracker.blocks if blocking in flaw_id_bugs]
        for tracker in tracker_bugs
    }
    return tracker_flaws, flaw_id_bugs


def get_highest_impact(trackers, tracker_flaws_map):
    """Get the highest impact of security bugs

    :param trackers: The list of tracking bugs you want to compare to get the highest severity
    :param tracker_flaws_map: A dict with tracking bug IDs as keys and lists of flaw bugs as values
    :return: The highest impact of the bugs
    """
    severity_index = 0  # "unspecified" severity
    for tracker in trackers:
        tracker_severity = constants.BUG_SEVERITY_NUMBER_MAP[tracker.severity.lower()]
        if tracker_severity == 0:
            # When severity isn't set on the tracker, check the severity of the flaw bugs
            # https://jira.coreos.com/browse/ART-1192
            flaws = tracker_flaws_map[tracker.id]
            for flaw in flaws:
                flaw_severity = constants.BUG_SEVERITY_NUMBER_MAP[flaw.severity.lower()]
                if flaw_severity > tracker_severity:
                    tracker_severity = flaw_severity
        if tracker_severity > severity_index:
            severity_index = tracker_severity
    if severity_index == 0:
        # When severity isn't set on all tracking and flaw bugs, default to "Low"
        # https://jira.coreos.com/browse/ART-1192
        logger.warning("CVE impact couldn't be determined for tracking bug(s); defaulting to Low.")
    return constants.SECURITY_IMPACT[severity_index]


def get_flaw_bugs(trackers):
    """Get a list of flaw bugs blocked by a list of tracking bugs. For a definition of these terms see
    https://docs.engineering.redhat.com/display/PRODSEC/%5BDRAFT%5D+Security+bug+types

    :param trackers: A list of tracking bugs

    :return: A list of flaw bug ids
    """
    flaw_ids = []
    for t in trackers:
        # Tracker bugs can block more than one flaw bug, but must be more than 0
        if not t.blocks:
            # This should never happen, log a warning here if it does
            logger.warning("Warning: found tracker bugs which doesn't block any other bugs")
        else:
            flaw_ids.extend(t.blocks)
    return flaw_ids


def get_tracker_flaws_map(bz_bug_tracker: BugzillaBugTracker, trackers: List):
    """Get flaw bugs blocked by tracking bugs. For a definition of these terms see
    https://docs.engineering.redhat.com/display/PRODSEC/%5BDRAFT%5D+Security+bug+types

    :param bz_bug_tracker: An instance of the BugzillaBugTracker class
    :param trackers: A list of tracking bugs

    :return: A dict with tracking bug IDs as keys and lists of flaw bugs as values
    """
    tracker_flaw_ids_map = {
        tracker.id: get_flaw_bugs([tracker]) for tracker in trackers
    }

    flaw_ids = [flaw_id for _, flaw_ids in tracker_flaw_ids_map.items() for flaw_id in flaw_ids]
    flaw_id_bug_map = bz_bug_tracker.get_bugs_map(flaw_ids)

    tracker_flaws_map = {tracker.id: [] for tracker in trackers}
    for tracker_id, flaw_ids in tracker_flaw_ids_map.items():
        for flaw_id in flaw_ids:
            flaw_bug = flaw_id_bug_map.get(flaw_id)
            if not flaw_bug or not is_flaw_bug(flaw_bug):
                logger.warning("Bug {} is not a flaw bug.".format(flaw_id))
                continue
            tracker_flaws_map[tracker_id].append(flaw_bug)
    return tracker_flaws_map


def is_flaw_bug(bug):
    return bug.product == "Security Response" and bug.component == "vulnerability"


def get_flaw_aliases(flaws):
    """Get a map of flaw bug ids and associated CVE aliases. For a definition of these terms see
    https://docs.engineering.redhat.com/display/PRODSEC/%5BDRAFT%5D+Security+bug+types

    :param bzapi: An instance of the python-bugzilla Bugzilla class
    :param flaws: Flaw bugs you want to get the aliases for

    :return: A map of flaw bug ids and associated CVE alisas.

    :raises:
        BugzillaFatalError: If bugs contains invalid bug ids, or if some other error occurs trying to
        use the Bugzilla XMLRPC api. Could be because you are not logged in to Bugzilla or the login
        session has expired.
    """
    flaw_cve_map = {}
    for flaw in flaws:
        if flaw is None:
            raise exceptions.BugzillaFatalError("Couldn't find bug with list of ids provided")
        if flaw.product == "Security Response" and flaw.component == "vulnerability":
            alias = flaw.alias
            if len(alias) >= 1:
                logger.debug("Found flaw bug with more than one alias, only alias which starts with CVE-")
                for a in alias:
                    if a.startswith('CVE-'):
                        flaw_cve_map[flaw.id] = a
            else:
                flaw_cve_map[flaw.id] = ""
    for key in flaw_cve_map.keys():
        if flaw_cve_map[key] == "":
            logger.warning("Found flaw bug with no alias, this can happen if a flaw hasn't been assigned to a CVE")
    return flaw_cve_map


def is_viable_bug(bug_obj):
    """ Check if a bug is viable to attach to an advisory.

    A viable bug must be in one of MODIFIED and VERIFIED status. We accept ON_QA
    bugs as viable as well, as they will be shortly moved to MODIFIED while attaching.

    :param bug_obj: bug object
    :returns: True if viable
    """
    return bug_obj.status in ["MODIFIED", "ON_QA", "VERIFIED"]


def is_cve_tracker(bug_obj):
    """ Check if a bug is a CVE tracker.

    A CVE tracker bug must have `SecurityTracking` and `Security` keywords.

    :param bug_obj: bug object
    :returns: True if the bug is a CVE tracker.
    """
    return "SecurityTracking" in bug_obj.keywords and "Security" in bug_obj.keywords


def get_whiteboard_component(bug):
    """Get whiteboard component value of a bug.

    An OCP cve tracker has a whiteboard value "component:<component_name>"
    to indicate which component the bug belongs to.

    :param bug: bug object
    :returns: a string if a value is found, otherwise False
    """
    marker = r'component:\s*(\S+)'
    tmp = re.search(marker, bug.whiteboard)
    if tmp and len(tmp.groups()) == 1:
        component_name = tmp.groups()[0]
        return component_name
    return False


def get_valid_rpm_cves(bugs):
    """ Get valid rpm cve trackers with their component names

    An OCP rpm cve tracker has a whiteboard value "component:<component_name>"
    excluding suffixes (apb|container)

    :param bugs: list of bug objects
    :returns: A dict of bug object as key and component name as value
    """

    rpm_cves = {}
    for b in bugs:
        if is_cve_tracker(b):
            component_name = get_whiteboard_component(b)
            # filter out non-rpm suffixes
            if component_name and not re.search(r'-(apb|container)$', component_name):
                rpm_cves[b] = component_name
    return rpm_cves


def get_bzapi(bz_data, interactive_login=False):
    bzapi = bugzilla.Bugzilla(bz_data['bugzilla_config']['server'])
    if not bzapi.logged_in:
        print("elliott requires cached login credentials for {}".format(bz_data['server']))
        if interactive_login:
            bzapi.interactive_login()
        else:
            red_print("Login using 'bugzilla login --api-key'")
            exit(1)
    return bzapi


def _construct_query_url(bz_data, status, search_filter='default', flag=None):
    query_url = SearchURL(bz_data)

    filter_list = []
    if bz_data.get('filter'):
        filter_list = bz_data.get('filter')
    elif bz_data.get('filters'):
        filter_list = bz_data.get('filters').get(search_filter)

    for f in filter_list:
        query_url.addFilter('component', 'notequals', f)

    for s in status:
        query_url.addBugStatus(s)

    for r in bz_data.get('target_release', []):
        query_url.addTargetRelease(r)

    if flag:
        query_url.addFlagFilter(flag, "substring")

    return query_url


def _perform_query(bzapi, query_url, include_fields=None):
    BZ_PAGE_SIZE = 1000

    def iterate_query(query):
        results = bzapi.query(query)

        if len(results) == BZ_PAGE_SIZE:
            query['offset'] += BZ_PAGE_SIZE
            results += iterate_query(query)
        return results

    if include_fields is None:
        include_fields = ['id']

    query = bzapi.url_to_query(str(query_url))
    query["include_fields"] = include_fields
    query["limit"] = BZ_PAGE_SIZE
    query["offset"] = 0

    return iterate_query(query)


class SearchFilter(object):
    """
    This represents a query filter. Each filter consists of three components:

    * field selector string
    * operator
    * field value
    """

    pattern = "&f{0}={1}&o{0}={2}&v{0}={3}"

    def __init__(self, field, operator, value):
        self.field = field
        self.operator = operator
        self.value = value

    def tostring(self, number):
        return SearchFilter.pattern.format(
            number, self.field, self.operator, urllib.parse.quote(self.value)
        )


class SearchURL(object):

    url_format = "https://{}/buglist.cgi?"

    def __init__(self, bz_data):
        self.bz_host = bz_data['bugzilla_config'].get('server', '') if bz_data.get('jira_config') else ''
        self.classification = bz_data['bugzilla_config'].get('classification', '') if bz_data.get('jira_config') else ''
        self.product = bz_data['bugzilla_config'].get('product', '') if bz_data.get('jira_config') else ''
        self.bug_status = []
        self.filters = []
        self.filter_operator = ""
        self.versions = []
        self.target_releases = []
        self.keyword = ""
        self.keywords_type = ""

    def __str__(self):
        root_string = SearchURL.url_format.format(self.bz_host)

        url = root_string + self._status_string()

        url += "&classification={}".format(urllib.parse.quote(self.classification))
        url += "&product={}".format(urllib.parse.quote(self.product))
        url += self._keywords_string()
        url += self.filter_operator
        url += self._filter_string()
        url += self._target_releases_string()
        url += self._version_string()

        return url

    def _status_string(self):
        return "&".join(["bug_status={}".format(i) for i in self.bug_status])

    def _version_string(self):
        return "".join(["&version={}".format(i) for i in self.versions])

    def _filter_string(self):
        return "".join([f.tostring(i) for i, f in enumerate(self.filters)])

    def _target_releases_string(self):
        return "".join(["&target_release={}".format(tr) for tr in self.target_releases])

    def _keywords_string(self):
        return "&keywords={}&keywords_type={}".format(self.keyword, self.keywords_type)

    def addFilter(self, field, operator, value):
        self.filters.append(SearchFilter(field, operator, value))

    def addFlagFilter(self, flag, operator):
        self.filters.append(SearchFilter("flagtypes.name", operator, flag))

    def addTargetRelease(self, release_string):
        self.target_releases.append(release_string)

    def addVersion(self, version):
        self.versions.append(version)

    def addBugStatus(self, status):
        self.bug_status.append(status)

    def addKeyword(self, keyword, keyword_type="anywords"):
        self.keyword = keyword
        self.keywords_type = keyword_type


def to_timestamp(dt: xmlrpc.client.DateTime):
    """ Converts xmlrpc.client.DateTime to timestamp """
    return datetime.strptime(dt.value, "%Y%m%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def approximate_cutoff_timestamp(basis_event: int, koji_api: ClientSession, metas: Iterable[Metadata]) -> float:
    """ Calculate an approximate sweep cutoff timestamp from the given basis event
    """
    basis_timestamp = koji_api.getEvent(basis_event)["ts"]
    builds: List[Dict] = asyncio.get_event_loop().run_until_complete(asyncio.gather(*[exectools.to_thread(meta.get_latest_build, complete_before_event=basis_event, honor_is=False) for meta in metas]))
    nvrs = [b["nvr"] for b in builds]
    rebase_timestamp_strings = filter(None, [isolate_timestamp_in_release(nvr) for nvr in nvrs])  # the timestamp in the release field of NVR is the approximate rebase time
    # convert to UNIX timestamps
    rebase_timestamps = [datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp()
                         for ts in rebase_timestamp_strings]
    return min(basis_timestamp, max(rebase_timestamps, default=basis_timestamp))


def get_highest_security_impact(bugs):
    security_impacts = set(bug.severity.lower() for bug in bugs)
    if 'urgent' in security_impacts:
        return 'Critical'
    if 'high' in security_impacts:
        return 'Important'
    if 'medium' in security_impacts:
        return 'Moderate'
    return 'Low'


def is_first_fix_any(bugtracker, flaw_bug, current_target_release):
    """
    Check if a flaw bug is considered a first-fix for a GA target release
    for any of its trackers components. A return value of True means it should be
    attached to an advisory.
    """
    # all z stream bugs are considered first fix
    if current_target_release[-1] != '0':
        return True

    # get all tracker bugs for a flaw bug
    tracker_ids = flaw_bug.depends_on
    if not tracker_ids:
        # No trackers found
        # is a first fix
        # shouldn't happen ideally
        return True

    # filter tracker bugs by OCP product
    tracker_bugs = [b for b in bugtracker.get_bugs(tracker_ids) if b.product == constants.BUGZILLA_PRODUCT_OCP and b.is_tracker_bug()]
    if not tracker_bugs:
        # No OCP trackers found
        # is a first fix
        return True

    # make sure 3.X or 4.X bugs are being compared to each other
    def same_major_release(bug):
        return util.minor_version_tuple(current_target_release)[0] == util.minor_version_tuple(bug.target_release[0])[0]

    def already_fixed(bug):
        pending = bug.status == 'RELEASE_PENDING'
        closed = bug.status == 'CLOSED' and bug.resolution in ['ERRATA', 'CURRENTRELEASE', 'NEXTRELEASE']
        if pending or closed:
            return True
        return False

    # group trackers by components
    component_tracker_groups = dict()
    component_not_found = '[NotFound]'
    for b in tracker_bugs:
        # filter out trackers that don't belong ex. 3.X bugs for 4.X target release
        if not same_major_release(b):
            continue
        component = bzutil.get_whiteboard_component(b)
        if not component:
            component = component_not_found

        if component not in component_tracker_groups:
            component_tracker_groups[component] = set()
        component_tracker_groups[component].add(b)

    if component_not_found in component_tracker_groups:
        invalid_trackers = sorted([b.id for b in component_tracker_groups[component_not_found]])
        logger.warning(f"For flaw bug {flaw_bug.id} - these tracker bugs do not have a valid "
                       f"whiteboard component value: {invalid_trackers} "
                       "Cannot reliably determine if flaw bug is first "
                       "fix. Check tracker bugs manually")
        return False

    # if any tracker bug for the flaw bug
    # has been fixed for the same major release version
    # then it is not a first fix
    def is_first_fix_group(trackers):
        for b in trackers:
            if already_fixed(b):
                return False
        return True

    # if for any component is_first_fix_group is true
    # then flaw bug is first fix
    for component, trackers in component_tracker_groups.items():
        if is_first_fix_group(trackers):
            logger.info(f'{flaw_bug.id} considered first-fix for component: {component} for trackers: '
                        f'{[t.id for t in trackers]}')
            return True

    return False
