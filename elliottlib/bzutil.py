"""
Utility functions and object abstractions for general interactions
with Red Hat Bugzilla
"""
from __future__ import absolute_import, print_function, unicode_literals
from future.utils import as_native_str
# stdlib
from future import standard_library
standard_library.install_aliases()
from time import sleep

import urllib.parse
from elliottlib import logutil

# ours
from . import constants
from elliottlib import exceptions, constants, util

# 3rd party
import click
import bugzilla


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
        # When severity isn't set on al tracking and flaw bugs, default to "Low"
        # https://jira.coreos.com/browse/ART-1192
        logger.warning("CVE impact couldn't be determined for tracking bug {}, defaulting to Low.".format(tracker.id))
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
            util.yellow_print(
                "Warning: found tracker bugs which doesn't block any other bugs")
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
        BugzillaFatorError: If bugs contains invalid bug ids, or if some other error occurs trying to
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
        BugzillaFatorError: If bugs contains invalid bug ids, or if some other error occurs trying to
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
            logger.warning("Found flaw bug with no alias, this can happen is a flaw hasn't been assigned a CVE")
    return flaw_cve_map


def create_placeholder(bz_data, kind, version):
    """Create a placeholder bug

    :param bz_data: The Bugzilla data dump we got from our bugzilla.yaml file
    :param kind: The "kind" of placeholder to create. Generally 'rpm' or 'image'
    :param version: The target version for the placeholder

    :return: Placeholder Bug object
    """

    bzapi = get_bzapi(bz_data)
    boilerplate = "Placeholder bug for OCP {} {} release".format(version, kind)

    createinfo = bzapi.build_createbug(
        product=bz_data['product'],
        version="unspecified",
        component="Release",
        summary=boilerplate,
        description=boilerplate)

    newbug = bzapi.createbug(createinfo)

    # change state to VERIFIED, set target release
    try:
        update = bzapi.build_update(status="VERIFIED", target_release=version)
        bzapi.update_bugs([newbug.id], update)
    except Exception as ex:  # figure out the actual bugzilla error. it only happens sometimes
        sleep(5)
        bzapi.update_bugs([newbug.id], update)
        print(ex)

    return newbug


def search_for_bugs(bz_data, status, search_filter='default', filter_out_security_bugs=True, verbose=False):
    """Search the provided target_release's for bugs in the specified states

    :param bz_data: The Bugzilla data dump we got from our bugzilla.yaml file
    :param status: The status(es) of bugs to search for
    :param search_filter: Which search filter from bz_data to use if multiple are specified
    :param filter_out_security_bugs: Boolean on whether to filter out bugs tagged with the SecurityTracking keyword.

    :return: A list of Bug objects
    """
    bzapi = get_bzapi(bz_data)
    query_url = _construct_query_url(bz_data, status, search_filter)

    if filter_out_security_bugs:
        query_url.addKeyword('SecurityTracking', 'nowords')

    # TODO: Expose this for debugging
    if verbose:
        click.echo(query_url)

    return _perform_query(bzapi, query_url, include_fields=['id', 'status', 'summary', 'creation_time', 'cf_pm_score', 'component'])


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

    A viable bug must be in one of MODIFIED and VERIFIED status.

    :param bug_obj: bug object
    :returns: True if viable
    """
    return bug_obj.status in ["MODIFIED", "VERIFIED"]


def is_cve_tracker(bug_obj):
    """ Check if a bug is a CVE tracker.

    A CVE tracker bug must have `SecurityTracking` and `Security` keywords.

    :param bug_obj: bug object
    :returns: True if the bug is a CVE tracker.
    """
    return "SecurityTracking" in bug_obj.keywords and "Security" in bug_obj.keywords


def get_bzapi(bz_data, interactive_login=False):
    bzapi = bugzilla.Bugzilla(bz_data['server'])
    if not bzapi.logged_in:
        print("elliott requires cached login credentials for {}".format(bz_data['server']))
        if interactive_login:
            bzapi.interactive_login()
    return bzapi


def _construct_query_url(bz_data, status, search_filter='default'):
    query_url = SearchURL(bz_data)

    if bz_data.get('filter'):
        filter_list = bz_data.get('filter')
    elif bz_data.get('filters'):
        filter_list = bz_data.get('filters').get(search_filter)

    for f in filter_list:
        query_url.addFilter(f.get('field'), f.get('operator'), f.get('value'))

    for v in bz_data.get('version', []):
        query_url.addVersion(v)

    for s in status:
        query_url.addBugStatus(s)

    for r in bz_data.get('target_release', []):
        query_url.addTargetRelease(r)

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
            number, self.field, self.operator, self.value
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

    @as_native_str()
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

    def addTargetRelease(self, release_string):
        self.target_releases.append(release_string)

    def addVersion(self, version):
        self.versions.append(version)

    def addBugStatus(self, status):
        self.bug_status.append(status)

    def addKeyword(self, keyword, keyword_type="anywords"):
        self.keyword = keyword
        self.keywords_type = keyword_type
