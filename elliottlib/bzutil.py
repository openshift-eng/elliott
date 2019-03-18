"""
Utility functions and object abstractions for general interactions
with Red Hat Bugzilla
"""

# stdlib
from subprocess import call, check_output
import urllib
import logutil

# ours
import constants

# 3rd party
import click
import bugzilla

logger = logutil.getLogger(__name__)

def get_bug_severity(bz_data, bug_id):
    """Get just the severity of a bug

    :param bz_data: The Bugzilla data dump we got from our bugzilla.yaml file
    :param bug_id: The ID of the bug you want information about

    :return: The severity of the bug
    """
    bzapi = get_bzapi(bz_data)
    bug = bzapi.getbug(bug_id, include_fields=['severity'])

    return bug.severity

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
    
    return _perform_query(bzapi, query_url)

def search_for_security_bugs(bz_data, status=None, search_filter='security', cve=None, verbose=False):
    """Search for CVE tracker bugs

    :param bz_data: The Bugzilla data dump we got from our bugzilla.yaml file
    :param status: The status(es) of bugs to search for
    :param search_filter: Which search filter from bz_data to use if multiple are specified
    :param cve: The CVE number to filter against

    :return: A list of CVE trackers
    """
    if status == None:
        status = ['NEW', 'ASSIGNED', 'POST', 'MODIFIED', 'ON_QA', 'VERIFIED', 'RELEASE_PENDING']

    bzapi = get_bzapi(bz_data)
    query_url = _construct_query_url(bz_data, status, search_filter)
    query_url.addKeyword('SecurityTracking')

    if verbose:
        click.echo(query_url)

    bug_list = _perform_query(bzapi, query_url, include_fields=['id', 'status', 'summary'])

    if(cve):
        bug_list = [bug for bug in bug_list if cve in bug.summary]
    
    return bug_list

def get_bzapi(bz_data):
    return bugzilla.Bugzilla(bz_data['server'])

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
        include_fields=['id']

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

    def __str__(self):
        root_string = SearchURL.url_format.format(self.bz_host)

        url = root_string + self._status_string()

        url += "&classification={}".format(urllib.quote(self.classification))
        url += "&product={}".format(urllib.quote(self.product))
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

    def addFilterOperator(self, operator):
        # Valid operators:
        #   AND_G - Match ALL against the same field
        #   OR - Match separately
        self.filter_operator += "&j_top={}".format(operator)

    def addTargetRelease(self, release_string):
        self.target_releases.append(release_string)

    def addVersion(self, version):
        self.versions.append(version)

    def addBugStatus(self, status):
        self.bug_status.append(status)

    def addKeyword(self, keyword, keyword_type="anywords"):
        self.keyword = keyword
        self.keywords_type = keyword_type
