from typing import Dict, List, Optional, Sequence, TextIO, Tuple, cast
import re
import koji
from jira import Issue
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
