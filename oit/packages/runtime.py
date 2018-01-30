import os
import click
import tempfile
import shutil
import atexit
import yaml
import datetime
import re

from common import assert_dir, assert_exec, gather_exec, Dir
from image import ImageMetadata
from rpm import RPMMetadata
from model import Model, Missing
from multiprocessing import Lock

DEFAULT_REGISTRIES = [
    "registry.reg-aws.openshift.com:443"
]


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


class Runtime(object):
    # Use any time it is necessary to synchronize feedback from multiple threads.
    mutex = Lock()

    # Serialize access to the debug_log, console, and record log
    log_lock = Lock()

    def __init__(self, **kwargs):

        self.include = []

        for key, val in kwargs.items():
            self.__dict__[key] = val

        self.remove_tmp_working_dir = False
        self.group_config = None

        # If source needs to be cloned by oit directly, the directory in which it will be placed.
        self.sources_dir = None

        self.distgits_dir = None

        self.record_log = None
        self.record_log_path = None

        self.debug_log = None
        self.debug_log_path = None

        self.brew_logs_dir = None

        self.flags_dir = None

        # Registries to push to if not specified on the command line; populated by group.yml
        self.default_registries = DEFAULT_REGISTRIES

        # Map of dist-git repo name -> ImageMetadata object. Populated when group is set.
        self.image_map = {}

        # Map of dist-git repo name -> RPMMetadata object. Populated when group is set.
        self.rpm_map = {}

        # Map of source code repo aliases (e.g. "ose") to a path on the filesystem where it has been cloned.
        # See registry_repo.
        self.source_paths = {}

        # Map of stream alias to image name.
        self.stream_alias_overrides = {}

        self.initialized = False

        # Will be loaded with the streams.yml Model
        self.streams = {}

        # Create a "uuid" which will be used in FROM fields during updates
        self.uuid = datetime.datetime.now().strftime("%Y%m%d.%H%M%S")

    def initialize(self, mode='images'):

        if self.initialized:
            return

        # We could mark these as required and the click library would do this for us,
        # but this seems to prevent getting help from the various commands (unless you
        # specify the required parameters). This can probably be solved more cleanly, but TODO
        if self.group is None:
            click.echo("Group must be specified")
            exit(1)

        assert_dir(self.metadata_dir, "Invalid metadata-dir directory")

        if self.working_dir is None:
            self.working_dir = tempfile.mkdtemp(".tmp", "oit-")
            # This can be set to False by operations which want the working directory to be left around
            self.remove_tmp_working_dir = True
            atexit.register(remove_tmp_working_dir, self)
        else:
            self.working_dir = os.path.abspath(self.working_dir)
            assert_dir(self.working_dir, "Invalid working directory")

        self.distgits_dir = os.path.join(self.working_dir, "distgits")
        if not os.path.isdir(self.distgits_dir):
            os.mkdir(self.distgits_dir)

        self.distgits_diff_dir = os.path.join(self.working_dir, "distgits-diffs")
        if not os.path.isdir(self.distgits_diff_dir):
            os.mkdir(self.distgits_diff_dir)

        self.sources_dir = os.path.join(self.working_dir, "sources")
        if not os.path.isdir(self.sources_dir):
            os.mkdir(self.sources_dir)

        self.debug_log_path = os.path.join(self.working_dir, "debug.log")
        self.debug_log = open(self.debug_log_path, 'a')
        atexit.register(close_file, self.debug_log)

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

        group_dir = os.path.join(self.metadata_dir, "groups", self.group)
        assert_dir(group_dir, "Cannot find group directory")

        images_dir = os.path.join(group_dir, 'images')
        assert_dir(group_dir, "Cannot find images directory for {}".format(group_dir))

        rpms_dir = os.path.join(group_dir, 'rpms')
        assert_dir(group_dir, "Cannot find rpms directory for {}".format(group_dir))

        # register the sources
        # For each "--source alias path" on the command line, register its existence with
        # the runtime.
        for r in self.source:
            self.register_source_alias(r[0], r[1])

        if self.sources:
            with open(self.sources, 'r') as sf:
                source_dict = yaml.load(sf)
                if not isinstance(source_dict, dict):
                    raise ValueError('--sources param must be a yaml file containing a single dict.')
                for key, val in source_dict.items():
                    self.register_source_alias(key, val)

        self.info("Searching group directory: %s" % group_dir)
        with Dir(group_dir):
            with open("group.yml", "r") as f:
                group_yml = f.read()

            self.group_config = Model(yaml.load(group_yml))

            if self.group_config.name != self.group:
                raise IOError(
                    "Name in group.yml does not match group name. Someone may have copied this group without updating group.yml (make sure to check branch)")

            if self.group_config.includes is not Missing and self.include is None:
                self.include = self.group_config.includes

            if self.branch is None:
                if self.group_config.branch is not Missing:
                    self.branch = self.group_config.branch
                    self.info("Using branch from group.yml: %s" % self.branch)
                else:
                    self.info("No branch specified either in group.yml or on the command line; all included images will need to specify their own.")
            else:
                self.info("Using branch from command line: %s" % self.branch)

            if len(self.include) > 0:
                self.include = flatten_comma_delimited_entries(self.include)
                self.info("Include list set to: %s" % str(self.include))

            images_list = []
            if os.path.isdir(images_dir):
                with Dir(images_dir):
                    images_list = [x for x in os.listdir(".") if os.path.isdir(x)]
            else:
                self.info('{} does not exist. Skipping image processing for group.'.format(rpms_dir))

            rpms_list = []
            if os.path.isdir(rpms_dir):
                with Dir(rpms_dir):
                    rpms_list = [x for x in os.listdir(".") if os.path.isdir(x)]
            else:
                self.log_verbose('{} does not exist. Skipping RPM processing for group.'.format(rpms_dir))

            # for later checking we need to remove from the lists, but they are tuples. Clone to list
            def flatten_names(names):
                if not names:
                    return []
                # split csv values
                result = []
                for n in names:
                    result.append([x for x in n.replace(' ', ',').split(',') if x != ''])
                # flatten result and remove dupes
                return list(set([y for x in result for y in x]))

            # process excludes before images and rpms
            # to ensure they never get added, -x is global
            self.exclude = flatten_names(self.exclude)
            if self.exclude:
                for x in self.exclude:
                    if x in images_list:
                        images_list.remove(x)
                    if x in rpms_list:
                        rpms_list.remove(x)

            image_include = []
            self.images = flatten_names(self.images)
            if self.images:
                also_exclude = set(self.images).intersection(set(self.exclude))
                if len(also_exclude):
                    self.info(
                        "Warning: The following images were included and excluded but exclusion takes precendence: {}".format(', '.join(also_exclude))
                    )
                for image in images_list:
                    if image in self.images:
                        image_include.append(image)

            rpm_include = []
            self.rpms = flatten_names(self.rpms)
            if self.rpms:
                also_exclude = set(self.rpms).intersection(set(self.exclude))
                if len(also_exclude):
                    self.info(
                        "Warning: The following rpms were included and excluded but exclusion takes precendence: {}".format(', '.join(also_exclude))
                    )
                for rpm in rpms_list:
                    if rpm in self.rpms:
                        rpm_include.append(rpm)

            missed_include = set(self.images + self.rpms) - set(image_include + rpm_include)
            if len(missed_include) > 0:
                raise IOError('Unable to find the following images or rpms configs: {}'.format(', '.join(missed_include)))

            def gen_ImageMetadata(name):
                self.image_map[name] = ImageMetadata(self, name, name)

            def gen_RPMMetadata(name):
                self.rpm_map[name] = RPMMetadata(self, name, name)

            def collect_configs(search_type, search_dir, name_list, include, gen):
                if len(name_list) == 0:
                    return  # no configs of this type found, bail out

                check_include = len(include) > 0
                with Dir(search_dir):
                    for distgit_repo_name in name_list:
                        if check_include:
                            if check_include and distgit_repo_name in include:
                                self.log_verbose("include: " + distgit_repo_name)
                                include.remove(distgit_repo_name)
                            else:
                                self.log_verbose("Skipping {} {} since it is not in the include list".format(search_type, distgit_repo_name))
                                continue

                        gen(distgit_repo_name)

            if mode in ['images', 'both']:
                collect_configs('image', images_dir, images_list, image_include, gen_ImageMetadata)
                if not self.image_map:
                    self.info("WARNING: No image metadata directories found within: {}".format(group_dir))

            if mode in ['rpms', 'both']:
                collect_configs('rpm', rpms_dir, rpms_list, rpm_include, gen_RPMMetadata)
                if not self.rpm_map:
                    self.info("WARNING: No rpm metadata directories found within: {}".format(group_dir))

        # Read in the streams definite for this group if one exists
        streams_path = os.path.join(group_dir, "streams.yml")
        if os.path.isfile(streams_path):
            with open(streams_path, "r") as s:
                self.streams = Model(yaml.load(s.read()))

    @staticmethod
    def timestamp():
        return datetime.datetime.utcnow().isoformat()

    def log_verbose(self, message):
        message = " ".join((self.timestamp(), message))
        with self.log_lock:
            if self.verbose:
                click.echo(message)
            self.debug_log.write(message + "\n")
            self.debug_log.flush()

    def info(self, message, debug=None):
        if self.verbose:
            if debug is not None:
                self.log_verbose("%s [%s]" % (message, debug))
            else:
                self.log_verbose(message)
        else:
            with self.log_lock:
                click.echo(" ".join((self.timestamp(), message)))

    def image_metas(self):
        return self.image_map.values()

    def rpm_metas(self):
        return self.rpm_map.values()

    def all_metas(self):
        return self.image_metas() + self.rpm_metas()

    def register_source_alias(self, alias, path):
        self.info("Registering source alias %s: %s" % (alias, path))
        path = os.path.abspath(path)
        assert_dir(path, "Error registering source alias %s" % alias)
        self.source_paths[alias] = path
        with Dir(path):
            origin_url = "?"
            rc1, out_origin, err_origin = gather_exec(self, ["git", "config", "--get", "remote.origin.url"])
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
                self.info("Error acquiring origin url for source alias %s: %s" % (alias, err_origin))

            branch = "?"
            rc2, out_branch, err_branch = gather_exec(self, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
            if rc2 == 0:
                branch = out_branch.strip()
            else:
                self.info("Error acquiring origin branch for source alias %s: %s" % (alias, err_branch))

            self.add_record("source_alias", alias=alias, origin_url=origin_url, branch=branch, path=path)

    def register_stream_alias(self, alias, image):
        self.info("Registering image stream alias override %s: %s" % (alias, image))
        self.stream_alias_overrides[alias] = image

    def add_record(self, record_type, **kwargs):
        """
        Records an action taken by oit that needs to be communicated to outside systems. For example,
        the update a Dockerfile which needs to be reviewed by an owner. Each record is encoded on a single
        line in the record.log. Records cannot contain line feeds -- if you need to communicate multi-line
        data, create a record with a path to a file in the working directory.
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

    def add_distgits_diff(self, distgit, diff):
        """
        Records the diff of changes applied to a distgit repo.
        """

        with open(os.path.join(self.distgits_diff_dir, distgit + '.patch'), 'w') as f:
            f.write(diff)

    def resolve_image(self, distgit_name, required=True):
        if distgit_name not in self.image_map:
            if not required:
                return None
            raise IOError("Unable to find image metadata in group / included images: %s" % distgit_name)
        return self.image_map[distgit_name]

    def resolve_stream(self, stream_name):

        # If the stream has an override from the command line, return it.
        if stream_name in self.stream_alias_overrides:
            return self.stream_alias_overrides[stream_name]

        if stream_name not in self.streams:
            raise IOError("Unable to find definition for stream: %s" % stream_name)

        return self.streams[stream_name]

    # Looks up a source alias and returns a path to the directory containing that source.
    # sources can be specified on the command line, or, failing that, in group.yml.
    # If a source specified in group.yaml has not be resolved before, this method will
    # clone that source to checkout the group's desired branch before returning a path
    # to the cloned repo.
    def resolve_source(self, alias, required=True):
        if alias in self.source_paths:
            return self.source_paths[alias]

        if self.group_config.sources is Missing or alias not in self.group_config.sources:
            if required:
                raise IOError("Source alias not found in specified sources or in the current group: %s" % alias)
            else:
                return None

        # Where the source will land
        source_dir = os.path.join(self.sources_dir, alias)

        # If this source has already been extracted for this working directory
        if os.path.isdir(source_dir):
            # Store so that the next attempt to resolve the source hits the map
            self.source_paths[alias] = source_dir
            self.info("Source '%s' already exists in (skipping clone): %s" % (alias, source_dir))
            return source_dir

        source_config = self.group_config.sources[alias]
        url = source_config["url"]
        self.info("Cloning source '%s' from %s as specified by group into: %s" % (alias, url, source_dir))
        assert_exec(self, ["git", "clone", url, source_dir])
        branch = source_config["branch"]
        fallback_branch = source_config.get("fallback-branch", None)
        found = False
        with Dir(source_dir):
            self.info("Attempting to checkout source '%s' branch %s in: %s" % (alias, branch, source_dir))

            if branch != "master":
                rc, out, err = gather_exec(self, ["git", "checkout", "-b", branch, "origin/%s" % branch])
            else:
                rc = 0

            if rc == 0:
                found = True
            else:
                if fallback_branch is not None:
                    self.info("  Unable to checkout branch %s ; trying fallback %s" % (branch, fallback_branch))
                    self.info("Attempting to checkout source '%s' fallback-branch %s in: %s" % (alias, fallback_branch, source_dir))
                    if fallback_branch != "master":
                        rc2, out, err = gather_exec(self, ["git", "checkout", "-b", fallback_branch, "origin/%s" % fallback_branch])
                    else:
                        rc2 = 0

                    if rc2 == 0:
                        found = True
                    else:
                        self.info("  Error checking out fallback-branch %s: %s" % (branch, err))
                else:
                    self.info("  Error checking out branch %s: %s" % (branch, err))

            if found:
                # Store so that the next attempt to resolve the source hits the map
                self.register_source_alias(alias, source_dir)
                return source_dir
            else:
                if required:
                    raise IOError("Error checking out target branch of source '%s' in: %s" % (alias, source_dir))
                else:
                    return None

    def export_sources(self, output):
        self.info('Writing sources to {}'.format(output))
        with open(output, 'w') as sources_file:
            yaml.dump(self.source_paths, sources_file, default_flow_style=False)

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

        if not repo_type in (self.group_config.repos):
            raise ValueError(
                "unknown repo-type {}, known types: {}".format(
                    repo_type,
                    ", ".join(self.group_config.repos.keys()))
            )

        # Are the repo keys in order? markllama 20180119 rhel-server-ose-rpms
        # repo_name = 'rhel-server-ose-rpms'
        repo_name = self.group_config.repos[repo_type].keys()[0]
        repo_url = self.group_config.repos[repo_type][repo_name].baseurl
        self.info(
            "Getting version from atomic-openshift package in {}".format(
                repo_url)
        )

        # create a randomish repo name to avoid erronious cache hits
        repoid = "oit" + datetime.datetime.now().strftime("%s")
        version_query = ["/usr/bin/repoquery", "--quiet", "--tempcache",
                         "--repoid", repoid,
                         "--repofrompath", repoid + "," + repo_url,
                         "--queryformat", "%{VERSION}",
                         "atomic-openshift"]
        rc, auto_version, err = gather_exec(self, version_query)
        if rc != 0:
            raise RuntimeError(
                "Unable to get OCP version from RPM repository: {}".format(err)
            )

        version = "v" + auto_version.strip()

        self.info("Auto-detected OCP version: {}".format(version))
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
        return re.match("^v\d+((\.\d+)+)?$", version) != None
