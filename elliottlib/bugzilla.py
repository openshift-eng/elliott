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

logger = logutil.getLogger(__name__)


def search_for_bugs(bz_data, status, verbose=False):
    """Search the provided target_release's for bugs in the specified states

    :return: A list of Bug objects
    """
    query_url = SearchURL(bz_data)

    for f in bz_data.get('filter'):
        query_url.addFilter(f.get('field'), f.get('operator'), f.get('value'))

    for v in bz_data.get('version'):
        query_url.addVersion(v)

    for s in status:
        query_url.addBugStatus(s)

    for r in bz_data.get('target_release'):
        query_url.addTargetRelease(r)

    # TODO: Expose this for debugging
    if verbose:
        click.echo(query_url)

    new_bugs = check_output(
        ['bugzilla', 'query', '--ids', '--from-url="{0}"'.format(query_url)]).splitlines()

    return [Bug(id=i) for i in new_bugs]

def search_for_bug_transitions(bz_data, current_state, changed_from, changed_to):
    query_url = SearchURL(bz_data)

    query_url.addBugStatus(current_state)

    query_url.addFilterOperator("AND_G")

    query_url.addFilter("bug_status", "changedfrom", changed_from)
    query_url.addFilter("bug_status", "changedto", changed_to)

    for v in bz_data.get('version'):
        query_url.addVersion(v)

    changed_bugs = check_output(
        ['bugzilla', 'query', '--ids', '--from-url="{0}"'.format(query_url)]).splitlines()

    return [Bug(id=i) for i in changed_bugs]

class Bug(object):
    """
    Abstract interactions with bugzilla bugs
    """
    def __init__(self, id):
        """:param int id: A Bugzilla bug ID"""
        self.id = id

    def __str__(self):
        return str(self.id)

    def __repr__(self):
        return str(self)

    def add_comment(self, comment, is_private):
        """Add a comment to a bug"""
        if is_private:
            call(['bugzilla', 'modify', self.id, '--comment', comment, '--private'])
        else:
            call(['bugzilla', 'modify', self.id, '--comment', comment])

    def add_flags(self, flags=[]):  # pragma: no cover
        """Add flags to a bug"""
        for flag in flags:
            self.add_flag(flag)

    def add_flag(self, flag):
        """Add the given flag to the bug"""
        call(['bugzilla', 'modify', '--flag', '{0}+'.format(flag), self.id])

    def add_whiteboard_value(self, value):
        call(['bugzilla', 'modify', self.id, '--whiteboard', value])

    def has_whiteboard_value(self, value):
        """Check if the value is in the Whiteboard for the bug"""
        return check_output(['bugzilla', 'query', '--id', self.id, '--whiteboard', value])


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

    def __str__(self):
        root_string = SearchURL.url_format.format(self.bz_host)

        url = root_string + self._status_string()

        url += "&classification={}".format(urllib.quote(self.classification))
        url += "&product={}".format(urllib.quote(self.product))
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
