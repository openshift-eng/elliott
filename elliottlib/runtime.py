from multiprocessing import Lock
from multiprocessing.dummy import Pool as ThreadPool
from pykwalify.core import Core
import os
import sys
import tempfile
import threading
import shutil
import atexit
import datetime
import re
import yaml
import click
import logging
import functools
import traceback
import urlparse
import gitdata

import logutil
import assertion
import exectools
from pushd import Dir
from image import ImageMetadata
from rpmcfg import RPMMetadata
from model import Model, Missing
from multiprocessing import Lock
import brew
import constants
from exceptions import ElliottFatalError


# Registered atexit to close out debug/record logs
def close_file(f):
    f.close()


# Iterates through a list of strings, detecting if any entries have a
# comma delimited entry. If an entry contains a comma, it is split into
# multiple entries.
# The extended list is returned.
def flatten_comma_delimited_entries(l):
    nl = []
    for e in l:
        nl.extend(e.split(","))
    return nl


def remove_tmp_working_dir(runtime):
    if runtime.remove_tmp_working_dir:
        shutil.rmtree(runtime.working_dir)
    else:
        click.echo("Temporary working directory preserved by operation: %s" % runtime.working_dir)


class WrapException(Exception):
    """ https://bugs.python.org/issue13831 """
    def __init__(self):
        super(WrapException, self).__init__()
        exc_type, exc_value, exc_tb = sys.exc_info()
        self.exception = exc_value
        self.formatted = "".join(
            traceback.format_exception(exc_type, exc_value, exc_tb))

    def __str__(self):
        return "{}\nOriginal traceback:\n{}".format(
            Exception.__str__(self), self.formatted)


def wrap_exception(func):
    """ Decorate a function, wrap exception if it occurs. """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            raise WrapException()
    return wrapper

# ============================================================================
# Runtime object definition
# ============================================================================


class Runtime(object):
    # Use any time it is necessary to synchronize feedback from multiple threads.
    mutex = Lock()

    # Serialize access to the console, and record log
    log_lock = Lock()

    def __init__(self, **kwargs):
        self.include = []

        # initialize defaults in case no value is given
        self.verbose = False
        self.quiet = False
        self.load_wip = False
        self.load_disabled = False
        self.data_path = None

        for key, val in kwargs.items():
            self.__dict__[key] = val

        self._remove_tmp_working_dir = False
        self.group_config = None


        self.record_log = None
        self.record_log_path = None

        self.debug_log_path = None

        self.brew_logs_dir = None

        self.flags_dir = None

        # Map of dist-git repo name -> ImageMetadata object. Populated when group is set.
        self.image_map = {}

        # Map of dist-git repo name -> RPMMetadata object. Populated when group is set.
        self.rpm_map = {}

        # Map of stream alias to image name.
        self.stream_alias_overrides = {}

        self.initialized = False

        # Optionally available if self.fetch_rpms_for_tag() is called
        self.rpm_list = None
        self.rpm_search_tree = None

    def get_group_config(self):
        # group.yml can contain a `vars` section which should be a
        # single level dict containing keys to str.format(**dict) replace
        # into the YAML content. If `vars` found, the format will be
        # preformed and the YAML model will reloaded from that result
        tmp_config = Model(self.gitdata.load_data(key='group').data)
        replace_vars = tmp_config.vars
        if replace_vars is not Missing:
            try:
                group_yml = yaml.safe_dump(tmp_config.primitive(), default_flow_style=False)
                tmp_config = Model(yaml.safe_load(group_yml.format(**replace_vars)))
            except KeyError as e:
                raise ValueError('group.yml contains template key `{}` but no value was provided'.format(e.args[0]))
        return tmp_config

    def initialize(self, mode='images',
                   validate_content_sets=False,
                   no_group=False, clone_source=True, disabled=None):

        if self.initialized:
            return

        if self.quiet and self.verbose:
            click.echo("Flags --quiet and --verbose are mutually exclusive")
            exit(1)

        # We could mark these as required and the click library would do this for us,
        # but this seems to prevent getting help from the various commands (unless you
        # specify the required parameters). This can probably be solved more cleanly, but TODO
        if not no_group and self.group is None:
            click.echo("Group must be specified")
            exit(1)

        if self.working_dir is None:
            self.working_dir = tempfile.mkdtemp(".tmp", "elliott-")
            # This can be set to False by operations which want the working directory to be left around
            self.remove_tmp_working_dir = True
            atexit.register(remove_tmp_working_dir, self)
        else:
            self.working_dir = os.path.abspath(self.working_dir)
            if not os.path.isdir(self.working_dir):
                os.makedirs(self.working_dir)

        if disabled is not None:
            self.load_disabled = disabled

        self.initialize_logging()

        self.resolve_metadata()

        if no_group:
            return  # nothing past here should be run without a group

        self.record_log_path = os.path.join(self.working_dir, "record.log")
        self.record_log = open(self.record_log_path, 'a')
        atexit.register(close_file, self.record_log)

        # Directory where brew-logs will be downloaded after a build
        self.brew_logs_dir = os.path.join(self.working_dir, "brew-logs")
        if not os.path.isdir(self.brew_logs_dir):
            os.mkdir(self.brew_logs_dir)

        # Directory for flags between invocations in the same working-dir
        self.flags_dir = os.path.join(self.working_dir, "flags")
        if not os.path.isdir(self.flags_dir):
            os.mkdir(self.flags_dir)

        self.group_dir = self.gitdata.data_dir

        with Dir(self.group_dir):
            self.group_config = self.get_group_config()
            self.arches = self.group_config.get('arches', ['x86_64'])

            if self.group_config.name != self.group:
                raise IOError(
                    "Name in group.yml does not match group name. Someone may have copied this group without updating group.yml (make sure to check branch)")

            if self.group_config.includes is not Missing and self.include is None:
                self.include = self.group_config.includes

            if self.branch is None:
                if self.group_config.branch is not Missing:
                    self.branch = self.group_config.branch
                    self.logger.info("Using branch from group.yml: %s" % self.branch)
                else:
                    self.logger.info("No branch specified either in group.yml or on the command line; all included images will need to specify their own.")
            else:
                self.logger.info("Using branch from command line: %s" % self.branch)



            # Flattens a list like like [ 'x', 'y,z' ] into [ 'x.yml', 'y.yml', 'z.yml' ]
            # for later checking we need to remove from the lists, but they are tuples. Clone to list
            def flatten_list(names):
                if not names:
                    return []
                # split csv values
                result = []
                for n in names:
                    result.append([x for x in n.replace(' ', ',').split(',') if x != ''])
                # flatten result and remove dupes
                return list(set([y for x in result for y in x]))

            def filter_wip(n, d):
                return d.get('mode', 'enabled') in ['wip', 'enabled']

            def filter_enabled(n, d):
                return d.get('mode', 'enabled') == 'enabled'

            def filter_disabled(n, d):
                return d.get('mode', 'enabled') in ['enabled', 'disabled']

            exclude_keys = flatten_list(self.exclude)
            image_keys = flatten_list(self.images)
            rpm_keys = flatten_list(self.rpms)

            filter_func = None
            if self.load_wip and self.load_disabled:
                pass  # use no filter, load all
            elif self.load_wip:
                filter_func = filter_wip
            elif self.load_disabled:
                filter_func = filter_disabled
            else:
                filter_func = filter_enabled

            image_data = self.gitdata.load_data(path='images', keys=image_keys,
                                                exclude=exclude_keys,
                                                filter_funcs=None if len(image_keys) else filter_func)

            try:
                rpm_data = self.gitdata.load_data(path='rpms', keys=rpm_keys,
                                                  exclude=exclude_keys,
                                                  filter_funcs=None if len(rpm_keys) else filter_func)
            except gitdata.GitDataPathException:
                # some older versions have no RPMs, that's ok.
                rpm_data = {}

            missed_include = set(image_keys + rpm_keys) - set(image_data.keys() + rpm_data.keys())
            if len(missed_include) > 0:
                raise ElliottFatalError('The following images or rpms were either missing or filtered out: {}'.format(', '.join(missed_include)))

            if mode in ['images', 'both']:
                for i in image_data.itervalues():
                    metadata = ImageMetadata(self, i)
                    self.image_map[metadata.distgit_key] = metadata
                if not self.image_map:
                    self.logger.warning("No image metadata directories found for given options within: {}".format(self.group_dir))

            if mode in ['rpms', 'both']:
                for r in rpm_data.itervalues():
                    metadata = RPMMetadata(self, r, clone_source=clone_source)
                    self.rpm_map[metadata.distgit_key] = metadata
                if not self.rpm_map:
                    self.logger.warning("No rpm metadata directories found for given options within: {}".format(self.group_dir))

        # Make sure that the metadata is not asking us to check out the same exact distgit & branch.
        # This would almost always indicate someone has checked in duplicate metadata into a group.
        no_collide_check = {}
        for meta in self.rpm_map.values() + self.image_map.values():
            key = '{}/{}/#{}'.format(meta.namespace, meta.name, meta.branch())
            if key in no_collide_check:
                raise IOError('Complete duplicate distgit & branch; something wrong with metadata: {} from {} and {}'.format(key, meta.config_filename, no_collide_check[key].config_filename))
            no_collide_check[key] = meta

        # Read in the streams definite for this group if one exists
        streams = self.gitdata.load_data(key='streams')
        if streams:
            self.streams = Model(self.gitdata.load_data(key='streams').data)


    def initialize_logging(self):

        if self.initialized:
            return

        # Three flags control the output modes of the command:
        # --verbose prints logs to CLI as well as to files
        # --debug increases the log level to produce more detailed internal
        #         behavior logging
        # --quiet opposes both verbose and debug
        if self.debug:
            log_level = logging.DEBUG
        elif self.quiet:
            log_level = logging.WARN
        else:
            log_level = logging.INFO

        default_log_formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.WARN)
        root_stream_handler = logging.StreamHandler()
        root_stream_handler.setFormatter(default_log_formatter)
        root_logger.addHandler(root_stream_handler)

        # If in debug mode, let all modules log
        if not self.debug:
            # Otherwise, only allow children of ocp to log
            root_logger.addFilter(logging.Filter("ocp"))

        # Get a reference to the logger for elliott
        self.logger = logutil.getLogger()
        self.logger.propagate = False

        # levels will be set at the handler level. Make sure master level is low.
        self.logger.setLevel(logging.DEBUG)

        main_stream_handler = logging.StreamHandler()
        main_stream_handler.setFormatter(default_log_formatter)
        main_stream_handler.setLevel(log_level)
        self.logger.addHandler(main_stream_handler)

        self.debug_log_path = os.path.join(self.working_dir, "debug.log")
        debug_log_handler = logging.FileHandler(self.debug_log_path)
        # Add thread information for debug log
        debug_log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s (%(thread)d) %(message)s'))
        debug_log_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(debug_log_handler)

    @staticmethod
    def timestamp():
        return datetime.datetime.utcnow().isoformat()

    def image_metas(self):
        return self.image_map.values()

    def rpm_metas(self):
        return self.rpm_map.values()

    def all_metas(self):
        return self.image_metas() + self.rpm_metas()

    def register_source_alias(self, alias, path):
        self.logger.info("Registering source alias %s: %s" % (alias, path))
        path = os.path.abspath(path)
        assertion.isdir(path, "Error registering source alias %s" % alias)
        self.source_paths[alias] = path
        with Dir(path):
            origin_url = "?"
            rc1, out_origin, err_origin = exectools.cmd_gather(
                ["git", "config", "--get", "remote.origin.url"])
            if rc1 == 0:
                origin_url = out_origin.strip()
                # Usually something like "git@github.com:openshift/origin.git"
                # But we want an https hyperlink like http://github.com/openshift/origin
                if origin_url.startswith("git@"):
                    origin_url = origin_url[4:]  # remove git@
                    origin_url = origin_url[:-4]  # remove .git
                    origin_url = origin_url.replace(":", "/", 1)  # replace first colon with /
                    origin_url = "https://%s" % origin_url
            else:
                self.logger.error("Failed acquiring origin url for source alias %s: %s" % (alias, err_origin))

            branch = "?"
            rc2, out_branch, err_branch = exectools.cmd_gather(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"])
            if rc2 == 0:
                branch = out_branch.strip()
            else:
                self.logger.error("Failed acquiring origin branch for source alias %s: %s" % (alias, err_branch))

            self.add_record("source_alias", alias=alias, origin_url=origin_url, branch=branch, path=path)

    def register_stream_alias(self, alias, image):
        self.logger.info("Registering image stream alias override %s: %s" % (alias, image))
        self.stream_alias_overrides[alias] = image

    @property
    def remove_tmp_working_dir(self):
        """
        Provides thread safe method of checking whether runtime should clean up the working directory.
        :return: Returns True if the directory should be deleted
        """
        with self.log_lock:
            return self._remove_tmp_working_dir

    @remove_tmp_working_dir.setter
    def remove_tmp_working_dir(self, remove):
        """
        Provides thread safe method of setting whether runtime should clean up the working directory.
        :param remove: True if the directory should be removed. Only the last value set impacts the decision.
        """
        with self.log_lock:
            self._remove_tmp_working_dir = remove

    def add_record(self, record_type, **kwargs):
        """
        Records an action taken by oit that needs to be communicated to outside
        systems. For example, the update a Dockerfile which needs to be
        reviewed by an owner. Each record is encoded on a single line in the
        record.log. Records cannot contain line feeds -- if you need to
        communicate multi-line data, create a record with a path to a file in
        the working directory.

        :param record_type: The type of record to create.
        :param kwargs: key/value pairs

        A record line is designed to be easily parsed and formatted as:
        record_type|key1=value1|key2=value2|...|
        """

        # Multiple image build processes could be calling us with action simultaneously, so
        # synchronize output to the file.
        with self.log_lock:
            record = "%s|" % record_type
            for k, v in kwargs.iteritems():
                assert ("\n" not in str(k))
                # Make sure the values have no linefeeds as this would interfere with simple parsing.
                v = str(v).replace("\n", " ;;; ").replace("\r", "")
                record += "%s=%s|" % (k, v)

            # Add the record to the file
            self.record_log.write("%s\n" % record)
            self.record_log.flush()

    def resolve_image(self, distgit_name, required=True):
        if distgit_name not in self.image_map:
            if not required:
                return None
            raise IOError("Unable to find image metadata in group / included images: %s" % distgit_name)
        return self.image_map[distgit_name]

    def late_resolve_image(self, distgit_key):
        """Resolve image and retrive meta without adding to image_map.
        Mainly for looking up parent image info."""

        with Dir(self.images_dir):
            meta = ImageMetadata(self, self.images_dir, distgit_key + '.yml')
        return meta

    def resolve_stream(self, stream_name):

        # If the stream has an override from the command line, return it.
        if stream_name in self.stream_alias_overrides:
            return self.stream_alias_overrides[stream_name]

        if stream_name not in self.streams:
            raise IOError("Unable to find definition for stream: %s" % stream_name)

        return self.streams[stream_name]

    def _flag_file(self, flag_name):
        return os.path.join(self.flags_dir, flag_name)

    def flag_create(self, flag_name, msg=""):
        with open(self._flag_file(flag_name), 'w') as f:
            f.write(msg)

    def flag_exists(self, flag_name):
        return os.path.isfile(self._flag_file(flag_name))

    def flag_remove(self, flag_name):
        if self.flag_exists(flag_name):
            os.remove(self._flag_file(flag_name))

    def auto_version(self, repo_type):
        """
        Find and return the version of the atomic-openshift package in the OCP
        RPM repository.

        This repository is the primary input for OCP images.  The group_config
        for a group specifies the location for both signed and unsigned
        rpms.  The caller must indicate which to use.
        """

        repo_url = self.repos['rhel-server-ose-rpms'].baseurl(repo_type, 'x86_64')
        self.logger.info(
            "Getting version from atomic-openshift package in {}".format(
                repo_url)
        )

        # create a randomish repo name to avoid erroneous cache hits
        repoid = "oit" + datetime.datetime.now().strftime("%s")
        version_query = ["/usr/bin/repoquery", "--quiet", "--tempcache",
                         "--repoid", repoid,
                         "--repofrompath", repoid + "," + repo_url,
                         "--queryformat", "%{VERSION}",
                         "atomic-openshift"]
        rc, auto_version, err = exectools.cmd_gather(version_query)
        if rc != 0:
            raise RuntimeError(
                "Unable to get OCP version from RPM repository: {}".format(err)
            )

        version = "v" + auto_version.strip()

        self.logger.info("Auto-detected OCP version: {}".format(version))
        return version

    def valid_version(self, version):
        """
        Check if a version string matches an accepted pattern.
        A single lower-case 'v' followed by one or more decimal numbers,
        separated by a dot.  Examples below are not exhaustive
        Valid:
          v1, v12, v3.4, v2.12.0

        Not Valid:
          1, v1..2, av3.4, .v12  .99.12, v13-55
        """
        return re.match("^v\d+((\.\d+)+)?$", version) is not None

    @classmethod
    def _parallel_exec(self, f, args, n_threads):
        pool = ThreadPool(n_threads)
        ret = pool.map_async(wrap_exception(f), args)
        pool.close()
        pool.join()
        return ret

    def parallel_exec(self, f, args, n_threads=None):
        n_threads = n_threads if n_threads is not None else len(args)
        terminate_event = threading.Event()
        pool = ThreadPool(n_threads)
        ret = pool.map_async(
            wrap_exception(f),
            [(a, terminate_event) for a in args])
        pool.close()
        try:
            # `wait` without a timeout disables signal handling
            while not ret.ready():
                ret.wait(60)
        except KeyboardInterrupt:
            self.logger.warn('SIGINT received, signaling threads to terminate...')
            terminate_event.set()
        pool.join()
        return ret

    def resolve_metadata(self):
        """
        The group control data can be on a local filesystem, in a git
        repository that can be checked out, or some day in a database

        If the scheme is empty, assume file:///...
        Allow http, https, ssh and ssh+git (all valid git clone URLs)
        """

        if self.data_path is None:
            raise ElliottFatalError(
                ("No metadata path provided. Must be set via one of:\n"
                 "* data_path key in {}\n"
                 "* elliott --data-path [PATH|URL]\n"
                 "* Environment variable ELLIOTT_DATA_PATH\n"
                 ).format(self.cfg_obj.full_path))

        try:
            self.gitdata = gitdata.GitData(data_path=self.data_path, clone_dir=self.working_dir,
                                           branch=self.group, logger=self.logger)
            self.data_dir = self.gitdata.data_dir

        except gitdata.GitDataException as ex:
            raise ElliottFatalError(ex.message)
