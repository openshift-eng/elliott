import yaml
import os
import urllib

import assertion
import constants
import exectools
import logutil

from model import Model, Missing


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


CONFIG_MODES = [
    'enable',  # business as usual
    'disable',  # manually disabled from automatically building
    'wip',  # Work in Progress, do not build
]

CONFIG_MODE_DEFAULT = CONFIG_MODES[0]


class Metadata(object):
    def __init__(self, meta_type, runtime, data_obj):
        """
        :param: meta_type - a string. Index to the sub-class <'rpm'|'image'>.
        :param: runtime - a Runtime object.
        :param: name - a filename to load as metadata
        """
        self.meta_type = meta_type
        self.runtime = runtime
        self.data_obj = data_obj
        self.base_dir = data_obj.base_dir
        self.config_filename = data_obj.filename
        self.full_config_path = data_obj.path


        # Some config filenames have suffixes to avoid name collisions; strip off the suffix to find the real
        # distgit repo name (which must be combined with the distgit namespace).
        # e.g. openshift-enterprise-mediawiki.apb.yml
        #      distgit_key=openshift-enterprise-mediawiki.apb
        #      name (repo name)=openshift-enterprise-mediawiki

        self.distgit_key = data_obj.key
        self.name = self.distgit_key.split('.')[0]   # Split off any '.apb' style differentiator (if present)

        self.runtime.logger.debug("Loading metadata from {}".format(self.full_config_path))

        self.config = Model(data_obj.data)

        self.mode = self.config.get('mode', CONFIG_MODE_DEFAULT).lower()
        if self.mode not in CONFIG_MODES:
            raise ValueError('Invalid mode for {}'.format(self.config_filename))

        self.enabled = (self.mode == CONFIG_MODE_DEFAULT)

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
        self.qualified_key = "%s/%s" % (self.namespace, self.distgit_key)

        # Includes information to identify the metadata being used with each log message
        self.logger = logutil.EntityLoggingAdapter(logger=self.runtime.logger, extra={'entity': self.qualified_key})

        self._distgit_repo = None

    def save(self):
        with open(self.full_config_path, "w") as f:
            yaml.safe_dump(self.config.primitive(), f, default_flow_style=False)

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
