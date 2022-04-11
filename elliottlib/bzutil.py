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
from urllib.parse import urlparse
from jira import JIRA, Issue

import bugzilla
import click
import os
from bugzilla.bug import Bug
from koji import ClientSession

from elliottlib import constants, exceptions, exectools, logutil
from elliottlib.metadata import Metadata
from elliottlib.util import isolate_timestamp_in_release, red_print

logger = logutil.getLogger(__name__)


class Bug:
    def __init__(self, bug_obj):
        self.bug = bug_obj

    @staticmethod
    def get_target_release(bugs) -> str:
        """
        Pass in a list of bugs and get their target release version back.
        Raises exception if they have different target release versions set.

        :param bugs: List[Bug] instance
        """
        invalid_bugs = []
        target_releases = set()

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
        self.creation_time_parsed = datetime.strptime(str(self.bug.creation_time), '%Y%m%dT%H:%M:%S').replace(tzinfo=timezone.utc)


class JIRABug(Bug):
    def _url(self):
        o = urlparse(self.bug.self)
        return o._replace(path=f"/browse/{self.id}").geturl()

    def __init__(self, bug_obj):
        super().__init__(bug_obj)
        self.id = self.bug.key
        self.weburl = self._url()
        self.component = self.bug.fields.components[0].name
        self.status = self.bug.fields.status.name
        self.creation_time_parsed = datetime.strptime(str(self.bug.fields.created), '%Y-%m-%dT%H:%M:%S.%f%z')
        self.summary = self.bug.fields.summary
        self.target_release = [x.name for x in self.bug.fields.fixVersions]


class BugTracker:
    def __init__(self, config):
        self.config = config
        self._server = config.get('server')

    def target_release(self):
        return self.config.get('target_release')

    def search(self):
        raise NotImplementedError


class JIRABugTracker(BugTracker):
    @staticmethod
    def get_config(runtime):
        version = f'{runtime.group_config.vars.MAJOR}.{runtime.group_config.vars.MINOR}'
        # TODO: have jira.yml file for all versions 4.6-4.11
        if version != '4.11':
            return {
                'server': "https://issues.stage.redhat.com",
                'project': 'OCPBUGS',
                'target_release': [f"{version}.0", f"{version}.z"]
            }
        return runtime.gitdata.load_data(key='jira').data

    def login(self, token_auth=None) -> JIRA:
        if not token_auth:
            token_auth = os.environ.get("JIRA_TOKEN")
            if not token_auth:
                raise ValueError(f"elliott requires login credentials for {self._server}. Set a JIRA_TOKEN env var ")
        client = JIRA(self._server, token_auth=token_auth)
        return client

    def __init__(self, config):
        super().__init__(config)
        self._project = config.get('project')
        self._client: JIRA = self.login()

    def target_release(self):
        return self.config.get('target_release')

    def get_bug(self, bugid, **kwargs) -> JIRABug:
        return JIRABug(self._client.issue(bugid, **kwargs))

    def get_bugs(self, bugids):
        return self.search(bug_list=bugids)

    def search(self,
               bug_list: Optional[List] = None,
               status: Optional[List] = None,
               target_release: Optional[List] = None,
               include_labels: Optional[List] = None,
               exclude_labels: Optional[List] = None) -> List[Issue]:
        query = f"project={self._project}"
        if bug_list:
            query += f" and issue in ({','.join(bug_list)})"
        if status:
            query += f" and status in ({','.join(status)})"
        if target_release:
            query += f" and fixVersion in ({','.join(target_release)})"
        if include_labels:
            query += f" and labels in ({','.join(exclude_labels)})"
        if exclude_labels:
            query += f" and labels not in ({','.join(exclude_labels)})"
        return [JIRABug(j) for j in self._client.search_issues(query, maxResults=False)]


class BugzillaBugTracker(BugTracker):
    @staticmethod
    def get_config(runtime):
        return runtime.gitdata.load_data(key='bugzilla').data

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

    def get_bugs(self, bugids, **kwargs):
        return [BugzillaBug(b) for b in self._client.getbugs(bugids, **kwargs)]

    def client(self):
        return self._client

    def search(self, status, search_filter='default', flag=None, filter_out_security_bugs=True, verbose=False):
        """Search the provided target_release's for bugs in the specified states

        :param status: The status(es) of bugs to search for
        :param search_filter: Which search filter from bz_data to use if multiple are specified
        :param flag: The Bugzilla flag (string) of bugs to search for. Flags are similar to status but are categorically
        different. https://bugzilla.readthedocs.io/en/latest/using/understanding.html#flags
        :param filter_out_security_bugs: Boolean on whether to filter out bugs tagged with the SecurityTracking keyword.

        :return: A list of Bug objects
        """
        query_url = _construct_query_url(self.config, status, search_filter, flag=flag)
        fields = ['id', 'status', 'summary', 'creation_time', 'cf_pm_score', 'component', 'external_bugs']

        if filter_out_security_bugs:
            query_url.addKeyword('SecurityTracking', 'nowords')
        else:
            fields.extend(['whiteboard', 'keywords'])

        if verbose:
            click.echo(query_url)

        return [BugzillaBug(b) for b in _perform_query(self._client, query_url, include_fields=fields)]

    def get_bugs_map(self, ids: List[int], raise_on_error: bool = True, **kwargs) -> Dict[int, Bug]:
        id_bug_map: Dict[int, Bug] = {}
        bugs: List[Bug] = self._client.getbugs(ids, permissive=not raise_on_error, **kwargs)
        for i, bug in enumerate(bugs):
            id_bug_map[ids[i]] = bug
        return id_bug_map

    def create_bug(self, bugtitle, bugdescription, target_status, keywords: List):
        createinfo = self._client.build_createbug(
            product=self.config.get('product'),
            version=self.config.get('version')[0],
            component="Release",
            summary=bugtitle,
            keywords=keywords,
            description=bugdescription)
        newbug = self._client.createbug(createinfo)
        # change state to VERIFIED, set target release
        try:
            update = self._client.build_update(status=target_status, target_release=self.config.get('target_release')[0])
            self._client.update_bugs([newbug.id], update)
        except Exception as ex:  # figure out the actual bugzilla error. it only happens sometimes
            sleep(5)
            self._client.update_bugs([newbug.id], update)
            print(ex)

        return newbug

    def create_placeholder(self, kind):
        """Create a placeholder bug

        :param kind: The "kind" of placeholder to create. Generally 'rpm' or 'image'

        :return: Placeholder Bug object
        """
        boilerplate = "Placeholder bug for OCP {} {} release".format(self.config.get('target_release')[0], kind)
        return self.create_bug(boilerplate, boilerplate, "VERIFIED", ["Automation"])

    def create_textonly(self, bugtitle, bugdescription):
        """Create a text only bug
        :param bugtitle: The title of the bug to create
        :param bugdescription: The description of the bug to create

        :return: Text only Bug object
        """
        return self.create_bug(bugtitle, bugdescription, "VERIFIED")


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


def set_state(bug, desired_state, noop=False, comment_for_release=None):
    """Change the state of a bug to desired_state

    :param bug:
    :param desired_state: Target state
    :param noop: Do not do anything
    :param comment_for_release: If set (e.g. "4.9") then comment on expected release.
    """
    current_state = bug.status
    comment = f'Elliott changed bug status from {current_state} to {desired_state}.'
    if comment_for_release:
        comment += f"\nThis bug is expected to ship in the next {comment_for_release} release created."
    if noop:
        logger.info(f"Would have changed BZ#{bug.id} from {current_state} to {desired_state} with comment:\n{comment}")
        return

    logger.info(f"Changing BZ#{bug.id} from {current_state} to {desired_state}")
    bug.setstatus(status=desired_state,
                  comment=comment,
                  private=True)


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
    bzapi = bugzilla.Bugzilla(bz_data['server'])
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

    if bz_data.get('filter'):
        filter_list = bz_data.get('filter')
    elif bz_data.get('filters'):
        filter_list = bz_data.get('filters').get(search_filter)

    for f in filter_list:
        query_url.addFilter(f.get('field'), f.get('operator'), f.get('value'))

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
        self.bz_host = bz_data.get('server')

        self.classification = bz_data.get('classification')
        self.product = bz_data.get('product')
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


def filter_bugs_by_cutoff_event(bzapi, bugs: Iterable, desired_statuses: Iterable[str], sweep_cutoff_timestamp: float) -> List:
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

    :param bzapi: Bugzilla API object
    :param bugs: a list of bugs
    :param desired_statuses: desired bug statuses
    :param timestamp: a unix timestamp
    :return: a list of found bugs
    """
    qualified_bugs = []
    desired_statuses = set(desired_statuses)

    # Filters out bugs that are created after the sweep cutoff timestamp
    before_cutoff_bugs = [bug for bug in bugs if to_timestamp(bug.creation_time) <= sweep_cutoff_timestamp]
    if len(before_cutoff_bugs) < len(bugs):
        logger.info(f"{len(bugs) - len(before_cutoff_bugs)} of {len(bugs)} bugs are ignored because they were created after the sweep cutoff timestamp {sweep_cutoff_timestamp} ({datetime.utcfromtimestamp(sweep_cutoff_timestamp)})")

    # Queries bug history
    bugs_history = bzapi.bugs_history_raw([bug.id for bug in before_cutoff_bugs])

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
        assert bug.id == bug_history["id"]  # `bugs_history["bugs"]` returned from Bugzilla API should have the same order as `before_cutoff_bugs`, but be safe

        # We are only interested in "status" field changes
        status_changes = filter(None, map(BugStatusChange.from_history_ent, bug_history["history"]))

        # status changes after the cutoff event
        after_cutoff_status_changes = list(itertools.dropwhile(lambda change: change.timestamp <= sweep_cutoff_timestamp, status_changes))

        # determines the status of the bug at the moment of the sweep cutoff event
        if not after_cutoff_status_changes:
            sweep_cutoff_status = bug.status  # no status change after the cutoff event; use current status
        else:
            sweep_cutoff_status = after_cutoff_status_changes[0].old  # sweep_cutoff_status should be the old status of the first status change after the sweep cutoff event

        if sweep_cutoff_status not in desired_statuses:
            logger.info(f"BZ {bug.id} is ignored because its status was {sweep_cutoff_status} at the moment of sweep cutoff ({datetime.utcfromtimestamp(sweep_cutoff_timestamp)})")
            continue

        # Per @Justin Pierce: If a BZ seems to qualify for a sweep currently and at the sweep cutoff event, then all state changes after the sweep cutoff event must be to a greater than the state which qualified the BZ at the sweep cutoff event.
        regressed_changes = [change.new for change in after_cutoff_status_changes if constants.VALID_BUG_STATES.index(change.new) <= constants.VALID_BUG_STATES.index(sweep_cutoff_status)]
        if regressed_changes:
            logger.warning(f"BZ {bug.id} is ignored because its status was {sweep_cutoff_status} at the moment of sweep cutoff ({datetime.utcfromtimestamp(sweep_cutoff_timestamp)})"
                           f", however its status changed back to {regressed_changes} afterwards")
            continue

        qualified_bugs.append(bug)

    return qualified_bugs


def approximate_cutoff_timestamp(basis_event: int, koji_api: ClientSession, metas: Iterable[Metadata]) -> float:
    """ Calculate an approximate sweep cutoff timestamp from the given basis event
    """
    basis_timestamp = koji_api.getEvent(basis_event)["ts"]
    builds: List[Dict] = asyncio.get_event_loop().run_until_complete(asyncio.gather(*[exectools.to_thread(meta.get_latest_build, complete_before_event=basis_event, honor_is=False) for meta in metas]))
    nvrs = [b["nvr"] for b in builds]
    rebase_timestamp_strings = filter(None, [isolate_timestamp_in_release(nvr) for nvr in nvrs])  # the timestamp in the release field of NVR is the approximate rebase time
    # convert to UNIX timestamps
    rebase_timestamps = [datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp() for ts in rebase_timestamp_strings]
    return min(basis_timestamp, max(rebase_timestamps, default=basis_timestamp))
