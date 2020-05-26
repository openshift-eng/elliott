"""
Utility functions for general interactions with Brew and Builds
"""
from __future__ import absolute_import, print_function, unicode_literals
from future.utils import as_native_str
# stdlib
from typing import List, Dict, Optional, Tuple, Iterable
import ast
import time
import datetime
import subprocess
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing import cpu_count
import shlex
import ssl
import koji
import logging

# ours
from . import constants
from . import exectools
from . import logutil
from elliottlib import exceptions

# 3rd party
import click
import requests
from requests_kerberos import HTTPKerberosAuth

logger = logutil.getLogger(__name__)


def get_latest_builds(tag_component_tuples: List[Tuple[str, str]], session: koji.ClientSession) -> List[Optional[List[Dict]]]:
    """ Get latest builds for multiple Brew components

    :param tag_component_tuples: List of (tag, component_name) tuples
    :param session: instance of Brew session
    :return: a list Koji/Brew build objects
    """
    tasks = []
    with session.multicall(strict=True) as m:
        for tag, component_name in tag_component_tuples:
            if not (tag and component_name):
                tasks.append(None)
                continue
            tasks.append(m.getLatestBuilds(tag, package=component_name))
    return [task.result if task else None for task in tasks]


def tag_builds(tag: str, builds: List[str], session: koji.ClientSession):
    tasks = []
    with session.multicall(strict=False) as m:
        for build in builds:
            if not build:
                tasks.append(None)
                continue
            tasks.append(m.tagBuild(tag, build))
    return tasks


def wait_tasks(task_ids: Iterable[int], session: koji.ClientSession, sleep_seconds=10, logger: logging.Logger = None):
    waiting_tasks = set(task_ids)
    while waiting_tasks:
        multicall_tasks = []
        with session.multicall(strict=False) as m:
            for task_id in waiting_tasks:
                multicall_tasks.append(m.getTaskInfo(task_id, request=True))
        for t in multicall_tasks:
            task_info = t.result
            task_id = task_info["id"]
            state = koji.TASK_STATES[task_info["state"]]
            if logger:
                logger.debug(f"Task {task_id} state is {state}")
            if state not in {"FREE", "OPEN"}:
                waiting_tasks.discard(task_id)  # remove from the wait list
        if waiting_tasks:
            if logger:
                logger.debug(f"There are still {len(waiting_tasks)} tagging task(s) running. Will recheck in {sleep_seconds} seconds.")
            time.sleep(sleep_seconds)


def untag_builds(tag: str, builds: List[str], session: koji.ClientSession):
    tasks = []
    with session.multicall(strict=False) as m:
        for build in builds:
            if not build:
                tasks.append(None)
                continue
            tasks.append(m.untagBuild(tag, build))
    return tasks


def get_build_objects(ids_or_nvrs, session=None):
    """Get information of multiple Koji/Brew builds

    :param ids_or_nvrs: list of build nvr strings or numbers.
    :param session: instance of :class:`koji.ClientSession`
    :return: a list Koji/Brew build objects
    """
    logger.debug(
        "Fetching build info for {} from Koji/Brew...".format(ids_or_nvrs))
    if not session:
        session = koji.ClientSession(constants.BREW_HUB)
    # Use Koji multicall interface to boost performance. See https://pagure.io/koji/pull-request/957
    tasks = []
    with session.multicall(strict=True) as m:
        for b in ids_or_nvrs:
            tasks.append(m.getBuild(b))
    return [task.result for task in tasks]


def get_builds_tags(build_nvrs, session=None):
    """Get tags of multiple Koji/Brew builds

    :param builds_nvrs: list of build nvr strings or numbers.
    :param session: instance of :class:`koji.ClientSession`
    :return: a list of Koji/Brew tag list
    """
    if not session:
        session = koji.ClientSession(constants.BREW_HUB)
    tasks = []
    with session.multicall(strict=True) as m:
        for nvr in build_nvrs:
            tasks.append(m.listTags(build=nvr))
    return [task.result for task in tasks]


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
    if session is not None:
        res = session.get(constants.errata_get_build_url.format(id=nvr),
                          verify=ssl.get_default_verify_paths().openssl_cafile,
                          auth=HTTPKerberosAuth())
    else:
        res = requests.get(constants.errata_get_build_url.format(id=nvr),
                           verify=ssl.get_default_verify_paths().openssl_cafile,
                           auth=HTTPKerberosAuth())
    if res.status_code == 200:
        return Build(nvr=nvr, body=res.json(), product_version=product_version)
    else:
        raise exceptions.BrewBuildException("{build}: {msg}".format(
            build=nvr,
            msg=res.text))


def find_unshipped_build_candidates(base_tag, kind='rpm', brew_session=koji.ClientSession(constants.BREW_HUB)):
    """Find builds for a product and return a list of the builds only
    labeled with the -candidate tag that aren't attached to any open
    advisory.

    :param str base_tag: The tag to search for shipped/candidate
    builds. This is combined with '-candidate' to return the build
    difference.

    :param str kind: Search for RPM builds by default. 'image' is also
    acceptable (In elliott we only use this function for rpm)

    For example, if `base_tag` is 'rhaos-3.7-rhel7' then this will
    look for two sets of tagged builds:

    (1) 'rhaos-3.7-rhel7'
    (2) 'rhaos-3.7-rhel7-candidate'

    :return: A set of build strings where each build is only tagged as
    a -candidate build
    """
    shipped_builds_set = set()
    diff_builds = {}
    candidate_builds = brew_session.listTagged(tag='{}-candidate'.format(base_tag), latest=True, type=kind)
    for b in brew_session.listTagged(tag=base_tag, latest=True, type=kind):
        shipped_builds_set.add(b['nvr'])

    for b in candidate_builds:
        if b['nvr'] not in shipped_builds_set:
            diff_builds[b['nvr']] = b

    return diff_builds


class Build(object):
    """An existing brew build

How might you use this object? Great question. I'd start by fetching
the details of a known build from the Errata Tool using the
/api/v1/build/{id_or_nvr} API endpoint. Then take that build NVR or ID
and the build object from the API and initialize a new Build object
from those.

Save yourself some time and use the brew.get_brew_build()
function. Give it an NVR or a build ID and it will give you an
initialized Build object (provided the build exists).

    """

    def __init__(self, nvr=None, body={}, product_version=''):
        """Model for a brew build.

        :param str nvr: Name-Version-Release (or build ID) of a brew build

        :param dict body: An object as one gets from the errata tool
        /api/v1/build/{id_or_nvr} REST endpoint. See also:
        get_brew_build() (above)

        :param str product_version: The tag (from Errata Tool) of the
        product this build will be attached to, for example:
        "RHEL-7-OSE-3.9". This is only useful when representing this
        object as an item that would be given to the Errata Tool API
        add_builds endpoint (see: Build.to_json()).
        """
        self.nvr = nvr
        self.body = body
        self.all_errata = []
        self.kind = ''
        self.path = ''
        self.attached_erratum_ids = set([])
        self.attached_closed_erratum_ids = set([])
        self.product_version = product_version
        self.buildinfo = {}
        self.process()

    @as_native_str()
    def __str__(self):
        return self.nvr

    @as_native_str()
    def __repr__(self):
        return "Build({nvr})".format(nvr=self.nvr)

    # Set addition
    def __eq__(self, other):
        return self.nvr == other.nvr

    # Set addition
    def __ne__(self, other):
        return self.nvr != other.nvr

    # List sorting
    def __gt__(self, other):
        return self.nvr > other.nvr

    # List sorting
    def __lt__(self, other):
        return self.nvr < other.nvr

    @property
    def open_erratum(self):
        """Any open erratum this build is attached to"""
        return [e for e in self.all_errata if e['status'] in constants.errata_active_advisory_labels]

    @property
    def shipped_erratum(self):
        """Any shipped live erratum this build is attached to"""
        return [e for e in self.all_errata if e['status'] == constants.errata_shipped_advisory_label]

    @property
    def open_errata_id(self):
        """Any open erratum this build is attached to"""
        return [e['id'] for e in self.all_errata if e['status'] in constants.errata_active_advisory_labels]

    @property
    def attached_to_open_erratum(self):
        """Attached to any open erratum"""
        return len(self.open_erratum) > 0

    @property
    def attached_to_shipped_erratum(self):
        """Attached to any shipped erratum"""
        return len(self.shipped_erratum) > 0

    @property
    def closed_erratum(self):
        """Any closed erratum this build is attached to"""
        return [e for e in self.all_errata if e['status'] in constants.errata_inactive_advisory_labels]

    @property
    def attached_to_closed_erratum(self):
        """Attached to any closed erratum"""
        return len(self.closed_erratum) > 0

    @property
    def attached(self):
        """Attached to ANY erratum (open or closed)"""
        return len(self.all_errata) > 0

    def process(self):
        """Generate some easy to access attributes about this build so we
           don't have to do extra manipulation later back in the view"""
        # Has this build been attached to any erratum?
        self.all_errata = self.body.get('all_errata', [])

        # What kind of build is this?
        if 'files' in self.body:
            # All of the files are provided. What we're trying to do
            # is figure out if this build classifies as one of the
            # kind of builds we work with: RPM builds and Container
            # Image builds.
            #
            # We decide opportunistically, hence the abrupt
            # breaks. This decision process may require tweaking in
            # the future.
            #
            # I've only ever seen OSE image builds having 1 item (a
            # tar file) in the 'files' list. On the other hand, I have
            # seen some other general product builds that have both
            # tars and rpms (and assorted other file types), and I've
            # seen pure RPM builds with srpms and rpms...
            for f in self.body['files']:
                if f['type'] == 'rpm':
                    self.kind = 'rpm'
                    self.file_type = 'rpm'
                    break
                elif f['type'] == 'tar':
                    self.kind = 'image'
                    self.file_type = 'tar'
                    break

    def to_json(self):
        """Method for adding this build to advisory via the Errata Tool
API. This is the body content of the erratum add_builds endpoint."""
        return {
            'product_version': self.product_version,
            'build': self.nvr,
            'file_types': [self.file_type],
        }
