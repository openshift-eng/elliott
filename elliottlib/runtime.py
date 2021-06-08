import atexit
import datetime
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import urllib.parse
from multiprocessing import Lock
from multiprocessing.dummy import Pool as ThreadPool
from typing import Optional

import click
import yaml

from elliottlib import assertion, brew, constants, gitdata, logutil, util, template
from elliottlib.exceptions import ElliottFatalError
from elliottlib.imagecfg import ImageMetadata
from elliottlib.model import Missing, Model


def remove_tmp_working_dir(runtime):
    if runtime.remove_tmp_working_dir:
        shutil.rmtree(runtime.working_dir)
    else:
        click.echo("Temporary working directory preserved by operation: %s" % runtime.working_dir)


# ============================================================================
# Runtime object definition
# ============================================================================


class Runtime(object):
    # Serialize access to the console, and record log
    log_lock = Lock()

    def __init__(self, **kwargs):
        # initialize defaults in case no value is given
        self.verbose = False
        self.quiet = False
        self.data_path = None

        for key, val in kwargs.items():
            self.__dict__[key] = val

        self._remove_tmp_working_dir = False
        self.group_config = None
        self.debug_log_path = None

        # Map of dist-git repo name -> ImageMetadata object. Populated when group is set.
        self.image_map = {}

        self.initialized = False

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
                formatted_group = yaml.safe_load(template.render(group_yml, **replace_vars))
                tmp_config = Model(formatted_group)
            except KeyError as e:
                raise ValueError('group.yml contains template key `{}` but no value was provided'.format(e.args[0]))
        return tmp_config

    def initialize(self, mode='none',
                   no_group=False):

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

        self.initialize_logging()

        if no_group:
            return  # nothing past here should be run without a group

        self.resolve_metadata()

        self.group_dir = self.gitdata.data_dir
        self.group_config = self.get_group_config()
        if self.group_config.name != self.group:
            raise IOError(
                "Name in group.yml does not match group name. Someone may have copied this group without updating group.yml (make sure to check branch)")

        if self.branch is not None:
            self.logger.info("Using branch from command line: %s" % self.branch)
        elif self.group_config.branch is not Missing:
            self.branch = self.group_config.branch
            self.logger.info("Using branch from group.yml: %s" % self.branch)
        else:
            self.logger.info("No branch specified either in group.yml or on the command line; all included images will need to specify their own.")

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

        def filter_enabled(n, d):
            return d.get('mode', 'enabled') == 'enabled'

        exclude_keys = flatten_list(self.exclude)
        image_keys = flatten_list(self.images)

        filter_func = filter_enabled

        replace_vars = self.group_config.vars.primitive() if self.group_config.vars else {}

        image_data = {}
        if mode in ['images', 'both']:
            image_data_tmpl = self.gitdata.load_data(path='images', keys=image_keys,
                                                     exclude=exclude_keys,
                                                     filter_funcs=None if len(image_keys) else filter_func)
            for i in image_data.values():
                image_key = template.render(i.key, **replace_vars)
                image_value = template.render(i, **replace_vars)
                self.late_resolve_image(image_key, add=True, data_obj=image_value)
            if not self.image_map:
                self.logger.warning("No image metadata directories found for given options within: {}".format(self.group_dir))

        missed_include = set(image_keys) - set(image_data.keys())
        if len(missed_include) > 0:
            raise ElliottFatalError('The following images or rpms were either missing or filtered out: {}'.format(', '.join(missed_include)))

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

        # levels will be set at the handler level. Make sure main level is low.
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

    def image_metas(self):
        return self.image_map.values()

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

    def late_resolve_image(self, distgit_name, add=False, data_obj=None):
        """Resolve image and retrieve meta, optionally adding to image_map.
        If image not found, error will be thrown"""

        if distgit_name in self.image_map:
            return self.image_map[distgit_name]
        if not data_obj:
            # TODO fail early if group_config vars doesn't match expected dict?
            replace_vars = self.group_config.vars.primitive() if self.group_config.vars else {}
            data_obj_templ = self.gitdata.load_data(path='images', key=distgit_name)
            data_obj = template.render(data_obj_templ, **replace_vars)
            if not data_obj:
                raise ElliottFatalError('Unable to resovle image metadata for {}'.format(distgit_name))

        meta = ImageMetadata(self, data_obj)
        if add:
            self.image_map[distgit_name] = meta
        return meta

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
            raise ElliottFatalError(ex)

    def get_public_upstream(self, remote_git: str) -> (str, Optional[str]):
        """
        Some upstream repo are private in order to allow CVE workflows. While we
        may want to build from a private upstream, we don't necessarily want to confuse
        end-users by referencing it in our public facing image labels / etc.
        In group.yaml, you can specify a mapping in "public_upstreams". It
        represents private_url_prefix => public_url_prefix. Remote URLs passed to this
        method which contain one of the private url prefixes will be translated
        into a new string with the public prefix in its place. If there is not
        applicable mapping, the incoming url will still be normalized into https.
        :param remote_git: The URL to analyze for private repo patterns.
        :return: tuple (url, branch)
            - url: An https normalized remote address with private repo information replaced.
            - branch: Optional public branch name if the public upstream source use a different branch name from the private upstream.
        """
        remote_https = util.convert_remote_git_to_https(remote_git)

        if self.group_config.public_upstreams:

            # We prefer the longest match in the mapping, so iterate through the entire
            # map and keep track of the longest matching private remote.
            target_priv_prefix = None
            target_pub_prefix = None
            target_pub_branch = None
            for upstream in self.group_config.public_upstreams:
                priv = upstream["private"]
                pub = upstream["public"]
                # priv can be a full repo, or an organization (e.g. git@github.com:openshift)
                # It will be treated as a prefix to be replaced
                https_priv_prefix = util.convert_remote_git_to_https(priv)  # Normalize whatever is specified in group.yaml
                https_pub_prefix = util.convert_remote_git_to_https(pub)
                if remote_https.startswith(f'{https_priv_prefix}/') or remote_https == https_priv_prefix:
                    # If we have not set the prefix yet, or if it is longer than the current contender
                    if not target_priv_prefix or len(https_priv_prefix) > len(target_pub_prefix):
                        target_priv_prefix = https_priv_prefix
                        target_pub_prefix = https_pub_prefix
                        target_pub_branch = upstream.get("public_branch")

            if target_priv_prefix:
                return (f'{target_pub_prefix}{remote_https[len(target_priv_prefix):]}', target_pub_branch)

        return (remote_https, None)
