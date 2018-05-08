import yaml
import os
import urllib

import logging

import assertion
import constants
from distgit import ImageDistGitRepo, RPMDistGitRepo
import exectools

from model import Model, Missing

#
# These are used as labels to index selection of a subclass.
#
DISTGIT_TYPES = {
    'image': ImageDistGitRepo,
    'rpm': RPMDistGitRepo
}


def cgit_url(name, filename, rev=None):
    ret = "/".join((constants.CGIT_URL, name, "plain", filename))
    if rev is not None:
        ret = "{}?h={}".format(ret, rev)
    return ret


def tag_exists(registry, name, tag, fetch_f=None):
    def assert_200(url):
        return urllib.urlopen(url).code == 200
    if fetch_f is None:
        fetch_f = assert_200
    return fetch_f("/".join((registry, "v1/repositories", name, "tags", tag)))


class Metadata(object):
    def __init__(self, meta_type, runtime, config_filename, logger=None):
        """
        :param: meta_type - a string. Index to the sub-class <'rpm'|'image'>.
        :param: runtime - a Runtime object.  used only for the .branch value.
        :param: name - a string appenaded to the derived namespace to locate
                       the git repo root.
        :param: logger - a python logger object.  Defaults to the root logger.

        The metadata object must be created when CWD is a directory containing
        a file named <name>.yml.

        This file must contain a YAML data structure like this:

          ---
          name: <value>
          distgit:
            namespace: <value>

        This file is converted to a Model which can be queried using dot
        notation.
        """

        self.logger = logger or logging.getLogger()

        self.meta_type = meta_type
        self.runtime = runtime
        self.config_filename = config_filename

        # Some config filenames have suffixes to avoid name collisions; strip off the suffix to find the real
        # distgit repo name (which must be combined with the distgit namespace).
        # e.g. openshift-enterprise-mediawiki.apb.yml
        #      distgit_key=openshift-enterprise-mediawiki.apb
        #      name (repo name)=openshift-enterprise-mediawiki

        self.distgit_key = config_filename.rsplit('.', 1)[0]  # Split off .yml
        self.name = self.distgit_key.split('.')[0]   # Split off any '.apb' style differentiator (if present)

        self.logger.debug("Current working directory is {}".format(os.getcwd()))
        self.logger.debug("Loading metadata from {}".format(self.config_filename))

        assertion.isfile(os.path.join(os.getcwd(), self.config_filename),
                         "Unable to find configuration file")

        with open(self.config_filename, "r") as f:
            config_yml_content = f.read()

        self.logger.debug(config_yml_content)
        self.config = Model(yaml.load(config_yml_content))

        # Basic config validation. All images currently required to have a name in the metadata.
        # This is required because from.member uses these data to populate FROM in images.
        # It would be possible to query this data from the distgit Dockerflie label, but
        # not implementing this until we actually need it.
        assert (self.config.name is not Missing)

        # Choose default namespace for config data
        if meta_type is "image":
            self.namespace = "containers"
        else:
            self.namespace = "rpms"

        # Allow config data to override
        if self.config.distgit.namespace is not Missing:
            self.namespace = self.config.distgit.namespace

        self.qualified_name = "%s/%s" % (self.namespace, self.name)

        self._distgit_repo = None

    def distgit_repo(self):
        if self._distgit_repo is None:
            self._distgit_repo = DISTGIT_TYPES[self.meta_type](self)
        return self._distgit_repo

    def branch(self):
        if self.config.distgit.branch is not Missing:
            return self.config.distgit.branch
        return self.runtime.branch

    def cgit_url(self, filename):
        return cgit_url(self.qualified_name, filename, self.branch())

    def fetch_cgit_file(self, filename):
        url = self.cgit_url(filename)
        req = exectools.retry(
            3, lambda: urllib.urlopen(url),
            check_f=lambda req: req.code == 200)
        return req.read()

    def tag_exists(self, tag):
        return tag_exists("http://" + constants.BREW_IMAGE_HOST, self.config.name, tag)

    def get_component_name(self):
        # By default, the bugzilla component is the name of the distgit,
        # but this can be overridden in the config yaml.
        component_name = self.name

        # For apbs, component name seems to have -apb appended.
        # ex. http://dist-git.host.prod.eng.bos.redhat.com/cgit/apbs/openshift-enterprise-mediawiki/tree/Dockerfile?h=rhaos-3.7-rhel-7
        if self.namespace == "apbs":
            component_name = "%s-apb" % component_name

        if self.namespace == "containers":
            component_name = "%s-container" % component_name

        if self.config.distgit.component is not Missing:
            component_name = self.config.distgit.component

        return component_name
