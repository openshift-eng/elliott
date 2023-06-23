import click
import requests
import re
from ruamel.yaml import YAML

from elliottlib import (Runtime, logutil, exectools)
from elliottlib.cli.common import cli
from elliottlib.cli.find_bugs_sweep_cli import FindBugsMode
from elliottlib.util import green_prefix

yaml = YAML(typ="safe")
LOGGER = logutil.getLogger(__name__)


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

    product_yml_url = 'https://github.com/openshift-eng/ocp-build-data/raw/main/product.yml'
    response = requests.get(product_yml_url)
    response.raise_for_status()
    brew_to_jira_mapping = yaml.load(response.content)["bug_mapping"]["components"]
    jira_to_brew_mapping = {}
    for brew_component in brew_to_jira_mapping.keys():
        jira_component = brew_to_jira_mapping[brew_component]['issue_component']
        if jira_component in jira_to_brew_mapping:
            jira_to_brew_mapping[jira_component].append(brew_component)
        else:
            jira_to_brew_mapping[jira_component] = [brew_component]

    cmd = [
        "doozer",
        "-g",
        "openshift-4.12",
        "--assembly",
        "stream",
        "images:print",
        "--short",
        "{name},{jira_component},{upstream_public}"
    ]
    _, stdout, _ = exectools.cmd_gather(cmd)
    art_managed_repos = set()
    jira_to_brew_mapping_doozer = {}
    for line in stdout.split('\n'):
        k = line.split(',')
        if len(k) != 3:
            continue
        name, jira_component, upstream_public = k
        match = re.search("github.com/openshift/(?P<repo>[a-zA-Z0-9-]+)", upstream_public)
        if not match:
            continue
        repo = match.group('repo')
        art_managed_repos.add(repo)
        if jira_component not in jira_to_brew_mapping_doozer:
            jira_to_brew_mapping_doozer[jira_component] = []
        jira_to_brew_mapping_doozer[jira_component].append(name)

    for bug in bugs:
        links = bug_tracker.get_bug_remote_links(bug.id)
        prs = []
        for link in links:
            url = link.raw['object']['url']
            if not 'github.com/openshift/' in url:
                continue

            match = re.search("github.com/openshift/(?P<repo>[a-zA-Z0-9-]+)/pull/(?P<pr_id>\d+)", url)
            repo, pr_id = match.group('repo'), match.group('pr_id')
            if repo in art_managed_repos:
                print(f'{bug.id} - pr found! {url} and we build it!!')
                prs.append(url)
        if not prs:
            continue
        component = bug.bug.fields.components[0].name
        print(bug.id, component)
        print(f'associated brew (product.yml): {jira_to_brew_mapping.get(component, [])}')
        print(f'associated brew (doozer): {jira_to_brew_mapping_doozer.get(component, [])}')

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
