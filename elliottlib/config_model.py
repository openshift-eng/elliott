
from typing import List
from pydantic import BaseModel, Field


class KernelBugSweepConfig(BaseModel):
    """ Represents kernel_bug_sweep field in bug.yml

    Example config:
        kernel_bug_sweep:
            tracker_jira:
                project: KMAINT
                labels:
                - early-kernel-track
            bugzilla:
                target_releases:
                - 9.2.0
            target_jira:
                project: OCPBUGS
                component: RHCOS
                version: "{MAJOR}.{MINOR}"
                target_release: "{MAJOR}.{MINOR}.0"
                candidate_brew_tag: "rhaos-{MAJOR}.{MINOR}-rhel-9-candidate"
                prod_brew_tag: "rhaos-{MAJOR}.{MINOR}-rhel-9"
    """
    class TrackerJiraConfig(BaseModel):
        """ tracker_jira field in kernel_bug_sweep config
        """

        project: str = Field(min_length=1, default="KMAINT")
        """ Jira project to discover weekly kernel release trackers """

        labels: List[str]
        """ Jira labels for filtering weekly kernel release trackers """

    class BugzillaConfig(BaseModel):
        """ bugzilla field in kernel_bug_sweep config
        """

        target_releases: List[str]
        """ Target releases of kernel bugs in Bugzilla
        """

    class TargetJiraConfig(BaseModel):
        """ target_jira field in kernel_bug_sweep config """

        project: str = Field(min_length=1, default="OCPBUGS")
        """ Target Jira project to clone kernel bugs into """

        component: str = Field(min_length=1, default="RHCOS")
        """ Component name to set on cloned kernel bugs """

        version: str = Field(min_length=1)
        """ Version to set on cloned kernel bugs """

        target_release: str = Field(min_length=1)
        """ Target Version to set on cloned kernel bugs """

        candidate_brew_tag: str = Field(min_length=1)
        """ when a kernel build is tagged into this candidate Brew tag, move the bug to MODIFIED """

        prod_brew_tag: str = Field(min_length=1)
        """ when a kernel build is tagged into this prod Brew tag, move the bug to CLOSED """

    tracker_jira: TrackerJiraConfig
    """ Config options for weekly kernel release trackers """

    bugzilla: BugzillaConfig
    """ Config options for source kernel bugs """

    target_jira: TargetJiraConfig
    """ Config options for cloned Jira bugs """
