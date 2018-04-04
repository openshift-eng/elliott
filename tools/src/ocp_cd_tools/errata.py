"""Utility functions for general interactions with the errata SERVICE.

As a human, you will be working with "ADVISORIES". Advisories are one
or more errata (an errata is one or more erratum) as well as
associated metadata.

Classes representing an ERRATUM (a single errata)

"""

import copy
import datetime
import json
import shlex

from ocp_cd_tools import constants
import ocp_cd_tools.brew
import ocp_cd_tools.exceptions

import requests
from requests_kerberos import HTTPKerberosAuth


def get_erratum(id):
    """5.2.1.2. GET /api/v1/erratum/{id}

    Retrieve the advisory data.

    https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-get-apiv1erratumid

    :return SUCCESS: An Erratum object
    :return FAILURE: :bool:False
    :raises: ocp_cd_tools.exceptions.ErrataToolUnauthorizedException if the user is not authenticated to make the request
    """
    res = requests.get(constants.errata_get_erratum_url.format(id=id),
                       auth=HTTPKerberosAuth())

    if res.status_code == 200:
        return Erratum(body=res.json())
    elif res.status_code == 401:
        raise ocp_cd_tools.exceptions.ErrataToolUnauthorizedException(res.text)
    else:
        return False


def new_erratum(kind=None, release_date=None, create=False, minor='Y'):
    """5.2.1.1. POST /api/v1/erratum

    Create a new advisory.
    Takes an unrealized advisory object and related attributes using the following format:

    https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-post-apiv1erratum

    :param string kind: One of 'rpm' or 'image', effects boilerplate text
    :param string release_date: A date in the form YYYY-MM-DD
    :param bool create: If true, create the erratum in the Errata
        tool, by default just the DATA we would have POSTed is
        returned
    :param str/int minor: The minor release to substitute into the
        errata boilerplate text (see:
        :mod:`ocp_cd_tools.constants`). E.g., if this is a '3.9'
        release, you would provide '9' as the value for 'minor'

    :return: An Erratum object
    :raises: ocp_cd_tools.exceptions.ErrataToolUnauthorizedException if the user is not authenticated to make the request
    """
    if release_date is None:
        release_date = datetime.datetime.now() + datetime.timedelta(days=21)

    if kind is None:
        kind = 'rpm'

    body = copy.deepcopy(constants.errata_new_object)
    body['advisory']['publish_date_override'] = release_date
    body['advisory']['synopsis'] = constants.errata_synopsis[kind].format(Y=minor)

    # Fill in the minor version variables
    body['advisory']['description'] = body['advisory']['description'].format(Y=minor)
    body['advisory']['solution'] = body['advisory']['solution'].format(Y=minor)
    body['advisory']['synopsis'] = body['advisory']['synopsis'].format(Y=minor)
    body['advisory']['topic'] = body['advisory']['topic'].format(Y=minor)

    if create:
        # THIS IS NOT A DRILL
        res = requests.post(constants.errata_post_erratum_url,
                            auth=HTTPKerberosAuth(),
                            json=body)

        if res.status_code == 201:
            return Erratum(body=res.json())
        elif res.status_code == 401:
            raise ocp_cd_tools.exceptions.ErrataToolUnauthorizedException(res.text)
        else:
            raise ocp_cd_tools.exceptions.ErraraToolError("Other error (status_code={code}): {msg}".format(
                code=res.status_code,
                msg=res.text))
    else:
        # This is a noop
        return json.dumps(body, indent=2)


def get_filtered_list(filter_id=ocp_cd_tools.constants.errata_default_filter, limit=5):
    """return a list of Erratum() objects from results using the provided
filter_id

    :param filter_id: The ID number of the pre-defined filter
    :param int limit: How many erratum to list
    :return: A list of Erratum objects

    :raises ocp_cd_tools.exceptions.ErrataToolUnauthorizedException: If the user is not authenticated to make the request
    :raises ocp_cd_tools.exceptions.ErrataToolError: If the given filter does not exist, and, any other unexpected error

    Note: Errata filters are defined in the ET web interface
    """
    filter_endpoint = constants.errata_filter_list_url.format(
        id=filter_id)
    res = requests.get(filter_endpoint,
                       auth=HTTPKerberosAuth())
    if res.status_code == 200:
        # When asked for an advisory list which does not exist
        # normally you would expect a code like '404' (not
        # found). However, the Errata Tool sadistically returns a 200
        # response code. That leaves us with one option: Decide that
        # successfully parsing the response as a JSON object indicates
        # a successful API call.
        try:
            return [Erratum(body=advs) for advs in res.json()][:limit]
        except Exception:
            raise ocp_cd_tools.exceptions.ErrataToolError("Could not locate the given advisory filter: {fid}".format(
                fid=filter_id))
    elif res.status_code == 401:
        raise ocp_cd_tools.exceptions.ErrataToolUnauthorizedException(res.text)
    else:
        raise ocp_cd_tools.exceptions.ErrataToolError("Other error (status_code={code}): {msg}".format(
            code=res.status_code,
            msg=res.text))


class Erratum(object):
    """
    Model for interacting with individual Erratum. Erratum instances
    can be created from the brief info provided in a filtered list, as
    well as from the full erratum body returned by the Errata Tool
    API. See also: get_erratum(id) for creating a filled in Erratum
    object automatically.
    """

    date_format = '%Y-%m-%dT%H:%M:%SZ'

    def __init__(self, body=None):
        """If a `body` is provided then this is an EXISTING advisory and we
        are filling in all the  at the time of object creation.
        """
        self.body = body

        if body is not None:
            self._parse_body()
        else:
            # Attributes used in str() representation
            self.adv_name = ''
            self.synopsis = ''
            self.url = ''
            self.created_at = datetime.datetime.now()

    ######################################################################
    # Basic utility/setup methods

    def __str__(self):
        return "{date} {state} {synopsis} {url}".format(
            date=self.created_at.isoformat(),
            state=self.status,
            synopsis=self.synopsis,
            url=self.url)

    def _parse_body(self):
        """The `body` content is different based on where it came from."""
        # Erratum from the direct erratum GET method
        if 'params' in self.body:
            # An advisory will come back as one of the following
            # kinda, we're just not sure which until we read the
            # object body
            for kind in ['rhba', 'rhsa', 'rhea']:
                if kind in self.body['errata']:
                    # Call it just a generic "red hat advisory"
                    rha = self.body['errata'][kind]
                    break

            content = self.body['content']['content']

            self.advisory_id = rha['id']
            self.advisory_name = rha['fulladvisory']
            self.synopsis = rha['synopsis']
            self.description = content['description']
            self.solution = content['solution']
            self.topic = content['topic']
            self.status = rha['status']
            self.created_at = datetime.datetime.strptime(rha['created_at'], self.date_format)
            self.url = "{et}/advisory/{id}".format(
                et=ocp_cd_tools.constants.errata_url,
                id=self.advisory_id)
        else:
            # Erratum returned from an advisory filtered list
            self.advisory_id = self.body.get('id', 0)
            self.advisory_name = self.body.get('advisory_name', '')
            self.synopsis = self.body['synopsis']
            self.description = self.body['content']['description']
            self.solution = self.body['content']['solution']
            self.topic = self.body['content']['topic']
            self.status = self.body.get('status', 'NEW_FILES')
            self.created_at = datetime.datetime.strptime(self.body['timestamps']['created_at'], self.date_format)
            self.url = "{et}/advisory/{id}".format(
                et=ocp_cd_tools.constants.errata_url,
                id=self.advisory_id)

    def refresh(self):
        """Refreshes this object by pulling down a fresh copy from the API"""
        self.body = get_erratum(self.advisory_id).body
        self._parse_body()

    def to_json(self):
        return json.dumps(self.body, indent=2)

    ######################################################################
    # The following methods are related to REST API interactions

    def add_bugs(self, bugs=[]):  # pragma: no cover
        """Shortcut for several calls to self.add_bug()

        :param Bug bugs: A list of :module:`ocp_cd_tools.bugzilla` Bug objects
        """
        for bug in bugs:
            yield (self.add_bug(bug), bug.id)

    def add_bug(self, bug):
        """5.2.1.5. POST /api/v1/erratum/{id}/add_bug

        Add a bug to an advisory.

        Example request body:
            {"bug": "884202"}

        https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-post-apiv1erratumidadd_bug

        :param Bug bug: A :module:`ocp_cd_tools.bugzilla` Bug object
        """
        return requests.post(ocp_cd_tools.constants.errata_add_bug_url.format(id=self.advisory_id),
                             auth=HTTPKerberosAuth(),
                             json={'bug': bug.id})

    def add_builds(self, builds=[]):
        """5.2.2.7. POST /api/v1/erratum/{id}/add_builds

        Add one or more brew builds to an advisory.

        Example request body:
            {"product_version": "RHEL-7", "build": "rhel-server-docker-7.0-23", "file_types": ["ks","tar"]}

        The request body is a single object or an array of objects
        specifying builds to add, along with the desired product
        version (or pdc release) and file type(s). Builds may be
        specified by ID or NVR.

        https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-post-apiv1erratumidadd_builds

        :param list[Build] builds: List of Build objects to attach to
        an advisory

        :return: True if builds were added successfully

        :raises: ocp_cd_tools.exceptions.BrewBuildException if the builds could not be attached
        :raises: ocp_cd_tools.exceptions.ErrataToolUnauthorizedException if the user is not authenticated to make the request
        """
        data = [b.to_json() for b in builds]

        res = requests.post(ocp_cd_tools.constants.errata_add_builds_url.format(id=self.advisory_id),
                            auth=HTTPKerberosAuth(),
                            json=data)

        print(res.status_code)
        print(res.text)

        if res.status_code == 422:
            # "Something" bad happened
            print(res.status_code)
            print(res.text)
            raise ocp_cd_tools.exceptions.BrewBuildException(str(res.json()))
        elif res.status_code == 401:
            raise ocp_cd_tools.exceptions.ErrataToolUnauthorizedException(res.text)
        # TODO: Find the success return code
        else:
            return True

    # We're not actually using the comment code yet
    def add_comment(self, comment='default'):  # pragma: no cover
        """5.2.1.8. POST /api/v1/erratum/{id}/add_comment

        Add a comment to an advisory.
        Example request body:

            {"comment": "This is my comment"}

        The response body is the updated or unmodified advisory, in the same format as GET /api/v1/erratum/{id}.

        https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-post-apiv1erratumidadd_comment

        :param str comment: The ID of one of the pre-defined
        comment strings in ocp_cd_tools.constants.errata_comments
        """
        if comment not in constants.errata_comments:
            raise Exception("Invalid comment selected. See ocp_cd_tools.constants.errata_comments for legal values")
        else:
            data = {"comment": constants.errata_comments[comment]}
            return requests.post(ocp_cd_tools.constants.errata_add_comment_url.format(id=self.advisory_id),
                                 auth=HTTPKerberosAuth(),
                                 data=data)

    def change_state(self, state):
        """5.2.1.14. POST /api/v1/erratum/{id}/change_state

        Change the state of an advisory.
        Example request body:

            {"new_state": "QE"}

        Request body may contain:
            new_state: e.g. 'QE' (required)
            comment: a comment to post on the advisory (optional)

        :param str state: The state to change the advisory to
        :return: True on successful state change
        :raises: ocp_cd_tools.exceptions.ErrataToolUnauthorizedException if the user is not authenticated to make the request

        https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-post-apiv1erratumidchange_state
        """
        res = requests.post(ocp_cd_tools.constants.errata_change_state_url.format(id=self.advisory_id),
                            auth=HTTPKerberosAuth(),
                            data={"new_state": state})

        # You may receive this response when: Erratum isn't ready to
        # move to QE, no builds in erratum, erratum has no Bugzilla
        # bugs or JIRA issues.
        if res.status_code == 422:
            # Conditions not met
            raise ocp_cd_tools.exceptions.ErraraToolError("Can not change erratum state, preconditions not yet met. Error message: {msg}".format(
                msg=res.text))
        elif res.status_code == 401:
            raise ocp_cd_tools.exceptions.ErrataToolUnauthorizedException(res.text)
        elif res.status_code == 201:
            # POST processed successfully
            self.refresh()
            return True
