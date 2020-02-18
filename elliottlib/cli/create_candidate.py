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
# They will debate the merits, 
# merge the PR, 
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
from elliottlib.util import green_prefix, green_print, parallel_results_with_progress, pbar_header

from errata_tool import Erratum, ErrataException
from kerberos import GSSError
import requests
import click
import pygit2
from github import Github

LOGGER = logutil.getLogger(__name__)

pass_runtime = click.make_pass_decorator(Runtime)

#
# Create Release Candidate PR
# create-candidate
#
@cli.command('create-candidate',
             short_help='Stage the release candidate by creating a github PR to Cincinnati Graph')
@click.option('--candidate-version', required=True, help='the release candidate version')
@pass_runtime
def create_candidate_cli(runtime, candidate_version):
    """Create a github pull request on Cincinnati Graph for candidate release.
    """
    g = Github("76b5dfd0e2dcd9eece4fe212a4efc49a1e491805")
    repo = g.get_organization("openshift").get_repo("elliott")
    print(repo.get_pull(1))

    body = '''
    This is just a test
    '''
    pr = repo.create_pull(title="Candidate-{}".format(candidate_version), body=body, 
    head='{}:{}'.format('shiywang', 'master'), base="master")

    print(pr)    