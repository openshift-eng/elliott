import os
import errno
import click
import atexit

from common import *
from image import ImageMetadata


class Runtime(object):

    def __init__(self, metadata_dir, user, verbose):
        self._verbose = verbose

        assert_dir(metadata_dir, "Invalid metadata-dir directory")

        self.metadata_dir = metadata_dir

        self._working_dir = None
        self._distgits_dir = None

        self._group = None

        self.distgit_branch = None

        self.group_dir = None

        self.user = user


        # Setup global aliases
        self.global_yaml_lines = [
            '_ocp_dist_git_branch: &OCP_DIST_GIT_BRANCH "master"  # TODO: determine what branch for the particular version of OSE being built',
            '_ocp_git_repo: &OCP_GIT_REPO "git@github.com:openshift/ose.git"',
        ]

        self.distgit_repos = {}


        # Map of source code repo alias (e.g. "ose") to a path on the filesystem where it has been cloned.
        # See registry_repo.
        self.source_repos = {}

        pass

    @property
    def working_dir(self):
        assert self._working_dir is not None
        return self._working_dir

    @working_dir.setter
    def working_dir(self, value):
        self._working_dir = value
        assert_dir(value, "Invalid working directory")
        self.distgits_dir = os.path.join(self._working_dir, "distgits")
        os.mkdir(self.distgits_dir)

    @property
    def group(self):
        assert self._group is not None
        return self._group

    @group.setter
    def group(self, value):
        self._group = value
        self.group_dir = os.path.join(self.metadata_dir, "groups", self._group)
        assert_dir(self.group_dir, "Cannot find group directory")

        self.info("Searching group directory: %s" % self.group_dir)
        with Dir(self.group_dir):
            for distgit_repo_name in [x for x in os.listdir(".") if os.path.isdir(x)]:
                self.distgit_repos[distgit_repo_name] = ImageMetadata(self, distgit_repo_name, distgit_repo_name)

    def verbose(self, message):
        if self._verbose:
            click.echo(message)

    def info(self, message, debug=None):
        if self._verbose:
            if debug is not None:
                self.verbose("%s [%s]" % (message, debug))
            else:
                self.verbose(message)
        else:
            click.echo(message)

    def clone_distgits(self):
        """
        Clones all dist-git repos in a given group into the distgits directory
        within the working directory.
        """
        self.info("Cloning all distgit repos into: %s" % self.distgits_dir)

        for image in self.distgit_repos.values():
            image.clone_distgit()

    def register_repo(self, alias, path):
        self.info("Registering source repo %s: %s" % (alias, path))
        assert_dir(path, "Error registering repo alias %s" % alias)
        self.source_repos[alias] = path
