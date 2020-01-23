from __future__ import absolute_import, print_function, unicode_literals
from . import logutil
import os
from io import BytesIO
import collections
import tarfile
import pygit2
import errata_tool
import koji
import logging
from . import constants
from future.standard_library import install_aliases
install_aliases()
from urllib.parse import urldefrag

# Exclude those files from the outputing tarball sources:
TARBALL_IGNORES = {".gitignore", ".oit", "container.yaml",
                   "content_sets.yml", "gating.yaml", "sources", "additional-tags"}

LOGGER = logutil.getLogger(__name__)

BuildWithProductVersion = collections.namedtuple(
    "BuildWithProductVersion", ["nvr", "product", "product_version"])


def find_builds_from_advisory(advisory_number, components):
    """ Returns a filtered list of builds attached to advisories

    NOTE: This function fetches the advisory info and attached builds using `errata_tool.Erratum()` Python API,
    which is pretty SLOW because it iterates over builds for signature checking but doesn't have an option to disable.
    Note that API cannot be called concurrently due to a race condition in its API implementation (instances of errata_tool.Erratum share class variables).

    :param advisory_number: an advisory number
    :param components: list of Koji/Brew components or NVRs to filter builds on the advisory
    :return: list of triple in the form of `(nvr, product, product_version)`
    """

    LOGGER.debug(
        "Fetching advisory {} from Errata Tool...".format(advisory_number))

    advisory = errata_tool.Erratum(errata_id=advisory_number)
    LOGGER.info("Got info for advisory {} - {} - {}: {} - {}".format(advisory_number, advisory.errata_state,
                                                                     advisory.errata_name, advisory.synopsis, advisory.url()))
    flattened_builds = [BuildWithProductVersion(nvr, advisory._product, product_version) for product_version,
                        nvrs in advisory.errata_builds.items() for nvr in nvrs]

    def matches_components(build):
        for component in components:
            if build[0].startswith(component):
                return True
        return False
    filtered_builds = [
        build for build in flattened_builds if matches_components(build)]
    return filtered_builds


def generate_tarball_source(tarball_file, prefix, local_repo_path, source_url, force_fetch=False):
    """ Gereate a tarball source from specified commit of a remote Git repository.

    This function uses pygit2 (libgit2) to walkthrough files of a commit.

    :param tarball_file: File object to write the tarball into
    :param prefix: Prepend a prefix (usually a directory) to files placed in the tarball.
    :param local_repo_path: Clone the remote repository into this local directory.
    :param source_url: Remote source repo url and commit hash seperated by `#`.
    :param force_fetch: Force download objects and refs from another repository
    """
    source_repo_url, source_commit_hash = urldefrag(source_url)
    assert source_commit_hash
    LOGGER.debug("Source is from repo {}, commit {}".format(
        source_repo_url, source_commit_hash))

    git_commit = None  # type: pygit2.Commit

    if os.path.isdir(local_repo_path) and os.listdir(local_repo_path):
        LOGGER.debug(
            "Local Git repo {} exists. Examining...".format(local_repo_path))
        discovered_repo = pygit2.discover_repository(
            local_repo_path, False, os.path.abspath(os.path.dirname(local_repo_path)))
        if not discovered_repo:
            raise ValueError(
                "{} exists but is not a valid Git repo.".format(local_repo_path))
        repo = pygit2.Repository(discovered_repo)
        origin = repo.remotes["origin"]  # type: pygit2.Remote
        if origin.url != source_repo_url:
            raise ValueError(
                "Found a different local Git repo in {}".format(discovered_repo))
        LOGGER.info(
            "Use existing local Git repo {}.".format(local_repo_path))
        fetch = force_fetch
        if not force_fetch:
            try:
                git_commit = repo.revparse_single(source_commit_hash).peel(pygit2.Commit)
            except KeyError:
                fetch = True
        if fetch:
            LOGGER.info("Fetching latest objects and refs...")
            repo.remotes["origin"].fetch()
    else:
        LOGGER.info("Cloning from {}...".format(source_repo_url))
        repo = pygit2.clone_repository(source_repo_url, local_repo_path)

    if not git_commit:
        git_commit = repo.revparse_single(source_commit_hash).peel(pygit2.Commit)
    LOGGER.info("Generating source from commit {}, author: {} <{}> message:{}".format(
        git_commit.id, git_commit.author.name, git_commit.author.email, git_commit.message))

    LOGGER.debug("Creating tarball {}...".format(tarball_file.name))
    with tarfile.open(fileobj=tarball_file, mode="w:gz") as archive:
        stack = [(git_commit.tree, "")]
        while stack:
            root, path = stack.pop()
            for _entry in root:
                entry = _entry  # type: pygit2.TreeEntry
                full_name = path + entry.name
                if full_name in TARBALL_IGNORES:
                    LOGGER.info(
                        "Excluded {} from source tarball.".format(full_name))
                    continue
                if entry.type == "tree":
                    stack.append((repo.get(entry.id), full_name + "/"))
                    continue
                info = tarfile.TarInfo(prefix + full_name)
                info.mtime = git_commit.committer.time
                info.uname = info.gname = 'root'  # Git does this!
                if entry.type == "commit":
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                    LOGGER.warning("Created placeholder dir for submodule {}: {}. Dist-git repos usually don't use submodules!".format(
                        full_name, entry.id))
                elif entry.type == "blob":
                    blob = repo.get(entry.id)  # type: pygit2.Blob
                    if entry.filemode == pygit2.GIT_FILEMODE_LINK:
                        info.type = tarfile.SYMTYPE
                        info.linkname = blob.data.decode("utf-8")
                        info.mode = 0o777  # symlinks get placeholder
                        info.size = 0
                    else:
                        info.mode = entry.filemode
                        info.size = blob.size
                    archive.addfile(info, BytesIO(blob.data))
                    LOGGER.debug("Added {}".format(full_name))
    tarball_file.flush()  # important to write to a temp file
