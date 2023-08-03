from typing import Dict, List, Optional, Sequence, TextIO, Tuple, cast
import re
import koji
from errata_tool.build import Build
from errata_tool import Erratum, ErrataException
from jira import Issue, JIRA
from elliottlib.config_model import KernelBugSweepConfig
from elliottlib import brew


def get_tracker_builds_and_tags(
        logger, tracker: Issue,
        koji_api: koji.ClientSession,
        config: KernelBugSweepConfig.TargetJiraConfig,
) -> Tuple[List[str], str, str]:
    """
    Determine NVRs (e.g. ["kernel-5.14.0-284.14.1.el9_2"]) from the summary,
    and whether candidate/base tags have been applied
    """
    nvrs = sorted(re.findall(r"(kernel(?:-rt)?-\S+-\S+)", tracker.fields.summary))
    if not nvrs:
        raise ValueError(f"Couldn't determine build NVRs for tracker {tracker.id}. Status will not be changed.")

    logger.info("Getting Brew tags for build(s) %s...", nvrs)
    candidate_brew_tag = config.candidate_brew_tag
    prod_brew_tag = config.prod_brew_tag
    build_tags = [set(t["name"] for t in tags) for tags in brew.get_builds_tags(nvrs, koji_api)]
    shipped = all(prod_brew_tag in tags for tags in build_tags)
    candidate = all(candidate_brew_tag in tags for tags in build_tags)

    return nvrs, candidate_brew_tag if candidate else None, prod_brew_tag if shipped else None


def _advisories_for_builds(nvrs: List[str]) -> List[Erratum]:
    advisories = {}
    for nvr in nvrs:
        try:
            build = Build(nvr)
        except ErrataException:
            continue  # probably build not yet added to an advisory
        for errata_id in build.all_errata_ids:
            if errata_id in advisories:
                continue  # already loaded
            # TODO: optimize with errata.get_raw_erratum
            advisory = Erratum(errata_id=errata_id)
            if advisory.errata_state == "SHIPPED_LIVE":
                advisories[errata_id] = advisory
    return list(advisories.values())


def _link_tracker_advisories(
        logger, dry_run: bool, jira_client: JIRA,
        advisories: List[Erratum], nvrs: List[str], tracker: Issue,
) -> List[str]:
    tracker_messages = []
    links = set(link.raw['object']['url'] for link in jira_client.remote_links(tracker))  # check if we already linked advisories
    for advisory in advisories:
        if advisory.url() in links:
            logger.info(f"Tracker {tracker.id} already links {advisory.url()} ({advisory.synopsis})")
            continue
        tracker_messages.append(f"Build(s) {nvrs} shipped in advisory {advisory.url()} with title:\n{advisory.synopsis}")
        if dry_run:
            logger.info(f"[DRY RUN] Tracker {tracker.id} would have added link {advisory.url()} ({advisory.errata_name}: {advisory.synopsis})")
        else:
            jira_client.add_simple_link(
                tracker, dict(
                    url=advisory.url(),
                    title=f"{advisory.errata_name}: {advisory.synopsis}"))
    return tracker_messages


def process_shipped_tracker(
        logger, dry_run: bool,
        jira_client: JIRA, tracker: Issue,
        nvrs: List[str], shipped_tag: str,
) -> List[str]:
    # when NVRs are shipped, ensure the associated tracker is closed with a comment
    # and a link to any advisory that shipped them
    logger.info("Build(s) %s shipped (tagged into %s). Looking for advisories...", nvrs, shipped_tag)
    advisories = _advisories_for_builds(nvrs)
    if not advisories:
        raise RuntimeError(f"NVRs {nvrs} tagged into {shipped_tag} but not found in any shipped advisories!")
    tracker_messages = _link_tracker_advisories(logger, dry_run, jira_client, advisories, nvrs, tracker)

    logger.info("Moving tracker Jira %s to CLOSED...", tracker)
    current_status: str = tracker.fields.status.name
    if current_status.lower() != "closed":
        if tracker_messages:
            comment_on_tracker(logger, dry_run, jira_client, tracker, tracker_messages)
        else:
            logger.warning("Closing Jira %s without adding any messages; prematurely closed?", tracker)
        move_jira(logger, dry_run, jira_client, tracker, "CLOSED")
    else:
        logger.info("No need to move %s because its status is %s", tracker.key, current_status)


def move_jira(
        logger, dry_run: bool,
        jira_client: JIRA, issue: Issue,
        new_status: str, comment: str = None,
):
    current_status: str = issue.fields.status.name
    if dry_run:
        logger.info("[DRY RUN] Would have moved Jira %s from %s to %s", issue.key, current_status, new_status)
    else:
        logger.info("Moving %s from %s to %s", issue.key, current_status, new_status)
        jira_client.assign_issue(issue.key, jira_client.current_user())
        jira_client.transition_issue(issue.key, new_status)
        if comment:
            jira_client.add_comment(issue.key, comment)
        logger.info("Moved %s from %s to %s", issue.key, current_status, new_status)


def comment_on_tracker(
        logger, dry_run: bool,
        jira_client: JIRA, tracker: Issue,
        comments: List[str],
):
    # wording NOTE: commenting is intended to avoid duplicates, but this logic may re-comment on old
    # trackers if the wording changes after previously commented. think long and hard before
    # changing the wording of any tracker comments.
    logger.info("Checking if making a comment on tracker %s is needed", tracker.key)
    previous_comments = jira_client.comments(tracker.key)
    for comment in comments:
        if any(previous.body == comment for previous in previous_comments):
            logger.info("Intended comment was already made on %s", tracker.key)
            continue
        logger.info("Making a comment on tracker %s", tracker.key)
        if dry_run:
            logger.info("[DRY RUN] Would have left a comment on tracker %s", tracker.key)
        else:
            jira_client.add_comment(tracker.key, comment)
            logger.info("Left a comment on tracker %s", tracker.key)
