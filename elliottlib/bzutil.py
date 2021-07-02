"""
Utility functions and object abstractions for general interactions
with Red Hat Bugzilla
"""
from datetime import datetime, timezone
from elliottlib.metadata import Metadata
from elliottlib.util import isolate_timestamp_in_release
import itertools
import re
from typing import Iterable, List
import urllib.parse
import xmlrpc.client
from time import sleep

import bugzilla
import click
from koji import ClientSession

from elliottlib import constants, exceptions, logutil

logger = logutil.getLogger(__name__)


def get_highest_impact(trackers, tracker_flaws_map):
    """Get the hightest impact of security bugs

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


def get_tracker_flaws_map(bzapi, trackers):
    """Get flaw bugs blocked by tracking bugs. For a definition of these terms see
    https://docs.engineering.redhat.com/display/PRODSEC/%5BDRAFT%5D+Security+bug+types

    :param bzapi: An instance of the python-bugzilla Bugzilla class
    :param trackers: A list of tracking bugs

    :return: A dict with tracking bug IDs as keys and lists of flaw bugs as values
    """
    tracker_flaw_ids_map = {
        tracker.id: get_flaw_bugs([tracker]) for tracker in trackers
    }

    flaw_ids = [flaw_id for _, flaw_ids in tracker_flaw_ids_map.items() for flaw_id in flaw_ids]
    flaw_id_bug_map = get_bugs(bzapi, flaw_ids)

    tracker_flaws_map = {tracker.id: [] for tracker in trackers}
    for tracker_id, flaw_ids in tracker_flaw_ids_map.items():
        for flaw_id in flaw_ids:
            flaw_bug = flaw_id_bug_map.get(flaw_id)
            if not flaw_bug or not is_flaw_bug(flaw_bug):
                logger.warning("Bug {} is not a flaw bug.".format(flaw_id))
                continue
            tracker_flaws_map[tracker_id].append(flaw_bug)
    return tracker_flaws_map


def get_bugs(bzapi, ids, raise_on_error=True):
    """ Get a map of bug ids and bug objects.

    :param bzapi: An instance of the python-bugzilla Bugzilla class
    :param ids: The IDs of the bugs you want to get the Bug objects for
    :param raise_on_error: If True, raise an error if failing to find bugs

    :return: A map of bug ids and bug objects

    :raises:
        BugzillaFatalError: If bugs contains invalid bug ids, or if some other error occurs trying to
        use the Bugzilla XMLRPC api. Could be because you are not logged in to Bugzilla or the login
        session has expired.
    """
    id_bug_map = {}
    bugs = bzapi.getbugs(ids)  # type: list
    for i, bug in enumerate(bugs):
        bug_id = ids[i]
        if not bug:
            msg = "Couldn't find bug {}.".format(bug_id)
            if raise_on_error:
                raise exceptions.BugzillaFatalError(msg)
            logger.warning(msg)
        id_bug_map[bug_id] = bug
    return id_bug_map


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


def set_state(bug, desired_state, noop=False):
    """Change the state of a bug to desired_state

    :param bug:
    :param desired_state: Target state
    :param noop: Do not do anything
    """
    current_state = bug.status
    if noop:
        logger.info(f"Would have changed BZ#{bug.bug_id} from {current_state} to {desired_state}")
        return

    logger.info(f"Changing BZ#{bug.bug_id} from {current_state} to {desired_state}")
    comment = f'Elliott changed bug status from {current_state} to {desired_state}.'
    bug.setstatus(status=desired_state,
                  comment=comment,
                  private=True)


def create_placeholder(bz_data, kind):
    """Create a placeholder bug

    :param bz_data: The Bugzilla data dump we got from our bugzilla.yaml file
    :param kind: The "kind" of placeholder to create. Generally 'rpm' or 'image'

    :return: Placeholder Bug object
    """

    bzapi = get_bzapi(bz_data)
    version = bz_data['version'][0]
    target_release = bz_data['target_release'][0]

    boilerplate = "Placeholder bug for OCP {} {} release".format(target_release, kind)

    createinfo = bzapi.build_createbug(
        product=bz_data['product'],
        version=version,
        component="Release",
        summary=boilerplate,
        description=boilerplate)

    newbug = bzapi.createbug(createinfo)

    # change state to VERIFIED, set target release
    try:
        update = bzapi.build_update(status="VERIFIED", target_release=target_release)
        bzapi.update_bugs([newbug.id], update)
    except Exception as ex:  # figure out the actual bugzilla error. it only happens sometimes
        sleep(5)
        bzapi.update_bugs([newbug.id], update)
        print(ex)

    return newbug


def search_for_bugs(bz_data, status, search_filter='default', flag=None, filter_out_security_bugs=True, verbose=False):
    """Search the provided target_release's for bugs in the specified states

    :param bz_data: The Bugzilla data dump we got from our bugzilla.yaml file
    :param status: The status(es) of bugs to search for
    :param search_filter: Which search filter from bz_data to use if multiple are specified
    :param flag: The Bugzilla flag (string) of bugs to search for. Flags are similar to status but are categorically
    different. https://bugzilla.readthedocs.io/en/latest/using/understanding.html#flags
    :param filter_out_security_bugs: Boolean on whether to filter out bugs tagged with the SecurityTracking keyword.

    :return: A list of Bug objects
    """
    bzapi = get_bzapi(bz_data)
    query_url = _construct_query_url(bz_data, status, search_filter, flag=flag)

    fields = ['id', 'status', 'summary', 'creation_time', 'cf_pm_score', 'component', 'external_bugs']

    if filter_out_security_bugs:
        query_url.addKeyword('SecurityTracking', 'nowords')
    else:
        fields.extend(['whiteboard', 'keywords'])

    # TODO: Expose this for debugging
    if verbose:
        click.echo(query_url)

    return _perform_query(bzapi, query_url, include_fields=fields)


def search_for_security_bugs(bz_data, status=None, search_filter='security', cve=None, verbose=False):
    """Search for CVE tracker bugs

    :param bz_data: The Bugzilla data dump we got from our bugzilla.yaml file
    :param status: The status(es) of bugs to search for
    :param search_filter: Which search filter from bz_data to use if multiple are specified
    :param cve: The CVE number to filter against

    :return: A list of CVE trackers
    """
    if status is None:
        status = ['NEW', 'ASSIGNED', 'POST', 'MODIFIED', 'ON_QA', 'VERIFIED', 'RELEASE_PENDING']

    bzapi = get_bzapi(bz_data, True)
    query_url = _construct_query_url(bz_data, status, search_filter)
    query_url.addKeyword('SecurityTracking')

    if verbose:
        click.echo(query_url)

    bug_list = _perform_query(bzapi, query_url, include_fields=['id', 'status', 'summary', 'blocks'])

    if cve:
        bug_list = [bug for bug in bug_list if cve in bug.summary]

    return bug_list


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


def get_valid_rpm_cves(bugs):
    """ Get valid rpm cve trackers with their component names

    An OCP rpm cve tracker has a whiteboard value "component:<component_name>"
    excluding suffixes (apb|container)

    :param bugs: list of bug objects
    :returns: A dict of bug object as key and component name as value
    """

    marker = r'component:\s*([-\w]+)'
    rpm_cves = {}
    for b in bugs:
        if is_cve_tracker(b):
            tmp = re.search(marker, b.whiteboard)
            if tmp and len(tmp.groups()) == 1:
                component_name = tmp.groups()[0]
                # filter out non-rpm suffixes
                if not re.search(r'-(apb|container)$', component_name):
                    rpm_cves[b] = component_name
    return rpm_cves


def get_bzapi(bz_data, interactive_login=False):
    bzapi = bugzilla.Bugzilla(bz_data['server'])
    if not bzapi.logged_in:
        print("elliott requires cached login credentials for {}".format(bz_data['server']))
        if interactive_login:
            bzapi.interactive_login()
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
    if include_fields is None:
        include_fields = ['id']

    query = bzapi.url_to_query(str(query_url))
    query["include_fields"] = include_fields

    return bzapi.query(query)


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
    nvrs = [meta.get_latest_build(koji_api=koji_api, event=basis_event, honor_is=False)["nvr"] for meta in metas]
    rebase_timestamp_strings = filter(None, [isolate_timestamp_in_release(nvr) for nvr in nvrs])  # the timestamp in the release field of NVR is the approximate rebase time
    # convert to UNIX timestamps
    rebase_timestamps = [datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp() for ts in rebase_timestamp_strings]
    return min(basis_timestamp, max(rebase_timestamps, default=basis_timestamp))
