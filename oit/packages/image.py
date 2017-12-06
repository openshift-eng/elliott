import yaml
import shutil
import os
import tempfile
import hashlib
import time
import urllib
from multiprocessing import Lock
from dockerfile_parse import DockerfileParser
import json
from distgit import DistGitRepo, pull_image, OIT_COMMENT_PREFIX, EMPTY_REPO
from metadata import Metadata

from common import BREW_IMAGE_HOST, CGIT_URL, RetryException, assert_rc0, assert_file, assert_exec, assert_dir, exec_cmd, gather_exec, retry, Dir, recursive_overwrite
from model import Model, Missing


class ImageMetadata(Metadata):
    def __init__(self, runtime, dir, name):
        super(ImageMetadata, self).__init__('image', runtime, dir, name)

    def get_latest_build_release(self, dfp):

        """
        Queries brew to determine the most recently built release of the component
        associated with this image. This method does not rely on the "release"
        label needing to be present in the Dockerfile.

        :param dfp: A populated DockerFileParser
        :return: The most recently built release field string (e.g. "2")
        """

        component_name = self.get_component_name()
        version = dfp.labels["version"]

        # Brew can return all builds executed for a distgit repo. Most recent is listed last.
        # e.g. brew search build registry-console-docker-v3.6.173.0.74-*
        #     -> registry-console-docker-v3.6.173.0.74-2
        #     -> registry-console-docker-v3.6.173.0.74-3
        pattern = '{}-{}-*'.format(component_name, version)

        rc, stdout, stderr = gather_exec(self.runtime,
                                         ["brew", "search", "build", pattern])

        assert_rc0(rc, "Unable to search brew builds: %s" % stderr)

        builds = stdout.strip().splitlines()
        if not builds:
            raise IOError("No builds detected for %s using pattern: %s" % (self.qualified_name, pattern))

        last_build_id = builds[-1]  # e.g. "registry-console-docker-v3.6.173.0.75-1"
        release = last_build_id.rsplit("-", 1)[1]  # [ "registry-console-docker-v3.6.173.0.75", "1"]

        return release

    def pull_url(self):
        dfp = DockerfileParser()
        dfp.content = self.fetch_cgit_file("Dockerfile")
        # Don't trust what is the Dockerfile for "release". This field may not even be present.
        # Query brew to find the most recently built release for this component version.
        dfp.labels["release"] = self.get_latest_build_release(dfp)
        return "{host}/{l[name]}:{l[version]}-{l[release]}".format(
            host=BREW_IMAGE_HOST, l=dfp.labels)

    def pull_image(self):
        pull_image(self.runtime, self.pull_url())
