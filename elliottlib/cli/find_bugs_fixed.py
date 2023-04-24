import json
import click
import requests
import re
import os
from string import Template
from elliottlib import (Runtime, logutil)
from elliottlib.cli import common
from elliottlib.cli.find_bugs_sweep_cli import FindBugsSweep
from elliottlib import exectools

logger = logutil.getLogger(__name__)


@common.cli.command("find-bugs:shipped", short_help="Find ART managed jira bugs that are open but have shipped")
@click.pass_obj
@common.click_coroutine
async def find_bugs_fixed_cli(runtime: Runtime):
    """Find ART managed jira bugs that are open but have shipped
    Only to be used with --assembly=stream

    $ elliott -g openshift-4.12 find-bugs:shipped

    """
    if runtime.assembly != 'stream':
        raise click.BadParameter("This command is intended to work only with --assembly=stream",
                                 param_hint='--assembly')

    runtime.initialize()
    major, minor = runtime.get_major_minor()
    find_bugs_obj = FindBugsSweep()
    bug_tracker = runtime.bug_trackers('jira')

    bugs = find_bugs_obj.search(bug_tracker_obj=bug_tracker, verbose=runtime.debug)
    tracker_bugs = [b for b in bugs if b.is_cve_in_summary()]
    for b in tracker_bugs:
        links = bug_tracker.get_bug_remote_links(b.id)

        for link in links:
            url = link.raw['object']['url']
            if not 'github.com/openshift/' in url:
                continue

            match = re.search("github.com/openshift/(?P<repo>[a-zA-Z0-9-]+)/pull/(?P<pr_id>\d+)", url)
            repo, pr_id = match.group('repo'), match.group('pr_id')
            earliest_release = None
            try:
                earliest_release = await PrInfo(repo, pr_id, f'{major}.{minor}', None, None).run()
            except Exception as e:
                print(f'Error: {e}')
                continue
            if earliest_release != '4.12.14':
                print(f'Bug PR#{pr_id} {b.id}({b.status}) {b.summary} -- shipped in {earliest_release}')

    # report = {}
    # actionable_bugs = {}
    # for b in look_like_trackers:
    #     # "CVE-2022-23525 CVE-2022-23526 special-resource-operator-container: various flaws [openshift-4]"
    #     # so we want to match CVE-2022-23525, CVE-2022-23526 into a list
    #     # and get special-resource-operator-container as the component
    #
    #     match = re.search(r'((?:CVE-\d+-\d+ )+)((?:\w+-?)+):', b.summary)
    #     component = match.group(2)
    #     cve_list = [c.strip() for c in match.group(1).split()]
    #
    #     cve_url = "https://access.redhat.com/hydra/rest/securitydata/cve/{cve_name}.json"
    #
    #     flaw_ids = []
    #     for cve in cve_list:
    #         url = cve_url.format(cve_name=cve)
    #         response = requests.get(url)
    #         response.raise_for_status()
    #         flaw_id = response.json()['bugzilla']['id']
    #         flaw_ids.append(int(flaw_id))
    #
    #     issues = []
    #     labels = []
    #     if not b.is_tracker_bug():
    #         issues.append(f"Missing tracker labels.")
    #     if not b.whiteboard_component:
    #         issues.append(f"Missing component label.")
    #         labels.append(f"pscomponent:{component}")
    #     if not b.corresponding_flaw_bug_ids:
    #         issues.append(f"Missing flaw bug label.")
    #         labels.extend([f"flaw:bz#{i}" for i in flaw_ids])
    #     elif not set(flaw_ids).issubset(set(b.corresponding_flaw_bug_ids)):
    #         issues.append(f"Flaw bug labels not found. Expected: {flaw_ids} to be in {b.corresponding_flaw_bug_ids}.")
    #
    #     if issues:
    #         report[b.id] = {'issues': ' '.join(issues), 'labels': labels}
    #         actionable_bugs[b.id] = b
    #
    # click.echo(f'Found {len(report)} bugs that are invalid')
    # click.echo(json.dumps(report, indent=4))
    #
    # if not fix:
    #     return
    #
    # for bug_id, data in report.items():
    #     labels = data['labels']
    #     if labels:
    #         bug = actionable_bugs[bug_id]
    #         click.echo(f'{bug.id}({bug.status}) - {bug.summary}')
    #         if click.confirm(f"Add labels {labels} to bug {bug_id}?"):
    #             bug = actionable_bugs[bug_id]
    #             bug.bug.fields.labels.extend(labels)
    #             bug.bug.update(fields={"labels": bug.bug.fields.labels})
    #             click.echo(f"Added labels")


    # bugs = find_bugs_obj.search(bug_tracker_obj=bug_tracker, verbose=runtime.debug,
    #                             with_target_release=False, custom_query=' AND "Target Version" is EMPTY AND '
    #                                                                     'component != "Release"')
    #click.echo(f'Found {len(bugs)} bugs with status={find_bugs_obj.status} and no Target Version set')

RC_ARCH_TO_RHCOS_ARCH = {
    'amd64': 'x86_64',
    'arm64': 'aarch64',
    'ppc64le': 'ppc64le',
    's390x': 's390x'
}

RELEASE_CONTROLLER_URL = Template('https://${arch}.ocp.releases.ci.openshift.org')
GITHUB_API_OPENSHIFT = "https://api.github.com/repos/openshift"

def github_distgit_mappings(version: str) -> dict:
    """
    Function to get the GitHub to Distgit mappings present in a particular OCP version.

    :version: OCP version
    """

    rc, out, err = exectools.cmd_gather(
        f"doozer --disable-gssapi -g openshift-{version} --assembly stream images:print --short '{{upstream_public}}: {{name}}'")

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
    return mappings

def get_image_stream_tag(distgit_name: str, version: str):
    """
    Function to get the image stream tag if the image is a payload image.
    The for_payload flag would be set to True in the yml file

    :distgit_name: Name of the distgit repo
    :version: OCP version
    """

    url = f"https://raw.githubusercontent.com/openshift/ocp-build-data/openshift-{version}/images/{distgit_name}.yml"
    response = requests.get(url)

    import yaml
    yml_file = yaml.safe_load(response.content)

    # Check if the image is in the payload
    if yml_file.get('for_payload', False):
        tag = yml_file['name'].split("/")[1]
        result = tag[4:] if tag.startswith("ose-") else tag  # remove 'ose-' if present
        return result

    # The image is not in the payload
    logger.info('Component %s does not belong to the OCP payload', distgit_name)
    return None

RELEASES = None

class PrInfo:
    def __init__(self, repo_name, pr_id, version, arch, component):
        self.repo_name = repo_name
        self.pr_id = pr_id
        self.pr_url = f'https://github.com/openshift/{repo_name}/pull/{pr_id}'

        self.version = version
        self.arch = arch if arch else 'amd64'
        self.component = component
        self.valid_arches = RC_ARCH_TO_RHCOS_ARCH.keys()
        self.releasestream_api_endpoint = \
            f'{RELEASE_CONTROLLER_URL.substitute(arch=self.arch)}/api/v1/releasestream'

        self.merge_commit = None
        self.distgit = None
        self.imagestream_tag = None
        self.commits = None
        self.header = {"Authorization": f"token {os.environ['GITHUB_PERSONAL_ACCESS_TOKEN']}"}

    def get_distgit(self):
        try:
            mappings = github_distgit_mappings(self.version)
        except Exception as e:
            print('Exception raised while getting github/distgit mappings: %s', e)
            print(f'Could not retrieve distgit name for {self.repo_name}')
            return None

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

    def get_imagestream_tag(self):
        """
        Return the component image name in the payload
        """

        imagestream_tag = get_image_stream_tag(self.distgit, self.version)
        if not imagestream_tag:
            print('Image for %s is not part of the payload', self.repo_name)
        return imagestream_tag

    def get_releases(self):
        global RELEASES
        if RELEASES:
            return RELEASES
        """
        Fetch stable {major}.{minor} versions from RC;
        return an iterable object where each element is a dict as such:

        {
            'name': '4.11.8',
            'phase': 'Accepted',
            'pullSpec': 'quay.io/openshift-release-dev/ocp-release:4.11.8-x86_64',
            'downloadURL': 'https://openshift-release-artifacts.apps.ci.l2s4.p1.openshiftapps.com/4.11.8'
        }

        The versions will be ordered from the most recent one to the oldest one
        """

        major, minor = self.version.split('.')

        if self.arch == 'amd64':
            release_endpoint = f'{self.releasestream_api_endpoint}/{major}-stable/tags'
        else:
            release_endpoint = f'{self.releasestream_api_endpoint}/{major}-stable-{self.arch}/tags'

        response = requests.get(release_endpoint)
        if response.status_code != 200:
            msg = f'OCP{major} not available on RC'
            print(msg)
            return []

        data = response.json()
        pattern = re.compile(rf'{major}\.{minor}\.[0-9]+.*$')
        releases = [r for r in filter(lambda x: re.match(pattern, x['name']), data['tags'])]
        RELEASES = releases
        return releases

    async def check_in_releases(self, releases) -> str:
        """
        Check if the PR has made it into release.
        Report the earliest one that has it, or if there are none
        """

        earliest = None

        for release in releases:
            cmd = f'oc adm release info {release["pullSpec"]} --image-for {self.imagestream_tag}'
            _, stdout, _ = await exectools.cmd_gather_async(cmd)

            cmd = f'oc image info -o json {stdout}'
            _, stdout, _ = await exectools.cmd_gather_async(cmd)
            labels = json.loads(stdout)['config']['config']['Labels']
            commit_id = labels['io.openshift.build.commit.id']

            if commit_id in self.commits:
                earliest = release
            else:
                break

        return earliest

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

    async def run(self):
        self.distgit = self.get_distgit()

        # Get merge commit associated to the PPR
        self.merge_commit = self.pr_merge_commit()
        # Get the commits that we need to check
        self.commits = self.get_commits_after(self.merge_commit)
        if self.merge_commit not in self.commits:
            print("This branch doesn't have this PR merge commit")
            print(f"release-{self.version} branch does not include this PR")
            return False


        # Check into nightlies and releases
        self.imagestream_tag = self.get_imagestream_tag()
        if self.imagestream_tag:
            earliest_release = await self.check_in_releases(self.get_releases())
            if earliest_release:
                return earliest_release["name"]
            return False

        raise RuntimeError(f'Couldn\'t get image stream tag for `{self.repo_name}` in `{self.version}`: '
                        f'will not look into nightlies nor releases...')

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
