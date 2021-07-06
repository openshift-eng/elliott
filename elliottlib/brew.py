"""
Utility functions for general interactions with Brew and Builds
"""

# stdlib
from elliottlib.model import Missing
import json
import logging
import ssl
import threading
import time
from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple

# 3rd party
import koji
import requests
from requests_kerberos import HTTPKerberosAuth

# ours
from elliottlib import constants, exceptions, logutil
from elliottlib.util import total_size

logger = logutil.getLogger(__name__)


def get_tagged_builds(tag_component_tuples: Iterable[Tuple[str, Optional[str]]], build_type: Optional[str], event: Optional[int], session: koji.ClientSession) -> List[Optional[List[Dict]]]:
    """ Get tagged builds  for multiple Brew tags (and components) as of the given event

    In each list for a component, builds are ordered from newest tagged to oldest tagged:
    https://pagure.io/koji/blob/3fed02c8adb93cde614af9f61abd12bbccdd6682/f/hub/kojihub.py#_1392

    :param tag_component_tuples: List of (tag, component_name) tuples
    :param build_type: if given, only retrieve specified build type (rpm, image)
    :param event: Brew event ID, or None for now.
    :param session: instance of Brew session
    :return: a list of Koji/Brew build dicts
    """
    tasks = []
    with session.multicall(strict=True) as m:
        for tag, component_name in tag_component_tuples:
            if not tag:
                tasks.append(None)
                continue
            tasks.append(m.listTagged(tag, event=event, package=component_name, type=build_type))
    return [build for task in tasks for build in task.result]


def get_latest_builds(tag_component_tuples: List[Tuple[str, str]], session: koji.ClientSession, event: Optional[int] = None) \
        -> List[Optional[List[Dict]]]:
    """ Get latest builds for multiple Brew components

    :param tag_component_tuples: List of (tag, component_name) tuples
    :param event: Brew event ID, or None for now.
    :param session: instance of Brew session
    :return: a list Koji/Brew build objects
    """
    if event:
        event = int(event)

    tasks = []
    with session.multicall(strict=True) as m:
        for tag, component_name in tag_component_tuples:
            if not (tag and component_name):
                tasks.append(None)
                continue
            tasks.append(m.getLatestBuilds(tag, event=event, package=component_name))
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
                logger.debug(
                    f"There are still {len(waiting_tasks)} tagging task(s) running. Will recheck in {sleep_seconds} seconds.")
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


def get_nvr_root_log(name, version, release, arch='x86_64'):
    root_log_url = '{host}/vol/rhel-{rhel_version}/packages/{name}/{version}/{release}/data/logs/{arch}/root.log'.format(
        host=constants.BREW_DOWNLOAD_URL,
        rhel_version=release[-1],
        name=name,
        version=version,
        release=release,
        arch=arch,
    )

    logger.debug(f"Trying {root_log_url}")
    res = requests.get(root_log_url, verify=ssl.get_default_verify_paths().openssl_cafile)
    if res.status_code != 200:
        raise exceptions.BrewBuildException("Could not get root.log for {}-{}-{}".format(name, version, release))
    return res.text


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

    def __str__(self):
        return self.nvr

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


class BuildStates(Enum):
    BUILDING = 0
    COMPLETE = 1
    DELETED = 2
    FAILED = 3
    CANCELED = 4


class KojiWrapperOpts(object):
    """
    A structure to carry special options into KojiWrapper API invocations. When using
    a KojiWrapper instance, any koji api call (or multicall) can include a KojiWrapperOpts
    as a positional parameter. It will be interpreted by the KojiWrapper and removed
    prior to sending the request on to the koji server.
    """

    def __init__(self, logger=None, caching=False, brew_event_aware=False, return_metadata=False):
        """
        :param logger: The koji API inputs and outputs will be logged at info level.
        :param caching: The result of the koji api call will be cached. Identical koji api calls (with caching=True)
                        will hit the cache instead of the server.
        :param brew_event_aware: Denotes that the caller is aware that the koji call they are making is NOT
                        constrainable with an event= or beforeEvent= kwarg. The caller should only be making such
                        a call if they know it will not affect the idempotency of the execution of tests. If not
                        specified, non-constrainable koji APIs will cause an exception to be thrown.
        :param return_metadata: If true, the API call will return KojiWrapperMetaReturn instead of the raw result.
                        This is for testing purposes (e.g. to see if caching is working). For multicall work, the
                        metadata wrapper will be returned from call_all()
        """
        self.logger = logger
        self.caching: bool = caching
        self.brew_event_aware: bool = brew_event_aware
        self.return_metadata: bool = return_metadata


class KojiWrapperMetaReturn(object):

    def __init__(self, result, cache_hit=False):
        self.result = result
        self.cache_hit = cache_hit


class KojiWrapper(koji.ClientSession):
    """
    Using KojiWrapper adds the following to the normal ClientSession:
    - Calls are retried if requests.exceptions.ConnectionError is encountered.
    - If the koji api call has a KojiWrapperOpts as a positional parameter:
        - If opts.logger is set, e.g. wrapper.getLastEvent(KojiWrapperOpts(logger=runtime.logger)), the invocation
          and results will be logged (the positional argument will not be passed to the koji server).
        - If opts.cached is True, the result will be cached and an identical invocation (also with caching=True)
          will return the cached value.
    """

    koji_wrapper_lock = threading.Lock()
    koji_call_counter = 0  # Increments atomically to help search logs for koji api calls
    # Used by the KojiWrapper to cache API calls, when a call's args include a KojiWrapperOpts with caching=True.
    # The key is either None or a brew event id to which queries are locked. The value is another dict whose
    # key is a string respresentation of the method to be invoked and the value is the cached value returned
    # from the server.
    koji_wrapper_result_cache = {}

    # A list of methods which support receiving an event kwarg. See --brew-event CLI argument.
    methods_with_event = set([
        'getBuildConfig',
        'getBuildTarget',
        'getBuildTargets',
        'getExternalRepo',
        'getExternalRepoList',
        'getFullInheritance',
        'getGlobalInheritance',
        'getHost',
        'getInheritanceData',
        'getLatestBuilds',
        'getLatestMavenArchives',
        'getLatestRPMS',
        'getPackageConfig',
        'getRepo',
        'getTag',
        'getTagExternalRepos',
        'getTagGroups',
        'listChannels',
        'listExternalRepos',
        'listPackages',
        'listTagged',
        'listTaggedArchives',
        'listTaggedRPMS',
        'newRepo',
    ])

    # Methods which cannot be constrained, but are considered safe to allow even when brew-event is set.
    # Why? If you know the parameters, those parameters should have already been constrained by another
    # koji API call.
    safe_methods = set([
        'getEvent',
        'getBuild',
        'listArchives',
        'listRPMs',
        'getPackage',
        'listTags',
        'gssapi_login',
        'sslLogin',
        'getTaskInfo',
        'build',
        'buildContainer',
        'buildImage',
        'buildReferences',
        'cancelBuild',
        'cancelTask',
        'cancelTaskChildren',
        'cancelTaskFull',
        'chainBuild',
        'chainMaven',
        'createImageBuild',
        'createMavenBuild',
        'filterResults',
        'getAPIVersion',
        'getArchive',
        'getArchiveFile',
        'getArchiveType',
        'getArchiveTypes',
        'getAverageBuildDuration',
        'getBuildLogs',
        'getBuildNotificationBlock',
        'getBuildType',
        'getBuildroot',
        'getChangelogEntries',
        'getImageArchive',
        'getImageBuild',
        'getLoggedInUser',
        'getMavenArchive',
        'getMavenBuild',
        'getPerms',
        'getRPM',
        'getRPMDeps',
        'getRPMFile',
        'getRPMHeaders',
        'getTaskChildren',
        'getTaskDescendents',
        'getTaskRequest',
        'getTaskResult',
        'getUser',
        'getUserPerms',
        'getVolume',
        'getWinArchive',
        'getWinBuild',
        'hello',
        'listArchiveFiles',
        'listArchives',
        'listBTypes',
        'listBuildRPMs',
        'listBuildroots',
        'listRPMFiles',
        'listRPMs',
        'listTags',
        'listTaskOutput',
        'listTasks',
        'listUsers',
        'listVolumes',
        'login',
        'logout',
        'logoutChild',
        'makeTask',
        'mavenEnabled',
        'mergeScratch',
        'moveAllBuilds',
        'moveBuild',
        'queryRPMSigs',
        'resubmitTask',
        'tagBuild',
        'tagBuildBypass',
        'taskFinished',
        'taskReport',
        'untagBuild',
        'winEnabled',
        'winBuild',
        'uploadFile',
    ])

    def __init__(self, koji_session_args, brew_event=None):
        """
        See class description on what this wrapper provides.
        :param koji_session_args: list to pass as *args to koji.ClientSession superclass
        :param brew_event: If specified, all koji queries (that support event=...) will be called with this
                event. This allows you to lock all calls to this client in time. Make sure the method is in
                KojiWrapper.methods_with_event if it is a new koji method (added after 2020-9-22).
        """
        self.___brew_event = None if not brew_event else int(brew_event)
        super(KojiWrapper, self).__init__(*koji_session_args)
        self.___before_timestamp = None
        if brew_event:
            self.___before_timestamp = self.getEvent(self.___brew_event)['ts']

    @classmethod
    def clear_global_cache(cls):
        with cls.koji_wrapper_lock:
            cls.koji_wrapper_result_cache.clear()

    @classmethod
    def get_cache_size(cls):
        with cls.koji_wrapper_lock:
            return total_size(cls.koji_wrapper_result_cache)

    @classmethod
    def get_next_call_id(cls):
        global koji_call_counter, koji_wrapper_lock
        with cls.koji_wrapper_lock:
            cid = cls.koji_call_counter
            cls.koji_call_counter = cls.koji_call_counter + 1
            return cid

    def _get_cache_bucket_unsafe(self):
        """Call while holding lock!"""
        cache_bucket = KojiWrapper.koji_wrapper_result_cache.get(self.___brew_event, None)
        if cache_bucket is None:
            cache_bucket = {}
            KojiWrapper.koji_wrapper_result_cache[self.___brew_event] = cache_bucket
        return cache_bucket

    def _cache_result(self, api_repr, result):
        with KojiWrapper.koji_wrapper_lock:
            cache_bucket = self._get_cache_bucket_unsafe()
            cache_bucket[api_repr] = result

    def _get_cache_result(self, api_repr, return_on_miss):
        with KojiWrapper.koji_wrapper_lock:
            cache_bucket = self._get_cache_bucket_unsafe()
            return cache_bucket.get(api_repr, return_on_miss)

    def modify_koji_call_kwargs(self, method_name, kwargs, kw_opts: KojiWrapperOpts):
        """
        For a given koji api method, modify kwargs by inserting an event key if appropriate
        :param method_name: The koji api method name
        :param kwargs: The kwargs about to passed in
        :param kw_opts: The KojiWrapperOpts that can been determined for this invocation.
        :return: The actual kwargs to pass to the superclass
        """
        brew_event = self.___brew_event
        if brew_event:
            if method_name == 'queryHistory':
                if 'beforeEvent' not in kwargs and 'before' not in kwargs:
                    # Only set the kwarg if the caller didn't
                    kwargs = kwargs or {}
                    kwargs['beforeEvent'] = brew_event + 1
            elif method_name == 'listBuilds':
                if 'completeBefore' not in kwargs and 'createdBefore' not in kwargs:
                    kwargs = kwargs or {}
                    kwargs['completeBefore'] = self.___before_timestamp
            elif method_name in KojiWrapper.methods_with_event:
                if 'event' not in kwargs:
                    # Only set the kwarg if the caller didn't
                    kwargs = kwargs or {}
                    kwargs['event'] = brew_event
            elif method_name in KojiWrapper.safe_methods:
                # Let it go through
                pass
            elif not kw_opts.brew_event_aware:
                # If --brew-event has been specified and non-constrainable API call is invoked, raise
                # an exception if the caller has not made clear that are ok with that via brew_event_aware option.
                raise IOError(f'Non-constrainable koji api call ({method_name}) with --brew-event set; you must use KojiWrapperOpts with brew_event_aware=True')

        return kwargs

    def modify_koji_call_params(self, method_name, params, aggregate_kw_opts: KojiWrapperOpts):
        """
        For a given koji api method, scan a tuple of arguments being passed to that method.
        If a KojiWrapperOpts is detected, interpret it. Return a (possible new) tuple with
        any KojiWrapperOpts removed.
        :param method_name: The koji api name
        :param params: The parameters for the method. In a standalone API call, this will just
                        be normal positional arguments. In a multicall, params will look
                        something like: (1328870, {'__starstar': True, 'strict': True})
        :param aggregate_kw_opts: The KojiWrapperOpts to be populated with KojiWrapperOpts instances found in the parameters.
        :return: The params tuple to pass on to the superclass call
        """
        new_params = list()
        for param in params:
            if isinstance(param, KojiWrapperOpts):
                kwOpts: KojiWrapperOpts = param

                # If a logger is specified, use that logger for the call. Only the most last logger
                # specific in a multicall will be used.
                aggregate_kw_opts.logger = kwOpts.logger or aggregate_kw_opts.logger

                # Within a multicall, if any call requests caching, the entire multiCall will use caching.
                # This may be counterintuitive, but avoids having the caller carefully setting caching
                # correctly for every single call.
                aggregate_kw_opts.caching |= kwOpts.caching

                aggregate_kw_opts.brew_event_aware |= kwOpts.brew_event_aware
                aggregate_kw_opts.return_metadata |= kwOpts.return_metadata
            else:
                new_params.append(param)

        return tuple(new_params)

    def _callMethod(self, name, args, kwargs=None, retry=True):
        """
        This method is invoked by the superclass as part of a normal koji_api.<apiName>(...) OR
        indirectly after koji.multicall() calls are aggregated and executed (this calls
        the 'multiCall' koji API).
        :param name: The name of the koji API.
        :param args:
            - When part of an ordinary invocation: a tuple of args. getBuild(1328870, strict=True) -> args=(1328870,)
            - When part of a multicall, contains methods, args, and kwargs. getBuild(1328870, strict=True) ->
                args=([{'methodName': 'getBuild','params': (1328870, {'__starstar': True, 'strict': True})}],)
        :param kwargs:
            - When part of an ordinary invocation, a map of kwargs. getBuild(1328870, strict=True) -> kwargs={'strict': True}
            - When part of a multicall, contains nothing? with multicall including getBuild(1328870, strict=True) -> {}
        :param retry: passed on to superclass retry
        :return: The value returned from the koji API call.
        """

        aggregate_kw_opts: KojiWrapperOpts = KojiWrapperOpts()

        if name == 'multiCall':
            # If this is a multiCall, we need to search through and modify each bundled invocation
            """
            Example args:
            ([  {'methodName': 'getBuild', 'params': (1328870, {'__starstar': True, 'strict': True})},
                {'methodName': 'getLastEvent', 'params': ()}],)
            """
            multiArg = args[0]   # args is a tuple, the first should be our listing of method invocations.
            for call_dict in multiArg:  # For each method invocation in the multicall
                method_name = call_dict['methodName']
                params = self.modify_koji_call_params(method_name, call_dict['params'], aggregate_kw_opts)
                if params:
                    params = list(params)
                    # Assess whether we need to inject event of beforeEvent into the koji call kwargs
                    possible_kwargs = params[-1]  # last element could be normal arg or kwargs dict
                    if isinstance(possible_kwargs, dict) and possible_kwargs.get('__starstar', None):
                        # __starstar is a special identifier added by the koji library indicating
                        # the entry is kwargs and not normal args.
                        params[-1] = self.modify_koji_call_kwargs(method_name, possible_kwargs, aggregate_kw_opts)
                call_dict['params'] = tuple(params)
        else:
            args = self.modify_koji_call_params(name, args, aggregate_kw_opts)
            kwargs = self.modify_koji_call_kwargs(name, kwargs, aggregate_kw_opts)

        my_id = KojiWrapper.get_next_call_id()

        logger = aggregate_kw_opts.logger
        return_metadata = aggregate_kw_opts.return_metadata
        use_caching = aggregate_kw_opts.caching

        retries = 4
        while retries > 0:
            try:
                if logger:
                    logger.info(f'koji-api-call-{my_id}: {name}(args={args}, kwargs={kwargs})')

                def package_result(result, cache_hit: bool):
                    ret = result
                    if return_metadata:
                        # If KojiWrapperOpts asked for information about call metadata back,
                        # return the results in a wrapper containing that information.
                        if name == 'multiCall':
                            # Results are going to be returned as [ [result1], [result2], ... ] if there is no fault.
                            # If there is a fault, the fault entry will be a dict.
                            ret = []
                            for entry in result:
                                # A fault was entry will not carry metadata, so only package when we see a list
                                if isinstance(entry, list):
                                    ret.append([KojiWrapperMetaReturn(entry[0], cache_hit=cache_hit)])
                                else:
                                    # Pass on fault without modification.
                                    ret.append(entry)
                        else:
                            ret = KojiWrapperMetaReturn(result, cache_hit=cache_hit)
                    return ret

                caching_key = None
                if use_caching:
                    # We need a reproducible immutable key from a dict with nest dicts. json.dumps
                    # and sorting keys is a deterministic way of achieving this.
                    caching_key = json.dumps({
                        'method_name': name,
                        'args': args,
                        'kwargs': kwargs
                    }, sort_keys=True)
                    result = self._get_cache_result(caching_key, Missing)
                    if result is not Missing:
                        if logger:
                            logger.info(f'CACHE HIT: koji-api-call-{my_id}: {name} returned={result}')
                        return package_result(result, True)

                result = super()._callMethod(name, args, kwargs=kwargs, retry=retry)

                if use_caching:
                    self._cache_result(caching_key, result)

                if logger:
                    logger.info(f'koji-api-call-{my_id}: {name} returned={result}')

                return package_result(result, False)
            except requests.exceptions.ConnectionError as ce:
                if logger:
                    logger.warning(f'koji-api-call-{my_id}: {method_name}(...) failed="{ce}""; retries remaining {retries - 1}')
                time.sleep(5)
                retries -= 1
                if retries == 0:
                    raise
