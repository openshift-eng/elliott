import re
import sys
from typing import Dict, List, Optional, Sequence, TextIO, Tuple, cast

import click
import koji
from jira import JIRA, Issue
from tenacity import retry, stop_after_attempt, wait_fixed

from elliottlib import Runtime, brew
from elliottlib.assembly import AssemblyTypes
from elliottlib.cli.common import cli, click_coroutine
from elliottlib.config_model import KernelBugSweepConfig
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import green_print
from elliottlib.bzutil import JIRABugTracker


class FindBugsKernelClonesCli:
    def __init__(self, runtime: Runtime, trackers: Sequence[str], issues: Sequence[str],
                 move: bool, comment: bool, dry_run: bool):
        self._runtime = runtime
        self._logger = runtime.logger
        self.trackers = list(trackers)
        self.issues = list(issues)
        self.move = move
        self.comment = comment
        self.dry_run = dry_run

    async def run(self):
        logger = self._logger
        if self.comment and not self.move:
            raise ElliottFatalError("--comment must be used with --move")
        if self._runtime.assembly_type is not AssemblyTypes.STREAM:
            raise ElliottFatalError("This command only supports stream assembly.")
        group_config = self._runtime.group_config
        raw_config = self._runtime.gitdata.load_data(key='bug', replace_vars=group_config.vars).data.get("kernel_bug_sweep")
        if not raw_config:
            logger.warning("kernel_bug_sweep is not defined in bug.yml")
            return
        config = KernelBugSweepConfig.parse_obj(raw_config)
        jira_tracker = self._runtime.bug_trackers("jira")
        jira_client: JIRA = jira_tracker._client
        koji_api = self._runtime.build_retrying_koji_client(caching=True)

        # Search for Jiras
        report = {"jira_issues": []}
        if self.issues:
            logger.info("Getting specified Jira issues %s...", self.issues)
            found_issues = self._get_jira_issues(jira_client, self.issues, config)
        else:
            logger.info("Searching for bug clones in Jira project %s...", config.target_jira.project)
            found_issues = self._search_for_jira_issues(jira_client, self.trackers, config)
        issue_keys = [issue.key for issue in found_issues]
        logger.info("Found %s Jira(s) in %s: %s", len(issue_keys), config.target_jira.project, issue_keys)

        # Update JIRA issues
        if self.move and found_issues:
            logger.info("Moving bug clones...")
            self._update_jira_issues(jira_client, found_issues, koji_api, config)
            logger.info("Done.")

        # Print a report
        report["jira_issues"] = [{
            "key": issue.key,
            "summary": issue.fields.summary,
            "status": str(issue.fields.status.name),
        } for issue in found_issues]
        self._print_report(report, sys.stdout)

    def _get_jira_issues(self, jira_client: JIRA, issue_keys: List[str], config: KernelBugSweepConfig):
        found_issues: List[Issue] = []
        labels = {"art:cloned-kernel-bug"}
        for key in issue_keys:
            issue = jira_client.issue(key)
            if not labels.issubset(set(issue.fields.labels)):
                raise ValueError(f"Jira {key} doesn't have all required labels {labels}")
            if issue.fields.project.key != config.target_jira.project:
                raise ValueError(f"Jira {key} doesn't belong to project {config.target_jira.project}")
            components = {c.name for c in issue.fields.components}
            if config.target_jira.component not in components:
                raise ValueError(f"Jira {key} is not set to component {config.target_jira.component}")
            target_versions = getattr(issue.fields, JIRABugTracker.FIELD_TARGET_VERSION)
            target_releases = {t.name for t in target_versions}
            if config.target_jira.target_release not in target_releases:
                raise ValueError(f"Jira {key} has invalid target version: {target_versions}")
            found_issues.append(issue)
        return found_issues

    @staticmethod
    @retry(reraise=True, stop=stop_after_attempt(10), wait=wait_fixed(30))
    def _search_for_jira_issues(jira_client: JIRA, trackers: Optional[List[str]],
                                config: KernelBugSweepConfig):
        conditions = [
            "labels = art:cloned-kernel-bug",
            f"project = {config.target_jira.project}",
            f"component = {config.target_jira.component}",
            f"\"Target Version\" = \"{config.target_jira.target_release}\"",
        ]
        if trackers:
            condition = ' OR '.join(map(lambda t: f"labels = art:kmaint:{t}", trackers))
            conditions.append(f"({condition})")
        jql_str = f'{" AND ".join(conditions)} order by created DESC'
        found_issues = jira_client.search_issues(jql_str, maxResults=0)
        return cast(List[Issue], found_issues)

    def _update_jira_issues(self, jira_client: JIRA,
                            issues: List[Issue],
                            koji_api: koji.ClientSession,
                            config: KernelBugSweepConfig):
        logger = self._runtime.logger
        candidate_brew_tag = config.target_jira.candidate_brew_tag
        prod_brew_tag = config.target_jira.prod_brew_tag
        trackers: Dict[str, Issue] = {}
        tracker_issues: Dict[str, List[Issue]] = {}
        issue_bug_ids: Dict[str, int] = {}
        for issue in issues:
            # extract bug id from labels: ["art:bz#12345"] -> 12345
            bug_id = next(map(lambda m: int(m[1]), filter(bool, map(lambda label: re.fullmatch(r"art:bz#(\d+)", label), issue.fields.labels))), None)
            if not bug_id:
                raise ValueError(f"Jira clone {issue.key} doesn't have the required `art:bz#N` label")
            issue_bug_ids[issue.key] = bug_id
            # extract KMAINT tracker key from labels: ["art:kmaint:KMAINT-1"] -> KMAINT-1
            tracker_key = next(map(lambda m: str(m[1]), filter(bool, map(lambda label: re.fullmatch(r"art:kmaint:(\S+)", label), issue.fields.labels))), None)
            if not tracker_key:
                raise ValueError(f"Jira clone {issue.key} doesn't have the required `art:kmaint:*` label")
            tracker = trackers.get(tracker_key)
            if not tracker:
                tracker = trackers[tracker_key] = jira_client.issue(tracker_key)
                if tracker.fields.project.key != config.tracker_jira.project:
                    raise ValueError(f"KMAINT tracker {tracker_key} is not in project {config.tracker_jira.project}")
                if not set(config.tracker_jira.labels).issubset(set(tracker.fields.labels)):
                    raise ValueError(f"KMAINT tracker {tracker_key} doesn't have required labels {config.tracker_jira.labels}")
            tracker_issues.setdefault(tracker.key, []).append(issue)

        for tracker_id, tracker in trackers.items():
            # Determine which NVRs have the fix. e.g. ["kernel-5.14.0-284.14.1.el9_2"]
            nvrs = re.findall(r"(kernel(?:-rt)?-\S+-\S+)", tracker.fields.summary)
            if not nvrs:
                raise ValueError("Couldn't determine build NVRs for bug %s. Bug status will not be moved.", bug_id)
            nvrs = sorted(nvrs)
            issues = tracker_issues[tracker_id]
            issue_keys = [issue.key for issue in issues]
            # Check if nvrs are already tagged into OCP
            logger.info("Getting Brew tags for build(s) %s...", nvrs)
            build_tags = brew.get_builds_tags(nvrs, koji_api)
            shipped = all([any(map(lambda t: t["name"] == prod_brew_tag, tags)) for tags in build_tags])
            tracker_message = None
            if shipped:
                logger.info("Build(s) %s shipped (tagged into %s). Moving Jira(s) %s to CLOSED...", nvrs, prod_brew_tag, issue_keys)
                for issue in issues:
                    current_status: str = issue.fields.status.name
                    new_status = 'CLOSED'
                    if current_status.lower() != "closed":
                        new_status = 'CLOSED'
                        message = f"Elliott changed bug status from {current_status} to {new_status} because {nvrs} was/were already shipped and tagged into {prod_brew_tag}."
                        self._move_jira(jira_client, issue, new_status, message)
                    else:
                        logger.info("No need to move %s because its status is %s", issue.key, current_status)
                tracker_message = f"Build(s) {nvrs} was/were already shipped and tagged into {prod_brew_tag}."
            else:
                modified = all([any(map(lambda t: t["name"] == candidate_brew_tag, tags)) for tags in build_tags])
                if modified:
                    logger.info("Build(s) %s tagged into %s. Moving Jira(s) %s to MODIFIED...", nvrs, candidate_brew_tag, issue_keys)
                    for issue in issues:
                        current_status: str = issue.fields.status.name
                        if current_status.lower() in {"new", "assigned", "post"}:
                            new_status = 'MODIFIED'
                            message = f"Elliott changed bug status from {current_status} to {new_status} because {nvrs} was/were already tagged into {candidate_brew_tag}."
                            self._move_jira(jira_client, issue, new_status, message)
                        else:
                            logger.info("No need to move %s because its status is %s", issue.key, current_status)
                    tracker_message = f"Build(s) {nvrs} was/were already tagged into {candidate_brew_tag}."
            if self.comment and tracker_message:
                logger.info("Checking if making a comment on tracker %s is needed", tracker.key)
                comments = jira_client.comments(tracker.key)
                if any(map(lambda comment: comment.body == tracker_message, comments)):
                    logger.info("A comment was already made on %s", tracker.key)
                    continue
                logger.info("Making a comment on tracker %s", tracker.key)
                if not self.dry_run:
                    jira_client.add_comment(tracker.key, tracker_message)
                    logger.info("Left a comment on tracker %s", tracker.key)
                else:
                    logger.warning("[DRY RUN] Would have left a comment on tracker %s", tracker.key)

    def _move_jira(self, jira_client: JIRA, issue: Issue, new_status: str, comment: Optional[str]):
        logger = self._runtime.logger
        current_status: str = issue.fields.status.name
        logger.info("Moving %s from %s to %s", issue.key, current_status, new_status)
        if not self.dry_run:
            jira_client.assign_issue(issue.key, jira_client.current_user())
            jira_client.transition_issue(issue.key, new_status)
            if comment:
                jira_client.add_comment(issue.key, comment)
            logger.info("Moved %s from %s to %s", issue.key, current_status, new_status)
        else:
            logger.warning("[DRY RUN] Would have moved Jira %s from %s to %s", issue.key, current_status, new_status)

    @staticmethod
    def _print_report(report: Dict, out: TextIO):
        print_func = green_print if out.isatty() else print  # use green_print if out is a TTY
        jira_issues = sorted(report.get("jira_issues", []), key=lambda issue: issue["key"])
        for issue in jira_issues:
            text = f"{issue['key']}\t{issue['status']}\t{issue['summary']}"
            print_func(text, file=out)


@cli.command("find-bugs:kernel-clones", short_help="Find kernel bugs")
@click.option("--tracker", "trackers", metavar='JIRA_KEY', multiple=True,
              help="Find by the specified KMAINT tracker JIRA_KEY")
@click.option("--issue", "issues", metavar='JIRA_KEY', multiple=True,
              help="Find by the specified Jira bug JIRA_KEY")
@click.option("--move",
              is_flag=True,
              default=False,
              help="Auto move Jira bugs to MODIFIED or CLOSED")
@click.option("--comment",
              is_flag=True,
              default=False,
              help="Make comments on KMAINT trackers")
@click.option("--dry-run",
              is_flag=True,
              default=False,
              help="Don't change anything")
@click.pass_obj
@click_coroutine
async def find_bugs_kernel_clones_cli(
        runtime: Runtime, trackers: Tuple[str, ...], issues: Tuple[str, ...],
        move: bool, comment: bool, dry_run: bool):
    """Find cloned kernel bugs in JIRA for weekly kernel release through OCP.

    Example 1: List all bugs in JIRA
    \b
        $ elliott -g openshift-4.14 find-bugs:kernel-clones

    Example 2: Move bugs to MODIFIED/CLOSED based on what Brew tags that the builds have.
    \b
        $ elliott -g openshift-4.14 find-bugs:kernel-clones --move

    Example 3: Move bugs and leave a comment on the KMAINT tracker
    \b
        $ elliott -g openshift-4.14 find-bugs:kernel-clones --move --comment
    """
    runtime.initialize(mode="none")
    cli = FindBugsKernelClonesCli(
        runtime=runtime,
        trackers=trackers,
        issues=issues,
        move=move,
        comment=comment,
        dry_run=dry_run
    )
    await cli.run()
