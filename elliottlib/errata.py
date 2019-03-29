"""Utility functions for general interactions with the errata SERVICE.

As a human, you will be working with "ADVISORIES". Advisories are one
or more errata (an errata is one or more erratum) as well as
associated metadata.

Classes representing an ERRATUM (a single errata)

"""

import copy
import datetime
import json
import ssl
import constants
import brew
import exceptions

import requests
from requests_kerberos import HTTPKerberosAuth
from errata_tool import Erratum


def find_mutable_erratum(kind, minor, major=3):
    """Find the latest mutable (may be updated/changed) erratum for a
    release series using a combination of search parameters.

    :param string kind: One of 'rpm' or 'image'
    :param str/int minor: The minor release to search against (i.e.,
        3.10, minor=10)
    :param str/int major: [Default 3] The major release to search
        against (i.e., 3.10, major=3)

    Example:

    To find a 3.10 erratum that you could attach new image builds to:
    * kind='image', minor=10

    Return Values:

    If an open AND mutable erratum exists matching your search:
    :return: An `Erratum` object of the discovered erratum

    If no open OR mutable erratum exists matching your search:
    :return: `None`

    DEV NOTE: If this function returns `None` then you can use the
    other find_*_erratum function to find the latest erratum of kind
    `kind` in the given release series. That is to say, if there are
    no open erratum for your release series you can still find the
    most recent erratum, even if it has passed the `QA` state or has
    even already been released.

    :raises: exceptions.ErrataToolUnauthorizedException if the user is not authenticated to make the request

    """
    pass


def find_latest_erratum(kind, major, minor):
    """Find an erratum in a given release series, in ANY state.

    Put simply, this tells you the erratum that has the most recent,
    or furthest in the future, release date set.

    This is useful for determining the release date of a new
    erratum. This combines the functionality provided by
    find_mutable_erratum and extends it by including searching closed
    or immutable erratum. These two functions can work well in tandem.

    Contrast this with find_mutable_erratum (best suited for elliott
    actions explicitly designed to UPDATE an erratum), this function
    promises to tell you the freshest release date of erratum in any
    state in a given release series.

    Example:

    You are creating a new erratum. The latest erratum in that series
    MAY or MAY NOT have gone to SHIPPED_LIVE state yet. Regardless of
    that, this function will tell you what the latest ship date is for
    an erratum in that series.

    If erratum exists matching your search:
    :return: An `Erratum` object of the erratum

    If no erratum can be found matching your search:
    :return: `None`
    """
    release = "{}.{}".format(major, minor)
    found_advisory = None

    # List of hashes because we will scan the Mutable advisories first
    filters = [
        {'Mutable Advisories': constants.errata_default_filter},
        {'Immutable Advisories': constants.errata_immutable_advisory_filter}
    ]

    # Fetch initial lists of advisories in each pre-defined filter
    advisory_list = []
    print("Running initial advisory fetching")
    for f in filters:
        state_desc, filter_id = f.items()[0]
        print("Fetching {state}".format(state=state_desc))
        advisories = get_filtered_list(filter_id, limit=50)
        # Filter out advisories that aren't for this release
        advisory_list.extend([advs for advs in advisories if " {} ".format(release) in advs.synopsis])
        print("Advisory list has {n} items after this fetch".format(
            n=len(advisory_list)))

    print("Looking for elliott metadata in comments:")
    matched_advisories = []
    for advisory in advisory_list:
        print("Scanning advisory {}".format(str(advisory)))

        for c in get_comments(advisory.errata_id):
            try:
                metadata = json.loads(c['attributes']['text'])
            except Exception:
                pass
            else:
                if str(metadata['release']) == str(release) and metadata['kind'] == kind and metadata['impetus'] == 'standard':
                    matched_advisories.append(advisory)
                    # Don't scan any more comments
                    break

    if matched_advisories == []:
        return None
    else:
        # loop over discovered advisories, select one with max() date
        real_advisories = [Erratum(errata_id=e.advisory_id) for e in matched_advisories]
        sorted_dates = sorted(real_advisories, key=lambda advs: advs.release_date)
        return sorted_dates[-1]


def new_erratum(et_data, errata_type=None, kind=None, release_date=None, create=False,
                assigned_to=None, manager=None, package_owner=None, impact=None, cve=None):
    """5.2.1.1. POST /api/v1/erratum

    Create a new advisory.
    Takes an unrealized advisory object and related attributes using the following format:

    https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-post-apiv1erratum

    :param et_data: The ET data dump we got from our erratatool.yaml file
    :param errata_type: The type of advisory to create (RHBA, RHSA, or RHEA)
    :param string kind: One of 'rpm' or 'image', effects boilerplate text
    :param string release_date: A date in the form YYYY-MM-DD
    :param bool create: If true, create the erratum in the Errata
        tool, by default just the DATA we would have POSTed is
        returned
    :param string assigned_to: The email address of the group responsible for
        examining and approving the advisory entries
    :param string manager: The email address of the manager responsible for
        managing the contents and status of this advisory
    :param string package_owner: The email address of the person who is handling
        the details and status of this advisory
    :param impact: The security impact. Only applies to RHSA
    :param cve: The CVE to attach to the advisory. Only applies to RHSA

    :return: An Erratum object
    :raises: exceptions.ErrataToolUnauthenticatedException if the user is not authenticated to make the request
    """
    if release_date is None:
        release_date = datetime.datetime.now() + datetime.timedelta(days=21)

    if kind is None:
        kind = 'rpm'

    e = Erratum(
            product = et_data['product'],
            release = et_data['release'],
            errata_type = errata_type,
            synopsis = et_data['synopsis'][kind],
            topic = et_data['topic'],
            description = et_data['description'],
            solution = et_data['solution'],
            qe_email = assigned_to,
            qe_group = et_data['quality_responsibility_name'],
            owner_email = package_owner,
            manager_email = manager,
            date = release_date
        )

    if errata_type == 'RHSA':
        e.security_impact = impact
        e.cve_names = cve

    if create:
        # THIS IS NOT A DRILL
        e.commit()
        return e
    else:
        return e


def get_filtered_list(filter_id=constants.errata_default_filter, limit=5):
    """return a list of Erratum() objects from results using the provided
filter_id

    :param filter_id: The ID number of the pre-defined filter
    :param int limit: How many erratum to list
    :return: A list of Erratum objects

    :raises exceptions.ErrataToolUnauthenticatedException: If the user is not authenticated to make the request
    :raises exceptions.ErrataToolError: If the given filter does not exist, and, any other unexpected error

    Note: Errata filters are defined in the ET web interface
    """
    filter_endpoint = constants.errata_filter_list_url.format(
        id=filter_id)
    res = requests.get(filter_endpoint,
                       verify=ssl.get_default_verify_paths().openssl_cafile,
                       auth=HTTPKerberosAuth())
    if res.status_code == 200:
        # When asked for an advisory list which does not exist
        # normally you would expect a code like '404' (not
        # found). However, the Errata Tool sadistically returns a 200
        # response code. That leaves us with one option: Decide that
        # successfully parsing the response as a JSONinfo object indicates
        # a successful API call.
        try:
            return [Erratum(errata_id = advs['id']) for advs in res.json()][:limit]
        except Exception:
            raise exceptions.ErrataToolError("Could not locate the given advisory filter: {fid}".format(
                fid=filter_id))
    elif res.status_code == 401:
        raise exceptions.ErrataToolUnauthenticatedException(res.text)
    else:
        raise exceptions.ErrataToolError("Other error (status_code={code}): {msg}".format(
            code=res.status_code,
            msg=res.text))

def add_comment(advisory_id, comment):
    """5.2.1.8. POST /api/v1/erratum/{id}/add_comment

        Add a comment to an advisory.
        Example request body:

            {"comment": "This is my comment"}

        The response body is the updated or unmodified advisory, in the same format as GET /api/v1/erratum/{id}.

        https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-post-apiv1erratumidadd_comment

        :param dict comment: The metadata object to add as a comment
        """
    data = {"comment": json.dumps(comment)}
    return requests.post(constants.errata_add_comment_url.format(id=advisory_id),
                            verify=ssl.get_default_verify_paths().openssl_cafile,
                            auth=HTTPKerberosAuth(),
                            data=data)

def get_comments(advisory_id):
    """5.2.10.2. GET /api/v1/comments?filter[key]=value

    Retrieve all advisory comments
    Example request body:

        {"filter": {"errata_id": 11112, "type": "AutomatedComment"}}

    Returns an array of comments ordered in descending order
    (newest first). The array may be empty depending on the filters
    used. The meaning of each attribute is documented under GET
    /api/v1/comments/{id} (see Erratum.get_comment())

    Included for reference:
    5.2.10.2.1. Filtering

    The list of comments can be filtered by applying
    filter[key]=value as a query parameter. All attributes of a
    comment - except advisory_state - can be used as a filter.

    This is a paginated API. Reference documentation:
    https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-pagination
    """
    body = {
        "filter": {
            "errata_id": advisory_id,
            "type": "Comment"
            }
        }
    res = requests.get(constants.errata_get_comments_url,
                        verify=ssl.get_default_verify_paths().openssl_cafile,
                        auth=HTTPKerberosAuth(),
                        json=body)

    if res.status_code == 200:
        return res.json().get('data', [])
    elif res.status_code == 401:
        raise exceptions.ErrataToolUnauthorizedException(res.text)
    else:
        return False
