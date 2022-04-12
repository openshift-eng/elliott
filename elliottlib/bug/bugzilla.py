import datetime
import bugzilla
import click
from datetime import datetime, timezone
from elliottlib.bug.base import Bug, BugTracker
from typing import List, Dict
from time import sleep
import urllib


class BugzillaBug(Bug):
    def __getattr__(self, attr):
        if attr in self.__dict__:
            return getattr(self, attr)
        return getattr(self.bug, attr)

    def __init__(self, bug_obj):
        super().__init__(bug_obj)
        self.creation_time_parsed = datetime.strptime(str(self.bug.creation_time), '%Y%m%dT%H:%M:%S').replace(tzinfo=timezone.utc)


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

    def get_bugs(self, bugids, verbose=False, **kwargs):
        return [BugzillaBug(b) for b in self._client.getbugs(bugids, verbose=verbose, **kwargs)]

    def client(self):
        return self._client

    def blocker_search(self, status, search_filter='default', filter_out_cve_trackers=False, verbose=False):
        query = _construct_query_url(self.config, status, search_filter, flag='blocker+')
        fields = ['id', 'status', 'summary', 'creation_time', 'cf_pm_score', 'component', 'external_bugs']
        if filter_out_cve_trackers:
            query.addKeyword('SecurityTracking', 'nowords')
        else:
            fields.extend(['whiteboard', 'keywords'])
        return self._search(query, fields, verbose)

    def search(self, status, search_filter='default', filter_out_cve_trackers=False, verbose=False):
        query = _construct_query_url(self.config, status, search_filter)
        fields = ['id', 'status', 'summary', 'creation_time', 'cf_pm_score', 'component', 'external_bugs']
        if filter_out_cve_trackers:
            query.addKeyword('SecurityTracking', 'nowords')
        else:
            fields.extend(['whiteboard', 'keywords'])
        return self._search(query, fields, verbose)

    def _search(self, query, fields, verbose=False):
        if verbose:
            click.echo(query)
        return [BugzillaBug(b) for b in _perform_query(self._client, query, include_fields=fields)]

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
