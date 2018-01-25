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

from common import BREW_IMAGE_HOST, CGIT_URL, RetryException, assert_rc0, assert_file, assert_exec, assert_dir, exec_cmd, gather_exec, retry, recursive_overwrite
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

        tag = "{}-candidate".format(self.branch())

        rc, stdout, stderr = gather_exec(self.runtime,
                                         ["brew", "latest-build", tag, component_name])

        assert_rc0(rc, "Unable to search brew builds: %s" % stderr)

        latest = stdout.strip().splitlines()[-1].split(' ')[0]

        if not latest.startswith(component_name):
            # If no builds found, `brew latest-build` output will appear as:
            # Build                                     Tag                   Built by
            # ----------------------------------------  --------------------  ----------------
            raise IOError("No builds detected for %s using tag: %s" % (self.qualified_name, tag))

        release = latest.rsplit("-", 1)[1]  # [ "registry-console-docker-v3.6.173.0.75", "1"]

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
