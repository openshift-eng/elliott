import yaml
import shutil
import os
import tempfile
import hashlib
import time
import urllib
import json
from distgit import ImageDistGitRepo, RPMDistGitRepo, pull_image

from common import BREW_IMAGE_HOST, CGIT_URL, RetryException, assert_rc0, assert_file, assert_exec, assert_dir, exec_cmd, retry, recursive_overwrite
from model import Model, Missing


DISTGIT_TYPES = {
    'image': ImageDistGitRepo,
    'rpm': RPMDistGitRepo
}


def cgit_url(name, filename, rev=None):
    ret = "/".join((CGIT_URL, name, "plain", filename))
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
    def __init__(self, meta_type, runtime, name):
        self.meta_type = meta_type
        self.runtime = runtime
        self.config_path = "{}.yml".format(name)
        self.name = name

        runtime.log_verbose("Loading metadata for %s from %s" % (name, self.config_path))

        assert_file(self.config_path, "Unable to find configuration file")

        with open(self.config_path, "r") as f:
            config_yml_content = f.read()

        runtime.log_verbose(config_yml_content)
        self.config = Model(yaml.load(config_yml_content))

        # Basic config validation. All images currently required to have a name in the metadata.
        # This is required because from.member uses these data to populate FROM in images.
        # It would be possible to query this data from the distgit Dockerflie label, but
        # not implementing this until we actually need it.
        assert (self.config.name is not Missing)

        self.namespace = "rpms"  # default type is rpms
        if self.config.distgit.namespace is not Missing:
            self.namespace = self.config.distgit.namespace

        self.qualified_name = "%s/%s" % (self.namespace, name)

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
        req = retry(
            3, lambda: urllib.urlopen(url),
            check_f=lambda req: req.code == 200)
        return req.read()

    def tag_exists(self, tag):
        return tag_exists("http://" + BREW_IMAGE_HOST, self.config.name, tag)

    def get_component_name(self):
        # By default, the bugzilla compnent is the name of the distgit,
        # but this can be overridden in the config yaml.
        component_name = self.name

        # For apbs, component name seems to have -apb appended.
        # ex. http://dist-git.host.prod.eng.bos.redhat.com/cgit/apbs/openshift-enterprise-mediawiki/tree/Dockerfile?h=rhaos-3.7-rhel-7
        if self.namespace == "apbs":
            component_name = "%s-apb" % component_name

        if self.config.distgit.component is not Missing:
            component_name = self.config.distgit.component

        return component_name
