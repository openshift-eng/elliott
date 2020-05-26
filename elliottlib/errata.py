"""Utility functions for general interactions with the errata SERVICE.

As a human, you will be working with "ADVISORIES". Advisories are one
or more errata (an errata is one or more erratum) as well as
associated metadata.

Classes representing an ERRATUM (a single errata)

"""
from __future__ import absolute_import, print_function, unicode_literals
from future import standard_library
standard_library.install_aliases()
from errata_tool import ErrataConnector
import datetime
import json
import ssl
import re
from elliottlib import exceptions, constants, brew
from elliottlib.util import green_prefix, exit_unauthenticated

import requests
from requests_kerberos import HTTPKerberosAuth
from kerberos import GSSError
from errata_tool import Erratum, ErrataException, ErrataConnector

import xmlrpc.client

ErrataConnector._url = constants.errata_url
errata_xmlrpc = xmlrpc.client.ServerProxy(constants.errata_xmlrpc_url)


def new_erratum(et_data, errata_type=None, boilerplate_name=None, kind=None, release_date=None, create=False,
                assigned_to=None, manager=None, package_owner=None, impact=None, cves=None):
    """5.2.1.1. POST /api/v1/erratum

    Create a new advisory.
    Takes an unrealized advisory object and related attributes using the following format:

    https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-post-apiv1erratum

    :param et_data: The ET data dump we got from our erratatool.yaml file
    :param errata_type: The type of advisory to create (RHBA, RHSA, or RHEA)
    :param string kind: One of [rpm, image].
        Only used for backward compatibility.
    :param string boilerplate_name: One of [rpm, image, extras, metadata, cve].
        The name of boilerplate for creating this advisory
    :param string release_date: A date in the form YYYY-Mon-DD
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
    :param cves: The CVE(s) to attach to the advisory. Separate multiple CVEs with a space. Only applies to RHSA

    :return: An Erratum object
    :raises: exceptions.ErrataToolUnauthenticatedException if the user is not authenticated to make the request
    """
    if not release_date:
        release_date = datetime.datetime.now() + datetime.timedelta(days=21)

    if not kind:
        kind = 'rpm'

    if not boilerplate_name:
        boilerplate_name = kind

    if "boilerplates" in et_data and boilerplate_name in et_data["boilerplates"]:
        boilerplate = et_data['boilerplates'][boilerplate_name]
    else:  # FIXME: For backward compatibility.
        boilerplate = {
            "synopsis": (et_data['synopsis'].get(boilerplate_name, 'rpm') if boilerplate_name != "cve"
                         else et_data['synopsis'][kind]),
            "topic": et_data["topic"],
            "description": et_data["description"],
            "solution": et_data["solution"],
        }

    e = Erratum(
        product=et_data['product'],
        release=et_data['release'],
        errata_type=errata_type,
        synopsis=boilerplate['synopsis'],
        topic=boilerplate['topic'],
        description=boilerplate['description'],
        solution=boilerplate['solution'],
        qe_email=assigned_to,
        qe_group=et_data['quality_responsibility_name'],
        owner_email=package_owner,
        manager_email=manager,
        date=release_date
    )

    if errata_type == 'RHSA':
        e.security_impact = impact
        e.cve_names = cves

    if create:
        # THIS IS NOT A DRILL
        e.commit()
        return e
    else:
        return e


def build_signed(build):
    """return boolean: is the build signed or not

    :param string build: The build nvr or id
"""
    filter_endpoint = constants.errata_get_build_url.format(
        id=build)
    res = requests.get(filter_endpoint,
                       verify=ssl.get_default_verify_paths().openssl_cafile,
                       auth=HTTPKerberosAuth())
    if res.status_code == 200:
        return res.json()['rpms_signed']
    elif res.status_code == 401:
        raise exceptions.ErrataToolUnauthenticatedException(res.text)
    else:
        raise exceptions.ErrataToolError("Other error (status_code={code}): {msg}".format(
            code=res.status_code,
            msg=res.text))


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
            return [Erratum(errata_id=advs['id']) for advs in res.json()][:limit]
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
    # This is a paginated API, we need to increment page[number] until an empty array is returned.
    params = {
        "page[number]": 1
    }
    while True:
        res = requests.get(
            constants.errata_get_comments_url,
            params=params,
            verify=ssl.get_default_verify_paths().openssl_cafile,
            auth=HTTPKerberosAuth(),
            json=body)
        if res.ok:
            data = res.json().get('data', [])
            if not data:
                break
            for comment in data:
                yield comment
            params["page[number]"] += 1
        elif res.status_code == 401:
            raise exceptions.ErrataToolUnauthorizedException(res.text)
        else:
            return False


def get_metadata_comments_json(advisory_id):
    """
    Fetch just the comments that look like our metadata JSON comments from the advisory.
    Returns a list, oldest first.
    """
    comments = get_comments(advisory_id)
    metadata_json_list = []
    # they come out in (mostly) reverse order, start at the beginning
    for c in reversed(list(comments)):
        try:
            metadata = json.loads(c['attributes']['text'])
        except Exception:
            pass
        else:
            if 'release' in metadata and 'kind' in metadata and 'impetus' in metadata:
                metadata_json_list.append(metadata)
    return metadata_json_list


def get_builds(advisory_id, session=None):
    """5.2.2.6. GET /api/v1/erratum/{id}/builds
     Fetch the Brew builds associated with an advisory.
     Returned builds are organized by product version, variant, arch
    and include all the build files from the advisory.
     Returned attributes for the product version include:
    * name: name of the product version.
    * description: description of the product version.
     Returned attributes for each build include:
    * id: build's ID from Brew, Errata Tool also uses this as an internal ID
    * nvr: nvr of the build.
    * variant_arch: the list of files grouped by variant and arch.
     https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-get-apiv1erratumidbuilds
    """
    if not session:
        session = requests.session()
    res = session.get(constants.errata_get_builds_url.format(id=advisory_id),
                      verify=ssl.get_default_verify_paths().openssl_cafile,
                      auth=HTTPKerberosAuth())
    if res.status_code == 200:
        return res.json()
    else:
        raise exceptions.ErrataToolUnauthorizedException(res.text)

# https://errata.devel.redhat.com/bugs/1743872/advisories.json


def get_brew_builds(errata_id, session=None):
    """5.2.2.1. GET /api/v1/erratum/{id}/builds

    Get Errata list of builds.

    https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-get-apiv1erratumidbuilds

    :param str errata_id: the errata id
    :param requests.Session session: A python-requests Session object,
    used for for connection pooling. Providing `session` object can
    yield a significant reduction in total query time when looking up
    many builds.

    http://docs.python-requests.org/en/master/user/advanced/#session-objects

    :return: A List of initialized Build object with the build details
    :raises exceptions.BrewBuildException: When erratum return errors

    """
    if session is None:
        session = requests.session()

    res = session.get(constants.errata_get_builds_url.format(id=errata_id),
                      verify=ssl.get_default_verify_paths().openssl_cafile,
                      auth=HTTPKerberosAuth())
    brew_list = []
    if res.status_code == 200:
        jlist = res.json()
        for key in jlist.keys():
            for obj in jlist[key]['builds']:
                brew_list.append(brew.Build(nvr=list(obj.keys())[0], product_version=key))
        return brew_list
    else:
        raise exceptions.BrewBuildException("fetch builds from {id}: {msg}".format(
            id=errata_id,
            msg=res.text))


def get_brew_build(nvr, product_version='', session=None):
    """5.2.2.1. GET /api/v1/build/{id_or_nvr}

    Get Brew build details.

    https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-get-apiv1buildid_or_nvr

    :param str nvr: A name-version-release string of a brew rpm/image build
    :param str product_version: The product version tag as given to ET
    when attaching a build
    :param requests.Session session: A python-requests Session object,
    used for for connection pooling. Providing `session` object can
    yield a significant reduction in total query time when looking up
    many builds.

    http://docs.python-requests.org/en/master/user/advanced/#session-objects

    :return: An initialized Build object with the build details
    :raises exceptions.BrewBuildException: When build not found

    """
    if session is None:
        session = requests.session()

    res = session.get(constants.errata_get_build_url.format(id=nvr),
                      verify=ssl.get_default_verify_paths().openssl_cafile,
                      auth=HTTPKerberosAuth())

    if res.status_code == 200:
        return brew.Build(nvr=nvr, body=res.json(), product_version=product_version)
    else:
        raise exceptions.BrewBuildException("{build}: {msg}".format(
            build=nvr,
            msg=res.text))


def get_advisories_for_bug(bug_id, session=None):
    """ Fetch the list of advisories which a specified bug is attached to.

    5.2.26.7 /bugs/{id}/advisories.json

    :param bug_id: Bug ID
    :param session: Optional requests.Session
    """
    if not session:
        session = requests.session()
    r = session.get(constants.errata_get_advisories_for_bug_url.format(id=int(bug_id)),
                    verify=ssl.get_default_verify_paths().openssl_cafile,
                    auth=HTTPKerberosAuth())
    r.raise_for_status()
    return r.json()


def parse_exception_error_message(e):
    """
    :param e: exception messages (format is like 'Bug #1685399 The bug is filed already in RHBA-2019:1589.
        # Bug #1685398 The bug is filed already in RHBA-2019:1589.' )

    :return: [1685399, 1685398]
    """
    return [int(b.split('#')[1]) for b in re.findall(r'Bug #[0-9]*', str(e))]


def add_bugs_with_retry(advisory, bug_list, retried):
    """
    adding specified bug_list into advisory, retry 2 times: first time
    parse the exception message to get failed bug id list, remove from original
    list then add bug to advisory again, if still has failures raise exceptions

    :param advisory: advisory id
    :param bug_list: bug id list which suppose to attach to advisory
    :param retried: retry 2 times, first attempt fetch failed bugs sift out then attach again
    :return:
    """
    try:
        advs = Erratum(errata_id=advisory)
    except GSSError:
        exit_unauthenticated()

    if advs is False:
        raise exceptions.ElliottFatalError("Error: Could not locate advisory {advs}".format(advs=advisory))

    green_prefix("Adding {count} bugs to advisory {retry_times} times:".format(
        count=len(bug_list),
        retry_times=1 if retried is False else 2
    ))
    print(" {advs}".format(advs=advs))
    try:
        advs.addBugs(bug_list)
        advs.commit()
    except ErrataException as e:
        print("ErrataException Message: {}, retry it again".format(e))
        if retried is not True:
            black_list = parse_exception_error_message(e)
            retry_list = [x for x in bug_list if x not in black_list]
            if len(retry_list) > 0:
                add_bugs_with_retry(advisory, retry_list, True)
        else:
            raise exceptions.ElliottFatalError(getattr(e, 'message', repr(e)))


def get_rpmdiff_runs(advisory_id, status=None, session=None):
    """ Get RPMDiff runs for a given advisory.
    :param advisory_id: advisory number
    :param status: If set, only returns RPMDiff runs in the status.
    :param session: requests.Session object.
    """
    params = {
        "filter[active]": "true",
        "filter[test_type]": "rpmdiff",
        "filter[errata_id]": advisory_id,
    }
    if status:
        if status not in constants.ET_EXTERNAL_TEST_STATUSES:
            raise ValueError("{} is not a valid RPMDiff run status.".format(status))
        params["filter[status]"] = status
    url = constants.errata_url + "/api/v1/external_tests"
    if not session:
        session = requests.Session()

    # This is a paginated API. We need to increment page[number] until an empty array is returned.
    # https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-pagination
    page_number = 1
    while True:
        params["page[number]"] = page_number
        resp = session.get(
            url,
            params=params,
            auth=HTTPKerberosAuth(),
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        if not data:
            break
        for item in data:
            yield item
        page_number += 1


def get_advisory_images(image_advisory_id, raw=False):
    """List images of a given advisory, raw, or in the format we usually send to CCS (docs team)

    :param int image_advisory_id: ID of the main image advisory
    :param bool raw: Print undoctored artifact list

    :return: str with a list of images
    """
    cdn_docker_file_list = errata_xmlrpc.get_advisory_cdn_docker_file_list(image_advisory_id)

    if raw:
        return '\n'.join(cdn_docker_file_list.keys())

    pattern = re.compile(r'^redhat-openshift(\d)-')

    def _get_image_name(repo):
        return pattern.sub(r'openshift\1/', list(repo['docker']['target']['repos'].keys())[0])

    def _get_nvr(component):
        parts = component.split('-')
        return '{}-{}'.format(parts[-2], parts[-1])

    image_list = [
        '{}:{}'.format(_get_image_name(repo), _get_nvr(key))
        for key, repo in sorted(cdn_docker_file_list.items())
    ]

    return '#########\n{}\n#########'.format('\n'.join(image_list))
