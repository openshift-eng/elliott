# Stage the release candidate
# Once the release is ready, create a PR against
# https://github.com/openshift/cincinnati-graph-data/tree/master/channels
# to enter the candidate in Cincinnati.
# 4.1 candidates go in prerelease-4.1
# 4.2+ candidates go in candidate-4.2+
# Add the release in both in its own minor version and in the next one if available
# (this enables upgrade edges to next minor version).
# So 4.1 candidates should be added to prerelease-4.1 and candidate-4.2.
# If you know we are not releasing all arches of a release,
# be specific about the ones we are; for instance, you can add solely 4.2.42+x86_64
# Alert
# @architects and @over-the-air-updates in
# #forum-release so that they know the release is ready.
# They will debate the merits, merge the PR,
# and run a tool against it to add the release and edges in Cincinnati.
# Alert RCM (aka rhartman) to stage the release content for customer portal.
# Once everyone is happy, Docs and QE should take the advisories through the release process.

from __future__ import absolute_import, print_function, unicode_literals
import json

import elliottlib
from elliottlib import constants, logutil, Runtime
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import exit_unauthenticated, ensure_erratatool_auth
from elliottlib.util import green_prefix, green_print, red_print
from elliottlib import exectools
from elliottlib import gitdata
from errata_tool import Erratum, ErrataException
from kerberos import GSSError
import requests
import click
import pygit2
import os
import random
import string
import ruamel.yaml
from github import Github

LOGGER = logutil.getLogger(__name__)

pass_runtime = click.make_pass_decorator(Runtime)

#
# Create Release Candidate PR which reqeust an edge on Cincinnati Graph
# request-edge
#
@cli.command('request-edge',
             short_help='Stage the release candidate by creating a github PR to Cincinnati Graph edge')
@click.option('--candidate-version', required=True, help='the release candidate version')
@click.option('--next-version', default=None, help='the release candidate version\'s next minor version if exist')
@click.option('--github-org', default="openshift", help='the github org where we clone and creating pull request')
@click.option('--github-repo', default="cincinnati-graph-data", help='the github repo where we clone and push and creating pull request')
@click.option("--out-dir", type=click.Path(), default="./cincinnati-graph-data", help="Output directory for tarball sources.")
@click.option("--github-access-token", type=click.Path(), required=True, help="github access token for github actions (pull request).")
@pass_runtime
def request_edge_cli(runtime, candidate_version, next_version, github_org, github_repo, out_dir, github_access_token):
    """Create a github pull request on Cincinnati Graph for candidate release.
    """

    if next_version is None:
        next_version = "{}+amd64".format(candidate_version)

    cvr = candidate_version.replace('-', '.').split('.')
    g = Github(github_access_token)
    repo = g.get_organization(github_org).get_repo(github_repo)

    # git clone
    exectools.cmd_assert('git clone {} {}'.format(repo.ssh_url, out_dir))
    LOGGER.info("Clone repo {} succeed....".format(repo.ssh_url))
    for counter in range(1, 3):
        exectools.cmd_assert('git -C {} checkout -b master')
        branch = 'candidate-{}-{}-'.format(counter, candidate_version) + ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        exectools.cmd_assert('git -C {} checkout -b {}'.format(out_dir, branch))
        _modify_cincinnati_graph(out_dir, candidate_version, next_version, (cvr[0], cvr[1], cvr[2]), counter)
        LOGGER.info("Modify Cincinnati graph locally succeed....")
        exectools.cmd_assert('git -C {} add -A'.format(out_dir))
        # git commit
        exectools.cmd_assert('git -C {} commit -m "elliott: creating candidate release {}"'.format(out_dir, candidate_version))
        LOGGER.info("Create git commit succeed....")
        # git push
        exectools.cmd_assert('git -C {} push origin HEAD'.format(out_dir))
        LOGGER.info("Git push succeed....")
        # create github pull request
        body = '''
        This is release candidate PR open atomatically by elliott
        '''
        pr = repo.create_pull(title="Candidate-{}".format(candidate_version), body=body, head='{}:{}'.format(github_org, branch), base="master")
        LOGGER.info("Open PR:{} on Github succeed....".format(pr))
    # remove cincinnati repo
    exectools.cmd_assert('rm -rf {}'.format(out_dir))


def _modify_cincinnati_graph(out_dir, candidate_version, next_version, version_tuple, modify_counter):
    targetdir = out_dir + '/channels/'
    if version_tuple[0] == '4' and version_tuple[1] == '1':
        if modify_counter == 1:
            targetfile = targetdir + 'prerelease-4.1.yaml'
            _write_yaml_file(targetfile, version=candidate_version)

        if modify_counter == 2:
            # Add the release in both in its own minor version and in the next
            # one if available this enables upgrade edges to next minor version.
            next_targetfile = targetdir + 'candidate-4.2.yaml'
            if os.path.exists(next_targetfile) and os.path.isfile(next_targetfile):
                _write_yaml_file(next_targetfile, version=next_version)

    else:   # 4.1+
        if modify_counter == 1:
            targetfile = targetdir + 'candidate-{}.yaml'.format(version_tuple[0] + '.' + version_tuple[1])
            _write_yaml_file(targetfile, version=candidate_version)

        if modify_counter == 2:
            # Add the release in both in its own minor version and in the next
            # one if available this enables upgrade edges to next minor version.
            next_targetfile = targetdir + 'candidate-{}.yaml'.format(version_tuple[0] + '.' + str(int(version_tuple[1]) + 1))
            if os.path.exists(next_targetfile):
                _write_yaml_file(next_targetfile, version=next_version)


def _write_yaml_file(target, version):
    with open(target) as f:
        ryaml = ruamel.yaml.YAML()  # defaults to round-trip if no parameters given
        data = ryaml.load(f)
    for v in data['versions']:
        if v == version:
            red_print("Release candidate already exist in cincinnati-graph-data/channels/{}.".format(target))
            exit(1)
    data['versions'].append(version)
    with open(target, "w") as f:
        ryaml.dump(data, f)
