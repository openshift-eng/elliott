"""
Utility functions and object abstractions for general interactions
with BugTrackers
"""
import asyncio
import itertools
import re
import urllib.parse
import xmlrpc.client
import bugzilla
import click
import os
import requests
from requests_gssapi import HTTPSPNEGOAuth
from datetime import datetime, timezone
from time import sleep
from typing import Dict, Iterable, List, Optional
from jira import JIRA, Issue
from errata_tool import Erratum
from errata_tool.jira_issue import JiraIssue as ErrataJira
from errata_tool.bug import Bug as ErrataBug
from bugzilla.bug import Bug
from koji import ClientSession

from elliottlib import constants, exceptions, exectools, logutil, errata, util
from elliottlib.cli import cli_opts
from elliottlib.errata_async import AsyncErrataAPI
from elliottlib.metadata import Metadata
from elliottlib.util import isolate_timestamp_in_release, chunk

logger = logutil.getLogger(__name__)


# This is easier to patch in unit tests
def datetime_now():
    return datetime.now(timezone.utc)


def get_jira_bz_bug_ids(bug_ids):
    ids = cli_opts.id_convert_str(bug_ids)
    jira_ids = {b for b in ids if JIRABug.looks_like_a_jira_bug(b)}
    bz_ids = {int(b) for b in ids if not JIRABug.looks_like_a_jira_bug(b)}
    return jira_ids, bz_ids


class Bug:
    def __init__(self, bug_obj):
        self.bug = bug_obj

    @property
    def id(self):
        raise NotImplementedError

    def created_days_ago(self):
        created_date = self.creation_time_parsed()
        return (datetime_now() - created_date).days

    def creation_time_parsed(self):
        raise NotImplementedError

    @property
    def corresponding_flaw_bug_ids(self):
        raise NotImplementedError

    @property
    def whiteboard_component(self):
        raise NotImplementedError

    def all_advisory_ids(self):
        raise NotImplementedError

    def is_tracker_bug(self):
        raise NotImplementedError

    def is_invalid_tracker_bug(self):
        raise NotImplementedError

    def is_flaw_bug(self):
        return self.product == "Security Response" and self.component == "vulnerability"

    def is_ocp_bug(self):
        raise NotImplementedError

    @property
    def component(self):
        raise NotImplementedError

    @property
    def product(self):
        raise NotImplementedError

    @staticmethod
    def get_target_release(bugs: List[Bug]) -> str:
        """
        Pass in a list of bugs and get their target release version back.
        Raises exception if they have different target release versions set.

        :param bugs: List[Bug] instance
        """
        invalid_bugs = []
        target_releases = dict()

        if not bugs:
            raise ValueError("bugs should be a non empty list")

        for bug in bugs:
            # make sure it's a list with a valid str value
            valid_target_rel = isinstance(bug.target_release, list) and len(bug.target_release) > 0 and \
                re.match(r'(\d+.\d+.[0|z])', bug.target_release[0])
            if not valid_target_rel:
                invalid_bugs.append(bug)
            else:
                tr = bug.target_release[0]
                if tr not in target_releases:
                    target_releases[tr] = set()
                target_releases[tr].add(bug.id)

        if invalid_bugs:
            err = 'target_release should be a list with a string matching regex (digit+.digit+.[0|z])'
            for b in invalid_bugs:
                err += f'\n bug: {b.id}, target_release: {b.target_release} '
            raise ValueError(err)

        if len(target_releases) != 1:
            err = f'Found different target_release values for bugs: {target_releases}. ' \
                'There should be only 1 target release for all bugs. Fix the offending bug(s) and try again.'
            raise ValueError(err)

        return list(target_releases.keys())[0]


class BugzillaBug(Bug):
    def __getattr__(self, attr):
        if attr in self.__dict__:
            return getattr(self, attr)
        return getattr(self.bug, attr)

    def __init__(self, bug_obj):
        super().__init__(bug_obj)

    @property
    def id(self):
        return self.bug.id

    @property
    def product(self):
        return self.bug.product

    @property
    def component(self):
        return self.bug.component

    @property
    def target_release(self):
        return self.bug.target_release

    @property
    def sub_component(self):
        if hasattr(self.bug, 'sub_component'):
            return self.bug.sub_component
        else:
            return None

    @property
    def corresponding_flaw_bug_ids(self):
        return self.bug.blocks

    @property
    def whiteboard_component(self):
        """Get whiteboard component value of a bug.

        An OCP cve tracker has a whiteboard value "component:<component_name>"
        to indicate which component the bug belongs to.

        :returns: a string if a value is found, otherwise None
        """
        marker = r'component:\s*(\S+)'
        tmp = re.search(marker, self.bug.whiteboard)
        if tmp and len(tmp.groups()) == 1:
            component_name = tmp.groups()[0]
            return component_name
        return None

    def is_tracker_bug(self):
        has_keywords = set(constants.TRACKER_BUG_KEYWORDS).issubset(set(self.keywords))
        has_whiteboard_component = bool(self.whiteboard_component)
        return has_keywords and has_whiteboard_component

    def is_invalid_tracker_bug(self):
        if self.is_tracker_bug():
            return False
        if 'WeaknessTracking' in self.keywords:
            # See e.g. https://bugzilla.redhat.com/show_bug.cgi?id=2092289. This bug is not a CVE tracker
            return False
        has_cve_in_summary = bool(re.search(r'CVE-\d+-\d+', self.summary))
        has_keywords = set(constants.TRACKER_BUG_KEYWORDS).issubset(set(self.keywords))
        return has_keywords or has_cve_in_summary

    def all_advisory_ids(self):
        return ErrataBug(self.id).all_advisory_ids

    def is_ocp_bug(self):
        return self.product == constants.BUGZILLA_PRODUCT_OCP

    def creation_time_parsed(self):
        return datetime.strptime(str(self.bug.creation_time), '%Y%m%dT%H:%M:%S').replace(tzinfo=timezone.utc)


class JIRABug(Bug):
    def __init__(self, bug_obj: Issue):
        super().__init__(bug_obj)

    @property
    def id(self):
        return self.bug.key

    @property
    def weburl(self):
        return self.bug.permalink()

    @property
    def component(self):
        component0 = self.bug.fields.components[0].name
        return component0.split('/')[0].strip()

    @property
    def status(self):
        return self.bug.fields.status.name

    def is_tracker_bug(self):
        has_keywords = set(constants.TRACKER_BUG_KEYWORDS).issubset(set(self.keywords))
        has_whiteboard_component = bool(self.whiteboard_component)
        has_linked_flaw = bool(self.corresponding_flaw_bug_ids)
        return has_keywords and has_whiteboard_component and has_linked_flaw

    def is_invalid_tracker_bug(self):
        if self.is_tracker_bug():
            return False
        if 'WeaknessTracking' in self.keywords:
            # See e.g. https://issues.redhat.com/browse/OCPBUGS-5804. This is not to be regarded a tracking bug.
            return False
        if 'art:cloned-kernel-bug' in self.keywords:
            # Bugs for advance-shipped kernel builds should not be regarded as a tracker. They might look like one,
            # but they are not invalid.
            # Context in this thread: https://redhat-internal.slack.com/archives/C04SCM5AYE4/p1685524912511489?thread_ts=1685489306.568039&cid=C04SCM5AYE4
            # This is likely not the end state, but at least for the time being.
            return False
        has_cve_in_summary = bool(re.search(r'CVE-\d+-\d+', self.summary))
        has_keywords = set(constants.TRACKER_BUG_KEYWORDS).issubset(set(self.keywords))
        has_linked_flaw = bool(self.corresponding_flaw_bug_ids)
        return has_keywords or has_cve_in_summary or has_linked_flaw

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
    def corresponding_flaw_bug_ids(self):
        flaw_bug_ids = []
        for label in self.bug.fields.labels:
            if str(label).startswith("flaw"):
                match = re.match(r'flaw:bz#(\d+)', label)
                if match:
                    flaw_bug_ids.append(match[1])
        return [int(f) for f in flaw_bug_ids]

    @property
    def version(self):
        return [x.name for x in self.bug.fields.versions]

    @property
    def blocked_by_bz(self):
        url = getattr(self.bug.fields, JIRABugTracker.FIELD_BLOCKED_BY_BZ)
        if not url:
            return None
        bug_id = re.search(r"id=(\d+)", url)
        if not bug_id:
            return None
        return int(bug_id.groups()[0])

    @property
    def target_release(self):
        tr_field = getattr(self.bug.fields, JIRABugTracker.FIELD_TARGET_VERSION)
        if not tr_field:
            raise ValueError(f'bug {self.id} does not have `Target Version` field set')
        return [x.name for x in tr_field]

    @property
    def sub_component(self):
        component0 = self.bug.fields.components[0].name
        split = component0.split('/')
        if len(split) < 2:
            return None
        return split[1].strip()

    @property
    def resolution(self):
        return str(self.bug.fields.resolution)

    @property
    def depends_on(self):
        depends_on = self._get_depends()
        depends_on_bz = self.blocked_by_bz
        if depends_on_bz:
            depends_on.append(depends_on_bz)
        return depends_on

    @property
    def release_blocker(self):
        return self._get_release_blocker()

    @property
    def severity(self):
        return self._get_severity()

    @property
    def product(self):
        return self.bug.fields.project.key

    @property
    def alias(self):
        # TODO: See usage. this can be correct or incorrect based in usage.
        return self.bug.fields.labels

    @property
    def whiteboard_component(self):
        """Get whiteboard component value of a bug.

        An OCP cve tracker has a whiteboard value "component:<component_name>"
        to indicate which component the bug belongs to.

        :returns: a string if a value is found, otherwise None
        """
        marker = r'component:\s*(\S+)'
        for label in self.bug.fields.labels:
            tmp = re.search(marker, label)
            if tmp and len(tmp.groups()) == 1:
                component_name = tmp.groups()[0]
                return component_name
        return None

    def _get_release_blocker(self):
        # release blocker can be ['None','Approved'=='+','Proposed'=='?','Rejected'=='-']
        field = getattr(self.bug.fields, JIRABugTracker.FIELD_RELEASE_BLOCKER)
        if field:
            return field.value == 'Approved'
        return False

    def _get_blocked_reason(self):
        field = getattr(self.bug.fields, JIRABugTracker.FIELD_BLOCKED_REASON)
        if field:
            return field.value
        return None

    def _get_severity(self):
        field = getattr(self.bug.fields, JIRABugTracker.FIELD_SEVERITY)
        if field:
            if "Urgent" in field.value:
                return "Urgent"
            if "High" in field.value:
                return "High"
            if "Medium" in field.value:
                return "Medium"
            if "Low" in field.value:
                return "Low"
        return None

    def all_advisory_ids(self):
        return ErrataJira(self.id).all_advisory_ids

    def creation_time_parsed(self):
        return datetime.strptime(str(self.bug.fields.created), '%Y-%m-%dT%H:%M:%S.%f%z')

    def is_ocp_bug(self):
        return self.bug.fields.project.key == "OCPBUGS" and not self.is_placeholder_bug()

    def is_placeholder_bug(self):
        return ('Placeholder' in self.summary) and (self.component == 'Release') and ('Automation' in self.keywords)

    def _get_blocks(self):
        # link "blocks"
        blocks = []
        for link in self.bug.fields.issuelinks:
            if link.type.name == "Blocks" and hasattr(link, "outwardIssue"):
                blocks.append(link.outwardIssue.key)
        return blocks

    def _get_depends(self):
        # link "is blocked by"
        depends = []
        for link in self.bug.fields.issuelinks:
            if link.type.name == "Blocks" and hasattr(link, "inwardIssue"):
                depends.append(link.inwardIssue.key)
        return depends

    @staticmethod
    def looks_like_a_jira_bug(bug_id):
        pattern = re.compile(r'\w+-\d+')
        return pattern.match(str(bug_id))


class BugTracker:
    def __init__(self, config: dict, tracker_type: str):
        self.config = config
        self._server = self.config.get('server', '')
        self.type = tracker_type

    def component_filter(self, filter_name='default') -> List:
        return self.config.get('filters', {}).get(filter_name)

    def target_release(self) -> List:
        return self.config.get('target_release')

    def search(self, status, search_filter, verbose=False, **kwargs):
        raise NotImplementedError

    def blocker_search(self, status, search_filter, verbose=False, **kwargs):
        raise NotImplementedError

    def cve_tracker_search(self, status, search_filter, verbose=False, **kwargs):
        raise NotImplementedError

    def get_bug(self, bugid, **kwargs):
        raise NotImplementedError

    def get_bugs(self, bugids: List, permissive=False, **kwargs):
        raise NotImplementedError

    def get_bugs_map(self, bugids: List, permissive: bool = False, **kwargs) -> Dict:
        id_bug_map = {}
        if not bugids:
            return id_bug_map
        bugs = self.get_bugs(bugids, permissive=permissive, **kwargs)
        for bug in bugs:
            id_bug_map[bug.id] = bug
        return id_bug_map

    def remove_bugs(self, advisory_obj, bugids: List, noop=False):
        raise NotImplementedError

    def attach_bugs(self, bugids: List, advisory_id: int = 0, advisory_obj: Erratum = None, noop=False,
                    verbose=False):
        raise NotImplementedError

    def add_comment(self, bugid, comment: str, private: bool, noop=False):
        raise NotImplementedError

    def create_bug(self, bug_title, bug_description, target_status, keywords: List, noop=False):
        raise NotImplementedError

    def _update_bug_status(self, bugid, target_status):
        raise NotImplementedError

    @staticmethod
    def advisory_bug_ids(advisory_obj):
        raise NotImplementedError

    @staticmethod
    def id_convert(id_string):
        raise NotImplementedError

    def create_placeholder(self, kind, noop=False):
        title = f"Placeholder bug for OCP {self.config.get('target_release')[0]} {kind} release"
        return self.create_bug(title, title, "VERIFIED", ["Automation"], noop)

    def create_textonly(self, bug_title, bug_description, noop=False):
        return self.create_bug(bug_title, bug_description, "VERIFIED", [], noop)

    def update_bug_status(self, bug: Bug, target_status: str,
                          comment: Optional[str] = None, log_comment: bool = True, noop=False):
        """ Update bug status and optionally leave a comment
        :return: True if but status has been actually updated
        """
        current_status = bug.status
        action = f'changed {bug.id} from {current_status} to {target_status}'
        if current_status == target_status:
            logger.info(f'{bug.id} is already on {target_status}')
            return False
        elif noop:
            logger.info(f"Would have {action}")
        else:
            self._update_bug_status(bug.id, target_status)
            logger.info(action)

        comment_lines = []
        if log_comment:
            comment_lines.append(f'Elliott changed bug status from {current_status} to {target_status}.')
        if comment:
            comment_lines.append(comment)
        if comment_lines:
            self.add_comment(bug.id, '\n'.join(comment_lines), private=True, noop=noop)
        return True

    @staticmethod
    def get_corresponding_flaw_bugs(tracker_bugs: List[Bug], flaw_bug_tracker, brew_api,
                                    strict: bool = True, verbose: bool = False) -> (Dict, Dict):
        """Get corresponding flaw bug objects for given list of tracker bug objects.
        flaw_bug_tracker object to fetch flaw bugs from

        :return: (tracker_flaws, flaw_id_bugs): tracker_flaws is a dict with tracker bug id as key and list of flaw
        bug id as value, flaw_id_bugs is a dict with flaw bug id as key and flaw bug object as value
        """
        bug_tracker = flaw_bug_tracker
        flaw_bugs = bug_tracker.get_flaw_bugs(
            list(set(sum([t.corresponding_flaw_bug_ids for t in tracker_bugs], []))),
            verbose=verbose
        )
        flaw_tracker_map = {bug.id: {'bug': bug, 'trackers': []}
                            for bug in flaw_bugs}

        # Validate that each tracker has a corresponding flaw bug
        # and a whiteboard component
        trackers_with_no_flaws = set()
        trackers_with_invalid_components = set()
        for t in tracker_bugs:
            component = t.whiteboard_component
            if not component:
                trackers_with_invalid_components.add(t.id)
                continue

            # is this component a valid package name in brew?
            if not brew_api.getPackageID(component):
                logger.info(f'package `{component}` not found in brew')
                trackers_with_invalid_components.add(t.id)
                continue

            flaw_bug_ids = [i for i in t.corresponding_flaw_bug_ids if i in flaw_tracker_map]
            if not len(flaw_bug_ids):
                trackers_with_no_flaws.add(t.id)
                continue

            for f_id in flaw_bug_ids:
                flaw_tracker_map[f_id]['trackers'].append(t)

        error_msg = ''
        if trackers_with_no_flaws:
            error_msg += 'Cannot find any corresponding flaw bugs for these trackers: ' \
                         f'{sorted(trackers_with_no_flaws)}. '

        if trackers_with_invalid_components:
            error_msg += "These trackers do not have a valid whiteboard component value:" \
                         f" {sorted(trackers_with_invalid_components)}."

        if error_msg:
            if strict:
                raise exceptions.ElliottFatalError(error_msg)
            else:
                logger.warning(error_msg)

        invalid_trackers = trackers_with_no_flaws | trackers_with_invalid_components
        tracker_flaws = {
            t.id: [b for b in t.corresponding_flaw_bug_ids if b in flaw_tracker_map]
            for t in tracker_bugs if t.id not in invalid_trackers
        }
        return tracker_flaws, flaw_tracker_map

    def get_tracker_bugs(self, bug_ids: List, strict: bool = False, verbose: bool = False):
        raise NotImplementedError

    def get_flaw_bugs(self, bug_ids: List, strict: bool = True, verbose: bool = False):
        raise NotImplementedError


class JIRABugTracker(BugTracker):
    JIRA_BUG_BATCH_SIZE = 50

    # Prefer to query by user visible Field Name. Context: https://issues.redhat.com/browse/ART-7053
    FIELD_BLOCKED_BY_BZ = 'customfield_12322152'  # "Blocked by Bugzilla Bug"
    FIELD_TARGET_VERSION = 'customfield_12323140'  # "Target Version"
    FIELD_RELEASE_BLOCKER = 'customfield_12319743'  # "Release Blocker"
    FIELD_BLOCKED_REASON = 'customfield_12316544'  # "Blocked Reason"
    FIELD_SEVERITY = 'customfield_12316142'  # "Severity"

    @staticmethod
    def get_config(runtime) -> Dict:
        major, minor = runtime.get_major_minor()
        if major == 4 and minor < 6:
            raise ValueError("ocp-build-data/bug.yml is not expected to be available for 4.X versions < 4.6")
        bug_config = runtime.gitdata.load_data(key='bug').data
        # construct config so that all jira_config keys become toplevel keys
        jira_config = bug_config.pop('jira_config')
        for key in jira_config:
            if key in bug_config:
                raise ValueError(f"unexpected: top level config contains same key ({key}) as jira_config")
            bug_config[key] = jira_config[key]
        return bug_config

    def login(self, token_auth=None) -> JIRA:
        if not token_auth:
            token_auth = os.environ.get("JIRA_TOKEN")
            if not token_auth:
                raise ValueError(f"elliott requires login credentials for {self._server}. Set a JIRA_TOKEN env var ")
        client = JIRA(self._server, token_auth=token_auth)
        return client

    def __init__(self, config):
        super().__init__(config, 'jira')
        self._project = self.config.get('project', '')
        self._client: JIRA = self.login()

    @property
    def product(self):
        return self._project

    def looks_like_a_jira_project_bug(self, bug_id) -> bool:
        pattern = re.compile(fr'{self._project}-\d+')
        return bool(pattern.match(str(bug_id)))

    def get_bug(self, bugid: str, **kwargs) -> JIRABug:
        return JIRABug(self._client.issue(bugid, **kwargs))

    def get_bugs(self, bugids: List[str], permissive=False, verbose=False, **kwargs) -> List[JIRABug]:
        invalid_bugs = [b for b in bugids if not self.looks_like_a_jira_project_bug(b)]
        if invalid_bugs:
            logger.warn(f"Cannot fetch bugs from a different project (current project: {self._project}):"
                        f" {invalid_bugs}")
        bugids = [b for b in bugids if self.looks_like_a_jira_project_bug(b)]
        if not bugids:
            return []

        # Split the request in chunks, in order not to fall into
        # jira.exceptions.JIRAError for request header size too large
        bugs = []
        for chunk_of_bugs in chunk(list(bugids), self.JIRA_BUG_BATCH_SIZE):
            query = self._query(bugids=chunk_of_bugs, with_target_release=False)
            if verbose:
                logger.info(query)
            bugs.extend(self._search(query))

        if len(bugs) < len(bugids):
            bugids_not_found = set(bugids) - {b.id for b in bugs}
            msg = f"Some bugs could not be fetched ({len(bugids) - len(bugs)}): {bugids_not_found}"
            if not permissive:
                raise ValueError(msg)
            else:
                logger.warn(msg)
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
            'components': [{'name': 'Release'}],
            'versions': [{'name': self.config.get('version')[0]}],  # Affects Version/s
            self.FIELD_TARGET_VERSION: [{'name': self.config.get('target_release')[0]}],  # Target Version
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
            logger.info(f"Would have added a private={private} comment to {bugid}")
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
               search_filter: str = None,
               custom_query: str = None) -> str:

        if target_release and with_target_release:
            raise ValueError("cannot use target_release and with_target_release together")
        if not target_release and with_target_release:
            target_release = self.target_release()

        exclude_components = []
        if search_filter:
            exclude_components = self.component_filter(search_filter)

        query = f"project={self._project}"
        if bugids:
            query += f" and issue in ({','.join(bugids)})"
        if status:
            val = ','.join(f'"{s}"' for s in status)
            query += f" and status in ({val})"
        if target_release:
            tr = ','.join(target_release)
            query += f' and "Target Version" in ({tr})'
        if include_labels:
            query += f" and labels in ({','.join(include_labels)})"
        if exclude_labels:
            query += f" and labels not in ({','.join(exclude_labels)})"
        if exclude_components:
            # https://docs.adaptavist.com/sr4js/6.55.1/features/jql-functions/included-jql-functions/calculations
            val = ','.join(f'componentMatch("{c}*")' for c in exclude_components)
            query += f" and component not in ({val})"
        if custom_query:
            query += custom_query
        return query

    def _search(self, query, verbose=False) -> List[JIRABug]:
        if verbose:
            logger.info(query)
        results = self._client.search_issues(query, maxResults=0)
        return [JIRABug(j) for j in results]

    def blocker_search(self, status, search_filter='default', verbose=False, **kwargs):
        query = self._query(
            status=status,
            with_target_release=True,
            search_filter=search_filter,
            custom_query='and "Release Blocker" = "Approved"'
        )
        return self._search(query, verbose=verbose, **kwargs)

    def search(self, status, search_filter='default', verbose=False):
        query = self._query(
            status=status,
            search_filter=search_filter
        )
        return self._search(query, verbose=verbose)

    def cve_tracker_search(self, status, search_filter='default', verbose=False):
        query = self._query(
            status=status,
            search_filter=search_filter,
            include_labels=["SecurityTracking"],
        )
        return self._search(query, verbose=verbose)

    def remove_bugs(self, advisory_obj, bugids: List, noop=False):
        if noop:
            print(f"Would've removed bugs: {bugids}")
            return
        advisory_obj.removeJIRAIssues(bugids)
        advisory_obj.commit()

    def attach_bugs(self, bugids: List, advisory_id: int = 0, advisory_obj: Erratum = None, noop=False,
                    verbose=False):
        if not advisory_obj:
            advisory_obj = Erratum(errata_id=advisory_id)
        return errata.add_jira_bugs_with_retry(advisory_obj, bugids, noop=noop)

    def filter_bugs_by_cutoff_event(self, bugs: Iterable, desired_statuses: Iterable[str],
                                    sweep_cutoff_timestamp: float, verbose=False) -> List:
        dt = datetime.utcfromtimestamp(sweep_cutoff_timestamp).strftime("%Y/%m/%d %H:%M")
        val = ','.join(f'"{s}"' for s in desired_statuses)
        query = f"issue in ({','.join([b.id for b in bugs])}) " \
                f"and status was in ({val}) " \
                f'before("{dt}")'
        return self._search(query, verbose=verbose)

    async def filter_attached_bugs(self, bugs: Iterable):
        bugs = list(bugs)
        api = AsyncErrataAPI()
        results = await asyncio.gather(*[api.get_advisories_for_jira(bug.id, ignore_not_found=True) for bug in bugs])
        attached_bugs = [bug for bug, advisories in zip(bugs, results) if advisories]
        await api.close()
        return attached_bugs

    @staticmethod
    def advisory_bug_ids(advisory_obj):
        return advisory_obj.jira_issues

    @staticmethod
    def id_convert(id_string):
        return cli_opts.id_convert_str(id_string)

    def get_tracker_bugs(self, bug_ids: List, strict: bool = False, verbose: bool = False):
        return [b for b in self.get_bugs(bug_ids, permissive=not strict, verbose=verbose) if b.is_tracker_bug()]

    def get_flaw_bugs(self, bug_ids: List, strict: bool = True, verbose: bool = False):
        return [b for b in self.get_bugs(bug_ids, permissive=not strict, verbose=verbose) if b.is_flaw_bug()]


class BugzillaBugTracker(BugTracker):
    @staticmethod
    def get_config(runtime):
        major, minor = runtime.get_major_minor()
        if major == 4 and minor < 5:
            raise ValueError("ocp-build-data/bug.yml is not expected to be available for 4.X versions < 4.5")
        bug_config = runtime.gitdata.load_data(key='bug').data
        # construct config so that all bugzilla_config keys become toplevel keys
        bz_config = bug_config.pop('bugzilla_config')
        for key in bz_config:
            if key in bug_config:
                raise ValueError(f"unexpected: top level config contains same key ({key}) as bugzilla_config")
            bug_config[key] = bz_config[key]
        return bug_config

    def login(self):
        client = bugzilla.Bugzilla(self._server)
        if not client.logged_in:
            raise ValueError(f"elliott requires cached login credentials for {self._server}. Login using 'bugzilla "
                             "login --api-key")
        return client

    def __init__(self, config):
        super().__init__(config, 'bugzilla')
        self._client = self.login()
        self.product = self.config.get('product', '')

    def get_bug(self, bugid, **kwargs):
        return BugzillaBug(self._client.getbug(bugid, **kwargs))

    def get_bugs(self, bugids, permissive=False, **kwargs):
        if not bugids:
            return []
        if 'verbose' in kwargs:
            if kwargs.pop('verbose'):
                logger.info(f'get_bugs called with bugids: {bugids}, permissive: {permissive} and kwargs: {kwargs}')
        bugs = [BugzillaBug(b) for b in self._client.getbugs(bugids, permissive=permissive, **kwargs)]
        if len(bugs) < len(bugids):
            bugids_not_found = set(bugids) - {b.id for b in bugs}
            msg = f"Some bugs could not be fetched ({len(bugids)-len(bugs)}): {bugids_not_found}"
            if permissive:
                print(msg)
        return bugs

    def client(self):
        return self._client

    def blocker_search(self, status, search_filter='default', verbose=False):
        query = _construct_query_url(self.config, status, search_filter, flag='blocker+')
        return self._search(query, verbose)

    def search(self, status, search_filter='default', verbose=False):
        query = _construct_query_url(self.config, status, search_filter)
        return self._search(query, verbose)

    def cve_tracker_search(self, status, search_filter='default', verbose=False):
        query = _construct_query_url(self.config, status, search_filter)
        query.addKeyword('SecurityTracking')
        return self._search(query, verbose)

    def _search(self, query, verbose=False):
        if verbose:
            logger.info(query)
        return [BugzillaBug(b) for b in _perform_query(self._client, query)]

    def remove_bugs(self, advisory_obj, bugids: List, noop=False):
        if noop:
            print(f"Would've removed bugs: {bugids}")
            return
        advisory_id = advisory_obj.errata_id
        return errata.remove_multi_bugs(advisory_id, bugids)

    def attach_bugs(self, bugids: List, advisory_id: int = 0, advisory_obj: Erratum = None, noop=False, verbose=False):
        if not advisory_obj:
            advisory_obj = Erratum(errata_id=advisory_id)
        return errata.add_bugzilla_bugs_with_retry(advisory_obj, bugids, noop=noop)

    def create_bug(self, title, description, target_status, keywords: List, noop=False) -> BugzillaBug:
        create_info = self._client.build_createbug(
            product=self.product,
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
        if target_status == 'CLOSED':
            return self._client.update_bugs([bugid], self._client.build_update(status=target_status,
                                                                               resolution='WONTFIX'))
        return self._client.update_bugs([bugid], self._client.build_update(status=target_status))

    def add_comment(self, bugid, comment: str, private, noop=False):
        self._client.update_bugs([bugid], self._client.build_update(comment=comment, comment_private=private))

    def filter_bugs_by_cutoff_event(self, bugs: Iterable, desired_statuses: Iterable[str],
                                    sweep_cutoff_timestamp: float, verbose=False) -> List:
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

    async def filter_attached_bugs(self, bugs: Iterable):
        bugs = list(bugs)
        api = AsyncErrataAPI()
        results = await asyncio.gather(*[api.get_advisories_for_bug(bug.id) for bug in bugs])
        attached_bugs = [bug for bug, advisories in zip(bugs, results) if advisories]
        await api.close()
        return attached_bugs

    @staticmethod
    def advisory_bug_ids(advisory_obj):
        return advisory_obj.errata_bugs

    @staticmethod
    def id_convert(id_string):
        return cli_opts.id_convert(id_string)

    def get_tracker_bugs(self, bug_ids: List, strict: bool = False, verbose: bool = False):
        fields = ["target_release", "blocks", 'whiteboard', 'keywords']
        return [b for b in self.get_bugs(bug_ids, permissive=not strict, include_fields=fields, verbose=verbose) if
                b.is_tracker_bug()]

    def get_flaw_bugs(self, bug_ids: List, strict: bool = True, verbose: bool = False):
        fields = ["product", "component", "depends_on", "alias", "severity", "summary"]
        return [b for b in self.get_bugs(bug_ids, permissive=not strict, include_fields=fields, verbose=verbose) if
                b.is_flaw_bug()]


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


def is_viable_bug(bug_obj):
    """ Check if a bug is viable to attach to an advisory.

    A viable bug must be in one of MODIFIED and VERIFIED status. We accept ON_QA
    bugs as viable as well, as they will be shortly moved to MODIFIED while attaching.

    :param bug_obj: bug object
    :returns: True if viable
    """
    return bug_obj.status in ["MODIFIED", "ON_QA", "VERIFIED"]


def _construct_query_url(config, status, search_filter='default', flag=None):
    query_url = SearchURL(config)
    query_url.fields = ['id', 'status', 'summary', 'creation_time', 'cf_pm_score', 'component',
                        # the api expects "sub_components" for the field "sub_component"
                        # https://github.com/python-bugzilla/python-bugzilla/blob/main/bugzilla/base.py#L321
                        'sub_components',
                        'external_bugs', 'whiteboard', 'keywords', 'target_release', 'depends_on']

    filter_list = []
    if config.get('filter'):
        filter_list = config.get('filter')
    elif config.get('filters'):
        filter_list = config.get('filters').get(search_filter)

    for f in filter_list:
        query_url.addFilter('component', 'notequals', f)

    # CVEs for this image get filed into component that we need to look at. As this is about a
    # deprecated system and fixing config is not an option, hard code this exclusion:
    query_url.addFilter('status_whiteboard', 'notsubstring', 'component:assisted-installer-container')

    for s in status:
        query_url.addBugStatus(s)

    for r in config.get('target_release', []):
        query_url.addTargetRelease(r)

    if flag:
        query_url.addFlagFilter(flag, "substring")

    return query_url


def _perform_query(bzapi, query_url):
    BZ_PAGE_SIZE = 1000

    def iterate_query(query):
        results = bzapi.query(query)

        if len(results) == BZ_PAGE_SIZE:
            query['offset'] += BZ_PAGE_SIZE
            results += iterate_query(query)
        return results

    include_fields = query_url.fields
    if not include_fields:
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

    def __init__(self, config):
        self.bz_host = config.get('server', '')
        self.classification = config.get('classification', '')
        self.product = config.get('product', '')
        self.bug_status = []
        self.filters = []
        self.filter_operator = ""
        self.versions = []
        self.target_releases = []
        self.keyword = ""
        self.keywords_type = ""
        self.fields = []

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


async def approximate_cutoff_timestamp(basis_event: int, koji_api: ClientSession, metas: Iterable[Metadata]) -> float:
    """ Calculate an approximate sweep cutoff timestamp from the given basis event
    """
    basis_timestamp = koji_api.getEvent(basis_event)["ts"]
    builds: List[Dict] = await asyncio.gather(*[exectools.to_thread(meta.get_latest_build, default=None, complete_before_event=basis_event, honor_is=False) for meta in metas])
    nvrs = [b["nvr"] for b in builds if b]
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


def sort_cve_bugs(bugs):
    def cve_sort_key(bug):
        impact = constants.security_impact_map[get_highest_security_impact([bug])]
        year, num = bug.alias[0].split("-")[1:]
        return impact, -int(year), -int(num)
    return sorted(bugs, key=cve_sort_key, reverse=True)


def is_first_fix_any(flaw_bug: BugzillaBug, tracker_bugs: Iterable[Bug], current_target_release: str):
    # all z stream bugs are considered first fix
    if current_target_release[-1] != '0':
        return True

    if not tracker_bugs:
        # This shouldn't happen
        raise ValueError(f'flaw bug {flaw_bug.id} does not seem to have trackers')

    if not (hasattr(flaw_bug, 'alias') and flaw_bug.alias):
        raise ValueError(f'flaw bug {flaw_bug.id} does not have an alias')

    alias = flaw_bug.alias[0]
    cve_url = f"https://access.redhat.com/hydra/rest/securitydata/cve/{alias}.json"
    response = requests.get(cve_url)
    response.raise_for_status()
    data = response.json()

    major, minor = util.minor_version_tuple(current_target_release)
    ocp_product_name = f"Red Hat OpenShift Container Platform {major}"
    components_not_yet_fixed = []
    pyxis_base_url = "https://pyxis.engineering.redhat.com/v1/repositories/registry/registry.access.redhat.com" \
                     "/repository/{pkg_name}/images?page_size=1&include=data.brew"

    if 'package_state' not in data:
        logger.info(f'{flaw_bug.id} ({alias}) not considered a first-fix because no unfixed components were found')
        return False

    for package_info in data['package_state']:
        # previously we were also checking `package_info['fix_state'] in ['Affected', 'Under investigation']`
        # but we don't need to verify that since according to @sfowler if a package has a tracker for a cve
        # and was found in the list of unfixed components then it is assumed to be `Affected`
        if ocp_product_name in package_info['product_name']:
            pkg_name = package_info['package_name']
            # for images `package_name` field is usually the container delivery repo
            # otherwise we assume it's the exact brew package name
            if '/' in pkg_name:
                pyxis_url = pyxis_base_url.format(pkg_name=pkg_name)
                response = requests.get(pyxis_url, auth=HTTPSPNEGOAuth())
                if response.status_code == requests.codes.ok:
                    data = response.json()['data']
                    if data:
                        pkg_name = data[0]['brew']['package']
                    else:
                        logger.warn(f'could not find brew package info at {pyxis_url}')
                else:
                    logger.warn(f'got status={response.status_code} for {pyxis_url}')
            components_not_yet_fixed.append(pkg_name)

    # get tracker components
    first_fix_components = []
    for t in tracker_bugs:
        component = t.whiteboard_component
        if component in components_not_yet_fixed:
            first_fix_components.append((component, t.id))

    if first_fix_components:
        logger.info(f'{flaw_bug.id} ({alias}) considered first-fix for these (component, tracker):'
                    f' {first_fix_components}')
        return True

    logger.info(f'{flaw_bug.id} ({alias}) not considered a first-fix because newly fixed trackers '
                f'components {[t.whiteboard_component for t in tracker_bugs]}, were not found in unfixed components '
                f'{components_not_yet_fixed}')
    return False
