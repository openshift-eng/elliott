import re
import sys
from typing import Dict, List, Optional, Sequence, TextIO, Tuple, cast

import click
import koji
from jira import JIRA, Issue
from tenacity import retry, stop_after_attempt, wait_fixed

from elliottlib import Runtime, brew, early_kernel
from elliottlib.assembly import AssemblyTypes
from elliottlib.cli.common import cli, click_coroutine
from elliottlib.config_model import KernelBugSweepConfig
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import green_print
from elliottlib.bzutil import JIRABugTracker


# [lmeyer] I like terms to distinguish between the two types of Jira issues we deal with here.
# trackers: the KMAINT issues the kernel team creates for tracking these special releases.
# bugs: OCPBUGS issues that clone the actual kernel bugs driving the need for a special OCP build.
# issues: when we are dealing with Jira issues generically that may be one or the other.
# Historically, bugs were called "issues" here and so they are still called this in command I/Os.


class FindBugsKernelClonesCli:
    def __init__(self, runtime: Runtime, trackers: Sequence[str], bugs: Sequence[str],
                 move: bool, update_tracker: bool, dry_run: bool):
        self._runtime = runtime
        self._logger = runtime.logger
        self.trackers = list(trackers)
        self.bugs = list(bugs)
        self.move = move
        self.update_tracker = update_tracker
        self.dry_run = dry_run

    def run(self):
        logger = self._logger
        if self.update_tracker and not self.move:
            raise ElliottFatalError("--update-tracker must be used with --move")
        if self._runtime.assembly_type is not AssemblyTypes.STREAM:
            raise ElliottFatalError("This command only supports stream assembly.")
        group_config = self._runtime.group_config
        raw_config = self._runtime.gitdata.load_data(key='bug', replace_vars=group_config.vars).data.get("kernel_bug_sweep")
        if not raw_config:
            logger.warning("kernel_bug_sweep is not defined in bug.yml")
            return
        config = KernelBugSweepConfig.parse_obj(raw_config)
        jira_tracker = self._runtime.get_bug_tracker("jira")
        jira_client: JIRA = jira_tracker._client
        koji_api = self._runtime.build_retrying_koji_client(caching=True)

        # Search for Jiras
        report = {"jira_issues": []}
        if self.bugs:
            logger.info("Getting specified Jira bugs %s...", self.bugs)
            found_bugs = self._get_jira_bugs(jira_client, self.bugs, config)
        else:
            logger.info("Searching for bug clones in Jira project %s...", config.target_jira.project)
            found_bugs = self._search_for_jira_bugs(jira_client, self.trackers, config)
        bug_keys = [bug.key for bug in found_bugs]
        logger.info("Found %s Jira(s) in %s: %s", len(bug_keys), config.target_jira.project, bug_keys)

        # Update JIRA bugs
        if self.move and found_bugs:
            logger.info("Moving bug clones...")
            self._update_jira_bugs(jira_client, found_bugs, koji_api, config)
            logger.info("Done.")

        # Print a report
        report["jira_issues"] = [{
            "key": bug.key,
            "summary": bug.fields.summary,
            "status": str(bug.fields.status.name),
        } for bug in found_bugs]
        self._print_report(report, sys.stdout)

    def _get_jira_bugs(self, jira_client: JIRA, bug_keys: List[str], config: KernelBugSweepConfig):
        # get a specified list of jira bugs we created previously as clones of the original kernel bugs
        found_bugs: List[Issue] = []
        labels = {"art:cloned-kernel-bug"}
        for key in bug_keys:
            bug = jira_client.issue(key)
            if not labels.issubset(set(bug.fields.labels)):
                raise ValueError(f"Jira {key} doesn't have all required labels {labels}")
            if bug.fields.project.key != config.target_jira.project:
                raise ValueError(f"Jira {key} doesn't belong to project {config.target_jira.project}")
            components = {c.name for c in bug.fields.components}
            if config.target_jira.component not in components:
                raise ValueError(f"Jira {key} is not set to component {config.target_jira.component}")
            target_versions = getattr(bug.fields, JIRABugTracker.FIELD_TARGET_VERSION)
            target_releases = {t.name for t in target_versions}
            if config.target_jira.target_release not in target_releases:
                raise ValueError(f"Jira {key} has invalid target version: {target_versions}")
            found_bugs.append(bug)
        return found_bugs

    @staticmethod
    @retry(reraise=True, stop=stop_after_attempt(10), wait=wait_fixed(30))
    def _search_for_jira_bugs(jira_client: JIRA, trackers: Optional[List[str]],
                              config: KernelBugSweepConfig):
        # search for jira bugs we created previously as clones of the original kernel bugs
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
        found_bugs = jira_client.search_issues(jql_str, maxResults=0)
        return cast(List[Issue], found_bugs)

    def _find_trackers_for_bugs(self,
                                config: KernelBugSweepConfig,
                                bugs: List[Issue],
                                jira_client: JIRA,
                                ) -> (Dict[str, Issue], Dict[str, List[Issue]]):
        # find relevant KMAINT trackers given the Jira bugs we previously made for them
        trackers: Dict[str, Issue] = {}
        tracker_bugs: Dict[str, List[Issue]] = {}
        for bug in bugs:
            # extract bug id from labels: ["art:bz#12345"] -> 12345
            bug_id = next(map(lambda m: int(m[1]), filter(bool, map(lambda label: re.fullmatch(r"art:bz#(\d+)", label), bug.fields.labels))), None)
            if not bug_id:
                raise ValueError(f"Jira clone {bug.key} doesn't have the required `art:bz#N` label")
            # extract KMAINT tracker key from labels: ["art:kmaint:KMAINT-1"] -> KMAINT-1
            tracker_key = next(map(lambda m: str(m[1]), filter(bool, map(lambda label: re.fullmatch(r"art:kmaint:(\S+)", label), bug.fields.labels))), None)
            if not tracker_key:
                raise ValueError(f"Jira clone {bug.key} doesn't have the required `art:kmaint:*` label")
            tracker = trackers.get(tracker_key)
            if not tracker:
                tracker = trackers[tracker_key] = jira_client.issue(tracker_key)
                if tracker.fields.project.key != config.tracker_jira.project:
                    raise ValueError(f"KMAINT tracker {tracker_key} is not in project {config.tracker_jira.project}")
                if not set(config.tracker_jira.labels).issubset(set(tracker.fields.labels)):
                    raise ValueError(f"KMAINT tracker {tracker_key} doesn't have required labels {config.tracker_jira.labels}")
            tracker_bugs.setdefault(tracker.key, []).append(bug)
        return trackers, tracker_bugs

    def _process_shipped_bugs(self, logger, bug_keys, bugs, jira_client: JIRA, nvrs, prod_brew_tag):
        # when NVRs are shipped, ensure the associated bugs are closed with a comment
        logger.info("Build(s) %s shipped (tagged into %s). Moving bug Jira(s) %s to CLOSED...", nvrs, prod_brew_tag, bug_keys)
        for bug in bugs:
            current_status: str = bug.fields.status.name
            if current_status.lower() != "closed":
                new_status = 'CLOSED'
                message = f"Elliott changed bug status from {current_status} to {new_status} because {nvrs} was/were already shipped and tagged into {prod_brew_tag}."
                early_kernel.move_jira(logger, self.dry_run, jira_client, bug, new_status, message)
            else:
                logger.info("No need to move %s because its status is %s", bug.key, current_status)

    def _process_candidate_bugs(self, logger, bug_keys, bugs, jira_client: JIRA, nvrs, candidate_brew_tag):
        # when NVRs are tagged, ensure the associated bugs are modified with a comment
        logger.info("Build(s) %s tagged into %s. Moving Jira(s) %s to MODIFIED...", nvrs, candidate_brew_tag, bug_keys)
        for bug in bugs:
            current_status: str = bug.fields.status.name
            if current_status.lower() in {"new", "assigned", "post"}:
                new_status = 'MODIFIED'
                message = f"Elliott changed bug status from {current_status} to {new_status} because {nvrs} was/were already tagged into {candidate_brew_tag}."
                early_kernel.move_jira(logger, self.dry_run, jira_client, bug, new_status, message)
            else:
                logger.info("No need to move %s because its status is %s", bug.key, current_status)

    def _update_jira_bugs(self, jira_client: JIRA, found_bugs: List[Issue], koji_api: koji.ClientSession, config: KernelBugSweepConfig):
        logger = self._runtime.logger
        trackers, tracker_bugs = self._find_trackers_for_bugs(config, found_bugs, jira_client)

        for tracker_id, tracker in trackers.items():
            nvrs, candidate, shipped = early_kernel.get_tracker_builds_and_tags(logger, tracker, koji_api, config.target_jira)
            bugs = tracker_bugs[tracker_id]
            bug_keys = [bug.key for bug in bugs]
            if shipped:
                self._process_shipped_bugs(logger, bug_keys, bugs, jira_client, nvrs, shipped)
                if self.update_tracker:
                    early_kernel.process_shipped_tracker(logger, self.dry_run, jira_client, tracker, nvrs, shipped)
            elif candidate:
                self._process_candidate_bugs(logger, bug_keys, bugs, jira_client, nvrs, candidate)
                if self.update_tracker:
                    early_kernel.comment_on_tracker(
                        logger, self.dry_run, jira_client, tracker,
                        [f"Build(s) {nvrs} was/were already tagged into {candidate}."]
                        # do not reword, see NOTE in method
                    )

    @staticmethod
    def _print_report(report: Dict, out: TextIO):
        print_func = green_print if out.isatty() else print  # use green_print if out is a TTY
        jira_bugs = sorted(report.get("jira_issues", []), key=lambda bug: bug["key"])
        for bug in jira_bugs:
            text = f"{bug['key']}\t{bug['status']}\t{bug['summary']}"
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
@click.option("--update-tracker",
              is_flag=True,
              default=False,
              help="Update KMAINT trackers state, links, and comments")
@click.option("--dry-run",
              is_flag=True,
              default=False,
              help="Don't change anything")
@click.pass_obj
def find_bugs_kernel_clones_cli(
        runtime: Runtime, trackers: Tuple[str, ...], issues: Tuple[str, ...],
        move: bool, update_tracker: bool, dry_run: bool):
    """Find cloned kernel bugs in JIRA for weekly kernel release through OCP.

    Example 1: List all bugs in JIRA
    \b
        $ elliott -g openshift-4.14 find-bugs:kernel-clones

    Example 2: Move bugs to MODIFIED/CLOSED based on what Brew tags that the builds have.
    \b
        $ elliott -g openshift-4.14 find-bugs:kernel-clones --move

    Example 3: Move bugs and update the KMAINT tracker
    \b
        $ elliott -g openshift-4.14 find-bugs:kernel-clones --move --update-tracker
    """
    runtime.initialize(mode="none")
    cli = FindBugsKernelClonesCli(
        runtime=runtime,
        trackers=trackers,
        bugs=issues,
        move=move,
        update_tracker=update_tracker,
        dry_run=dry_run
    )
    cli.run()
