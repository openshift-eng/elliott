#!/usr/bin/env python
"""
An OCP build requires very specific source repositories to be checked out and
configured. This script prepares those repositories.
"""

from __future__ import print_function

import argparse
import string
import os
import sys
import shutil
import time
import re

import git

import logging

logging.basicConfig()
logger = logging.getLogger()
log_levels = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'WARN': logging.WARNING,
    'ERROR': logging.ERROR
}

repo_urls = {
    "ose": "git@github.com:openshift/ose.git",
    "origin": "git@github.com:openshift/origin.git"
#    "origin.spec": "https://raw.githubusercontent.com/openshift/ose/master/origin.spec"
}


def branch_list(repo, remote_name, pattern=None):
    """
    Return the list of branch names from a given repo and remote
    Get the ls-remote --head list, filtering with the pattern.

    :param repo: A git.Repo object
    :param remote_name: A string representing the repo remote to query
    :param pattern: A string used to filter the results

    :return: list of branch names

    """
    # The return string for a remote reference is a single line with two
    # fields separated by a tab string.  The first field is a commit hash.
    # The second field is the reference path.  The unique part of the path
    # is the last field.
    #
    # 423f434cd877926ff47f3a710a7b0c414785515e	refs/heads/enterprise-3.0

    lines = repo.git.ls_remote(remote_name, pattern, heads=True).split("\n")
    return [str(line.split('/')[-1]) for line in lines]

# ----------------------------------------------------------------------------
# Define the CLI inputs for the command
# ----------------------------------------------------------------------------


def prepare_args():

    parser = argparse.ArgumentParser()

    parser.add_argument("--loglevel", type=str, default="INFO",
                        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
                        help="Select the log level for output messages")
    parser.add_argument("--destination", type=str, default="./repos",
                        help="The directory where repos will be placed")
    parser.add_argument("--version", type=str, default="latest",
                        help="The version to be checked out for build")
    parser.add_argument("--mode", type=str, default="auto",
                        choices=("auto", "release", "pre-release",
                                 "online:int", "online:stg"),
                        help="the build mode for this checkout")
    parser.add_argument("--clean", action="store_true", default=False,
                        help="Remove the destination before cloning")
    return parser


# ==========================================================================
# Version String Operations
# =========================================================================

def version_major(version_string):
    return version_string.split('.')[0]

def version_minor(version_string):
    return version_string.split('.')[1]

def version_major_minor(version_string):
    """
    Return just the first two fields of a dotted version/release string
    """
    return '.'.join(version_string.split('.')[0:2])
    
def get_spec_version(spec_file_name):
    """
    Return the version information from an RPM spec file.
    Return a dict containing the different components and the complete string

    :param spec_file_name: The path to an RPM spec file
    :return version dict: A dictionary with the components of the version and
                          release strings.
    """

    # Read the 
    spec_file = open(spec_file_name)
    lines = spec_file.readlines()
    
    # TBD check if there's only one
    version_lines = [l.strip() for l in lines if l.startswith("Version: ")]
    version_line = version_lines[0]
    version_string = version_line.split()[1]

    (major, minor) = version_string.split('.')[0:2]

    # TBD check if there's only one
    release_lines = [l.strip() for l in lines if l.startswith("Release: ")]
    release_line = release_lines[0]
    release_string = release_line.split()[1]

    # the release string from the spec file may have %{dist} templates or other
    # strings in it.  Just take the leading numeric fields (. separated)
    num_field_re = re.compile("(^[0-9.]+).*")
    num_field_match = num_field_re.match(release_string)
    if num_field_match:
        release_string = num_field_match.groups()[0]
    else:
        # should this throw an error?
        release_string = ""
    
    return {'version': version_string, 'release': release_string}

def cmp_version(v0, v1):
    """
    Compare two version strings of the form N0.N1.N2...
    Where N[0...] are decimal integers separated by periods(.)

    :param v0: the first version string
    :param v1: the second version string

    :return int: -1: v0 less than v1, 0: equal, 1: v0 greater than v1
    """

    # Convert both version strings to arrays of ints
    try: 
        a0 = [int(f) for f in v0.split('.')]
        a1 = [int(f) for f in v1.split('.')]
    except ValueError as error:
        logger.error("invalid version comparison: {} <> {}".format(v0, v1))
        raise error

    # Make sure both arrays have the same length
    while len(a0) < len(a1): a0.append(0)
    while len(a1) < len(a0): a1.append(0)
    
    # Make an array of tuples for comparison
    t = zip(a0, a1)

    # the first pair that aren't equal determine the comparison value
    for f in t:
        if f[0] != f[1]:
            return cmp(f[0], f[1])

    # They're all equal: the versions are equal
    return 0

def eq_version(v0, v1):
    """
    Check if two version strings are equivalent

    :param v0, v1: Version strings to test
    :return boolean:
    """
    return cmp_version(v0, v1) == 0

# ==========================================================================
# Repo management functions
# ==========================================================================

def manual_clone(repo_url, path):
    repo = git.Repo.init(path)

    # add both remotes.  Then we can ls-remote to find the release branches
    repo.create_remote("origin", repo_url)
    repo.create_remote("upstream", repo_urls['origin'])

    # Get the release branch list for both ose and origin
    ose_branches = branch_list(repo, 'origin', '*/enterprise-*')
    origin_branches = branch_list(repo, 'upstream', '*/release-*')

    #
    # We do need to get the master branch to compare if version == latest
    #
    
    logger.info("Fetching origin remote master branch")
    start = time.time()
    repo.remotes.origin.fetch("refs/heads/master:refs/remotes/origin/master")
    end = time.time()
    logger.info("Fetch complete in {} seconds".format(int(end - start)))
    repo.create_head('master', repo.remotes.origin.refs.master)
    repo.heads.master.set_tracking_branch(repo.remotes.origin.refs.master)
    repo.heads.master.checkout()

    return repo

#
# ============================================================================
#                       OCP build workspace setup
# ---------------------------------------------------------------------------
#               | master | rel branch  | upstream | auto version |  auto mode |
# ------------- | -----------------------------------------------------------
# release:      |    -   |       +     |    -     |      n       |     y      |
# ------------- | -----------------------------------------------------------
# pre-release:  |    +   |       +     |    +(?)  |      y       |     n      |
# ------------- | -----------------------------------------------------------
# stage:        |    ?   |       ?     |   -(?)   |      y[1]    |     n      |
# ------------- | -----------------------------------------------------------
# dev:          |    +   |       -     |    +     |      y       |     y      |
# ============================================================================
#
# [1] auto version stage cannot check if it's the RIGHT version
#
source_branches = {
    "release": {
        "on-master": False,
        "origin": "enterprise-VERSION",
        "upstream": None
    },

    "pre-release": {
        "on-master": True,
        "origin": "enterprise-VERSION",
        "upstream": "release-VERSION"
    },

    "online:stg": {
        "on-master": True,
        "origin": "stage",
        "upstream": "stage"
    },

    "online:int": {
        "on-master": True,
        "origin": "master",
        "upstream": "master"
    }
}


def select_branches(mode, ose_version, build_version):
    """
    The ose sources are a combination of the upstream OpenShift Origin
    git sources and the OpenShift Enterprise.

    Each build mode selects a different combination of the two using
    the master branch or named release branches
    """

    branch_spec = source_branches[mode]

    # check for valid mode and source version
    if branch_spec['on-master'] != eq_version(ose_version, build_version):
        # release builds can't be from the version on master HEAD
        # dev builds must be on master HEAD 
        raise ValueError(
            "Invalid build mode {}: ose_version: {},  build_version {}".
            format(mode, ose_version, build_version))

    origin_branch = string.replace(
        branch_spec['origin'], "VERSION", build_version)

    if branch_spec['upstream'] is None:
        upstream_branch = None
    else:
        upstream_branch = string.replace(
            branch_spec['upstream'], "VERSION", build_version)

    return (origin_branch, upstream_branch)

# ============================================================================
# Build mode logic
# ============================================================================
def get_auto_mode(build_version, master_version, releases):
    # Select auto-mode
    if eq_version(build_version, master_version):
        auto_mode = "online:int"
    elif build_version in releases:
        auto_mode = "release"
    
    return auto_mode

# ---------------------------------------------------------------------------
# Functions to update the version and release numbers
# ---------------------------------------------------------------------------

def next_release_stage(version, release):
    r_ints = release.split('.')
    r_ints[2] = str(int(r_ints[2]) + 1)
    return (version, '.'.join(r_ints))

def next_release_int(version, release):
    r_ints = release.split('.')
    r_ints[1] = str(int(r_ints[1]) + 1)
    r_ints[2] = '0'
    return (version, '.'.join(r_ints))

def next_version(version, release):
    v_ints = version.split('.')
    v_ints[-1] = str(int(v_ints[-1]) + 1)
    return ('.'.join(v_ints), "1")

next_version_release = {
    "online:int": next_release_int,
    "online:stg": next_release_stage,
    "release": next_version,
    "pre-release": next_version   
}


def git_enable_merge_ours_driver(repo, *args):
    """
    Enable the merge.ours driver for a set of file/dir patterns

    :param repo: A git.Repo object
    :*args: A list of patterns to enable the merge.ours driver on
    """
    repo.git.config("merge.ours.driver", "true")
    gitattr_path = repo.working_dir + "/.gitattributes"
    gitattr_file = open(gitattr_path, "a")
    for pattern in args:
        gitattr_file.write("{} merge=ours\n".format(pattern))
    gitattr_file.close()

def merge_upstream_branch(ose_repo, build_branch, upstream_branch_name):
    # got the master branch already
    # get the upstream branch reference
    upstream_refs = []
    for ref in ose_repo.remotes.upstream.refs:
        if ref.name.split('/')[-1] == upstream_branch_name:
            upstream_refs.append(ref)
    if len(upstream_refs) == 0:
        raise ValueError("Invalid merge: no upstream branch named {}".
                         format(upstream_branch_name))
    upstream_ref = upstream_refs[0]

    common_commit = ose_repo.merge_base(build_branch, upstream_ref)
    merge_index = ose_repo.index.merge_tree(upstream_ref, base=common_commit)
    ose_repo.index.commit(
        "Merge remote-tracking branch {}".format(upstream_branch_name),
        parent_commits=(build_branch.commit, upstream_ref.commit))

    build_branch.checkout(force=True)


def merge_master_branch(repo, branch_name):
    common_commit = repo.merge_base(repo.heads[branch_name], repo.heads.master)
    merge_index = repo.index.merge_tree(repo.heads.master, base=common_commit)
    repo.index.commit(
        "Merge branch {}".format('master'),
        parent_commits=(repo.heads[branch_name].commit, repo.heads.master.commit))

    repo.heads[branch_name].checkout(force=True)


# ============================================================================
#
# MAIN
#
# ============================================================================
if __name__ == "__main__":

    parser = prepare_args()
    opts = parser.parse_args()

    print(opts)

    logger = logging.getLogger()
    logger.setLevel(log_levels[string.upper(opts.loglevel)])

    #
    # Remove any existing build tree if required
    #
    if os.path.exists(opts.destination) and opts.clean:
        logger.info("deleting object(s) at {}".format(opts.destination))
        if os.path.isdir(opts.destination):
            shutil.rmtree(opts.destination)
        else:
            os.unlink(opts.destination)

    try:
        os.mkdir(opts.destination)
    except OSError as error:
        raise OSError("destination exists: {}\n  Pick a new destination or use --clean".format(opts.destination))

#    try:
#        os.mkdir(opts.destination + "go/src/github.com/openshift" + "/ose")
#    except OSError as error:
#        raise OSError("repo exists: {}\n  Pick a new repo or use --clean".format(opts.destination + "/ose"))

    # Save this a bit MAL 20180607
    #repo = manual_clone(repo_urls['ose'], opts.destination + "/ose")
    logger.info("Cloning ose repo: {}".format(repo_urls['ose']))
    start = time.time()
    repo = git.Repo.clone_from(
        repo_urls['ose'],
        opts.destination + "/go/src/github.com/openshift" + "/ose",
        branch='master',
        single_branch=True
    )
    end = time.time()
    logger.info("cloned ose in {} seconds: {}".format(int(end - start), repo.working_dir))

    repo.create_remote("upstream", repo_urls['origin'], no_tags=True)

    # Find the version/release strings on the master branch
    master = get_spec_version(repo.working_dir + "/origin.spec")

    if opts.version == 'latest':
        opts.version = version_major_minor(master['version'])
    #
    # Decide what build mode based on the version to build and the branch
    # versions
    #
    #p = "^enterprise-"
    #v = lambda s: version_major_minor(re.sub(p, '', s))
    ose_branches = branch_list(repo, 'origin', '*/enterprise-*')
    origin_branches = branch_list(repo, 'upstream', '*/release-*')

    releases = [version_major_minor(re.sub('^enterprise-', '', r)) for r in ose_branches]

    # **********************************************************************
    # At this point we have the version on master and the list of release
    # branches in both the ose and upstream repos.
    # We 
    # **********************************************************************

    sys.exit(0)
    
    if opts.mode == 'auto':
        # Get the list of previous release branches
        logger.debug("comparing versions: opts.version: {}, master_version: {}".
                     format(opts.version, master['version']))
        # Determine the build mode: building on master, master-1 or more?
        mode = get_auto_mode(opts.version, master['version'], releases)
        logger.debug("Auto-selected build mode: {}".format(mode))
    else:
        # Only certain modes are actually valid.  Mode generally has to do with
        # what branch is built and whether there's an upstream to merge
        mode = opts.mode

    # The release branch names for origin and enterprise are slightly
    # different
    # Determine the matching branch names for the desired release version
    (origin_branch_name, upstream_branch_name) = select_branches(
        mode, version_major_minor(master['version']), opts.version)
    logger.debug("origin branch: {}, upstream branch: {}".
                 format(origin_branch_name, upstream_branch_name))

    #
    # Check that the branches are available
    #
    if origin_branch_name not in ['master', 'stage'] + ose_branches:
        raise ValueError(
            "invalid origin branch: {}, not found in ose".
            format(origin_branch_name))

    if (upstream_branch_name and
        upstream_branch_name not in ['master', 'stage'] + origin_branches):
        raise ValueError(
            "invalid upstream branch: {}, not found in origin".
            format(upstream_branch_name))

    #
    # If the build branch is not master, add the remote ref and check it out
    #
    if origin_branch_name is not "master":
        logger.info("Fetching ose build branch: {}".format(origin_branch_name))
        start = time.time()
        repo.remotes.origin.fetch(
            "refs/heads/{}:refs/remotes/origin/{}".
            format(origin_branch_name, origin_branch_name)
        )
        end = time.time()
        logger.info("fetched branch in {} seconds: {}".
                    format(int(end - start), origin_branch_name))
        repo.create_head(
            origin_branch_name,
            repo.remotes.origin.refs[origin_branch_name])
        repo.heads[origin_branch_name].checkout()

    # Increment the right field of the version/release based on build mode
    build = get_spec_version(repo.working_dir + "/origin.spec")
    logger.debug("current version-release: {}-{}".
                 format(build['version'], build['release']))
    (new_version, new_release) = next_version_release[mode](
        build['version'], build['release'])
    logger.debug("new version-release: {}-{}".format(new_version, new_release))

    git_enable_merge_ours_driver(
        repo,
        "pkg/assets/bindata.go",
        "pkg/assets/java/bindata.go")

    # if this is pre-release, merge master into this branch
    if mode == "pre-release":
        logger.info("merging master")
        common_commit = repo.merge_base(
            repo.heads[origin_branch_name],
            repo.heads.master)
        merge_index = repo.index.merge_tree(
            repo.heads.master, base=common_commit)
        repo.index.commit(
            "Merge branch {}".format('master'),
            parent_commits=(
                repo.heads[origin_branch_name].commit,
                repo.heads.master.commit))

    repo.heads[origin_branch_name].checkout(force=True)
    
    # Prepare to merge upstream if set
    if upstream_branch_name:
        # add the remote reference
        logger.info("Fetching upstream branch: {}".format(upstream_branch_name))
        start = time.time()
        repo.remotes.upstream.fetch(
            "refs/heads/{}:refs/remotes/upstream/{}".
            format(upstream_branch_name, upstream_branch_name)
        )
        end = time.time()
        logger.info("fetched branch in {} seconds: {}".
                    format(int(end - start), upstream_branch_name))
        
        build_ref = repo.heads[origin_branch_name]
        upstream_ref = repo.remotes.upstream.refs[upstream_branch_name]
        # merge it into the build branch
        common_commit = repo.merge_base(build_ref, upstream_ref)
        merge_index = repo.index.merge_tree(upstream_ref, base=common_commit)
        repo.index.commit(
            "Merge remote-tracking branch {}".format(upstream_branch_name),
            parent_commits=(build_ref.commit, upstream_ref.commit))

        build_ref.checkout(force=True)
