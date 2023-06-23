import click
import requests
import re
import os
import koji
from string import Template
from ruamel.yaml import YAML

from elliottlib import (Runtime, logutil, exectools)
from elliottlib.cli.common import cli
from elliottlib.cli.find_bugs_sweep_cli import FindBugsMode
from elliottlib.util import green_prefix

yaml = YAML(typ="safe")
logger = logutil.getLogger(__name__)


class FindBugsQE(FindBugsMode):
    def __init__(self):
        super().__init__(
            status={'MODIFIED', 'ON_QA'},
            cve_only=False,
        )


@cli.command("find-bugs:qe", short_help="Fetch MODIFIED bugs, find which ones got fixed and move them to ON_QA")
@click.option("--noop", "--dry-run",
              is_flag=True,
              default=False,
              help="Don't change anything")
@click.pass_obj
def find_bugs_qe_cli(runtime: Runtime, noop):
    """Fetch MODIFIED bugs for the target-releases,
    find out which ones got fixed via associated PRs and set them to ON_QA.
    with a release comment and associated build (if available) on each bug

\b
    $ elliott -g openshift-4.6 find-bugs:qe

"""
    runtime.initialize()
    find_bugs_obj = FindBugsQE()
    find_bugs_qe(runtime, find_bugs_obj, noop, runtime.bug_trackers('jira'))

def find_bugs_qe(runtime, find_bugs_obj, noop, bug_tracker):
    major_version, minor_version = runtime.get_major_minor()
    statuses = sorted(find_bugs_obj.status)
    tr = bug_tracker.target_release()
    green_prefix(f"Searching {bug_tracker.type} for bugs with status {statuses} and target releases: {tr}\n")

    bugs = find_bugs_obj.search(bug_tracker_obj=bug_tracker, verbose=runtime.debug)
    click.echo(f"Found {len(bugs)} bugs: {', '.join(sorted(str(b.id) for b in bugs))}")

    art_managed_repos = github_distgit_mappings(f'{major_version}.{minor_version}').keys()
    for bug in bugs:
        links = bug_tracker.get_bug_remote_links(bug.id)
        prs = []
        for link in links:
            url = link.raw['object']['url']
            if not 'github.com/openshift/' in url:
                continue

            match = re.search("github.com/openshift/(?P<repo>[a-zA-Z0-9-]+)/pull/(?P<pr_id>\d+)", url)
            repo, pr_id = match.group('repo'), match.group('pr_id')
            if repo not in art_managed_repos:
                continue

            print(f'{bug.id} - pr found! {url} and we build it!!')
            build = None
            try:
                build = PrInfo(repo, pr_id, f'{major_version}.{minor_version}', None, None).run()
            except Exception as e:
                logger.error(e)
                continue
            print(f'build for pr found - {build}')
            prs.append((url, build))

    release_comment = (
        "An ART build cycle completed after this fix was made, which usually means it can be"
        f" expected in the next created {major_version}.{minor_version} nightly and release.")
    for bug in bugs:
        updated = bug_tracker.update_bug_status(bug, 'ON_QA', comment=release_comment, noop=noop)
        if updated and bug.is_tracker_bug():
            # leave a special comment for QE
            comment = """Note for QE:
This is a CVE bug. Please plan on verifying this bug ASAP.
A CVE bug shouldn't be dropped from an advisory if QE doesn't have enough time to verify.
Contact ProdSec if you have questions.
"""
            bug_tracker.add_comment(bug.id, comment, private=True, noop=noop)

RC_ARCH_TO_RHCOS_ARCH = {
    'amd64': 'x86_64',
    'arm64': 'aarch64',
    'ppc64le': 'ppc64le',
    's390x': 's390x'
}
RELEASE_CONTROLLER_URL = Template('https://${arch}.ocp.releases.ci.openshift.org')
GITHUB_API_OPENSHIFT = "https://api.github.com/repos/openshift"
ART_DASH_API_ROUTE = "https://art-dash-server-art-dashboard-server.apps.artc2023.pc3z.p1.openshiftapps.com/api/v1"
BREW_TASK_STATES = {
    "Success": "success",
    "Failure": "failure"
}
BREW_URL = 'https://brewweb.engineering.redhat.com/brew'

mappings_by_version = {}

def github_distgit_mappings(version: str) -> dict:
    """
    Function to get the GitHub to Distgit mappings present in a particular OCP version.
    :version: OCP version
    """
    global mappings_by_version
    if version in mappings_by_version:
        return mappings_by_version[version]

    rc, out, err = exectools.cmd_gather(
        f"doozer --disable-gssapi -g openshift-{version} --assembly stream images:print --short '{{"
        f"upstream_public}}: {{name}}'")

    if rc != 0:
        if "koji.GSSAPIAuthError" in err:
            msg = "Kerberos authentication failed for doozer"
            logger.error(msg)
            raise RuntimeError(msg)

        logger.error('Doozer returned status %s: %s', rc, err)
        raise RuntimeError(f'doozer returned status {rc}')

    mappings = {}

    for line in out.splitlines():
        github, distgit = line.split(": ")
        reponame = github.split("/")[-1]
        if github not in mappings:
            mappings[reponame] = [distgit]
        else:
            mappings[reponame].append(distgit)

    if not mappings:
        logger.warning('No github-distgit mapping found in %s', version)
        raise RuntimeError("No data from doozer command for github-distgit mapping")
    mappings_by_version[version] = mappings
    return mappings


class PrInfo:
    def __init__(self, repo_name, pr_id, version, arch, component):
        self.repo_name = repo_name
        self.pr_id = pr_id
        self.pr_url = f'https://github.com/openshift/{repo_name}/pull/{pr_id}'

        self.version = version
        self.arch = arch if arch else 'amd64'
        self.component = component

        self.merge_commit = None
        self.distgit = None
        self.post_merge_commits = None
        self.koji_api = koji.ClientSession('https://brewhub.engineering.redhat.com/brewhub')
        self.header = {"Authorization": f"token {os.environ['GITHUB_PERSONAL_ACCESS_TOKEN']}"}

    def get_distgit(self):
        mappings = github_distgit_mappings(self.version)
        if self.repo_name not in mappings:
            print(f'Unable to find the distgit repo associated with `{self.repo_name}`: '
                        f'please check the query and try again')
            return None
        repo_mappings = mappings[self.repo_name]


        # Multiple components build from the same upstream
        if len(repo_mappings) > 1:
            # The user must explicitly provide the component name
            if not self.component:
                print(f'Multiple components build from `{self.repo_name}`: '
                            f'please specify the one you\'re interested in and try again')
                return None

            # Does the component exist?
            if self.component not in repo_mappings:
                print(f'No distgit named `{self.component}` has been found: '
                            f'please check the query and try again')
                return None
            return self.component

        # No ambiguity: return the one and only mapped distgit
        mapping = repo_mappings[0]
        return mapping

    def get_commit_time(self, commit) -> str:
        """
        Return the timestamp associated with a commit: e.g. "2022-10-21T19:48:29Z"
        """

        url = f"{GITHUB_API_OPENSHIFT}/{self.repo_name}/commits/{commit}"
        response = requests.get(url, headers=self.header)
        json_data = response.json()
        commit_time = json_data['commit']['committer']['date']
        return commit_time

    def get_commits_after(self, commit) -> list:
        """
        Return commits in a repo from the given time (includes the current commit).
        """

        datetime = self.get_commit_time(commit)
        url = f"{GITHUB_API_OPENSHIFT}/{self.repo_name}/commits?sha=release-{self.version}&since={datetime}"
        commits = github_api_all(url)
        result = []
        for data in commits:
            result.append(data['sha'])
        return result[::-1]

    def pr_merge_commit(self):
        """
        Return the merge commit SHA associated with a PR
        """

        url = f"{GITHUB_API_OPENSHIFT}/{self.repo_name}/pulls/{self.pr_id}"
        response = requests.get(url, headers=self.header)
        json_data = response.json()
        sha = json_data["merge_commit_sha"]
        return sha

    def get_builds_from_db(self, commit, task_state):
        """
        Function to find the build using commit, from API, which queries the database.
        """

        params = {
            "group": f"openshift-{self.version}",
            "label_io_openshift_build_commit_id": commit,
            "brew_task_state": task_state
        }
        url = f"{ART_DASH_API_ROUTE}/builds/"
        response = requests.get(url, params=params)
        if response.status_code != 200:
            msg = f'Request to {url} returned with status code {response.status_code}'
            logger.error(msg)
            raise RuntimeError(msg)

        return response.json()

    def find_first_build(self):
        # Look for first successful builds in post merge commits
        build_id = None
        for commit in self.post_merge_commits:
            response_data = self.get_builds_from_db(commit, BREW_TASK_STATES["Success"])
            count = response_data.get("count", 0)
            if response_data and count > 0:
                builds = response_data["results"]
                build_id = sorted([x["build_0_id"] for x in builds])[0]
                break

        if not build_id:
            logger.info("No successful builds found for given PR")
            return None
        nvr = self.koji_api.getBuild(build_id)['nvr']
        return nvr, f'{BREW_URL}/buildinfo?buildID={build_id}'

    def run(self):
        self.distgit = self.get_distgit()
        self.merge_commit = self.pr_merge_commit()
        self.post_merge_commits = self.get_commits_after(self.merge_commit)
        if self.merge_commit not in self.post_merge_commits:
            logger.info(f"release-{self.version} branch does not include this PR")
            return False

        return self.find_first_build()

def github_api_all(url: str):
    """
    GitHub API paginates results. This function goes through all the pages and returns everything.
    This function is used only for GitHub API endpoints that return a list as response. The endpoints that return
    json are usually not paginated.
    """
    params = {'per_page': 100, 'page': 1}
    header = {"Authorization": f"token {os.environ['GITHUB_PERSONAL_ACCESS_TOKEN']}"}
    num_requests = 1  # Guard against infinite loop
    max_requests = 100

    response = requests.get(url, params=params, headers=header)
    results = response.json()

    while "next" in response.links.keys() and num_requests <= max_requests:
        url = response.links['next']['url']
        response = requests.get(url, headers=header)

        if response.status_code != 200:
            logger.error('Could not fetch data from %s', url)

        results += response.json()
        num_requests += 1
    return results
