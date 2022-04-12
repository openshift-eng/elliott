from elliottlib.bug.base import Bug, BugTracker
from jira import Issue, JIRA
from datetime import datetime
import os
import click
from typing import Optional, List


class JIRABug(Bug):
    def __init__(self, bug_obj: Issue):
        super().__init__(bug_obj)
        self.id = self.bug.key
        self.weburl = self.bug.permalink()
        self.component = self.bug.fields.components[0].name
        self.status = self.bug.fields.status.name
        self.creation_time_parsed = datetime.strptime(str(self.bug.fields.created), '%Y-%m-%dT%H:%M:%S.%f%z')
        self.summary = self.bug.fields.summary
        self.target_release = [x.name for x in self.bug.fields.fixVersions]


class JIRABugTracker(BugTracker):
    @staticmethod
    def get_config(runtime):
        version = f'{runtime.group_config.vars.MAJOR}.{runtime.group_config.vars.MINOR}'
        # TODO: have jira.yml file for all versions 4.6-4.11
        if version != '4.11':
            return {
                'server': "https://issues.stage.redhat.com",
                'project': 'OCPBUGS',
                'target_release': [f"{version}.0", f"{version}.z"]
            }
        return runtime.gitdata.load_data(key='jira').data

    def login(self, token_auth=None) -> JIRA:
        if not token_auth:
            token_auth = os.environ.get("JIRA_TOKEN")
            if not token_auth:
                raise ValueError(f"elliott requires login credentials for {self._server}. Set a JIRA_TOKEN env var ")
        client = JIRA(self._server, token_auth=token_auth)
        return client

    def __init__(self, config):
        super().__init__(config)
        self._project = config.get('project')
        self._client: JIRA = self.login()

    def target_release(self):
        return self.config.get('target_release')

    def get_bug(self, bugid, **kwargs) -> JIRABug:
        return JIRABug(self._client.issue(bugid, **kwargs))

    def get_bugs(self, bugids, strict=True, verbose=False, **kwargs):
        bugs = self._search(self._query(bug_list=bugids), verbose=verbose, **kwargs)
        if strict and len(bugs) < len(bugids):
            raise ValueError(f"Not all bugs were not found, {len(bugs)} out of {len(bugids)}")
        return bugs

    def _query(self, bug_list: Optional[List] = None,
               status: Optional[List] = None,
               target_release: Optional[List] = None,
               include_labels: Optional[List] = None,
               exclude_labels: Optional[List] = None) -> str:
        query = f"project={self._project}"
        if bug_list:
            query += f" and issue in ({','.join(bug_list)})"
        if status:
            query += f" and status in ({','.join(status)})"
        if target_release:
            query += f" and fixVersion in ({','.join(target_release)})"
        if include_labels:
            query += f" and labels in ({','.join(exclude_labels)})"
        if exclude_labels:
            query += f" and labels not in ({','.join(exclude_labels)})"
        return query

    def _search(self, query, verbose=False, **kwargs) -> List[JIRABug]:
        if verbose:
            click.echo(query)
        return [JIRABug(j) for j in self._client.search_issues(query, maxResults=False, **kwargs)]

    def blocker_search(self, status, search_filter='default', filter_out_cve_trackers=False, verbose=False, **kwargs):
        include_labels = ['blocker+']
        exclude_labels = ['SecurityTracking'] if filter_out_cve_trackers else []
        query = self._query(
            status=status,
            include_labels=include_labels,
            exclude_labels=exclude_labels,
            target_release=self.target_release()
        )
        return self._search(query, verbose, **kwargs)

    def search(self, status, search_filter='default', filter_out_cve_trackers=False, verbose=False, **kwargs):
        exclude_labels = ['SecurityTracking'] if filter_out_cve_trackers else []
        query = self._query(
            status=status,
            exclude_labels=exclude_labels
        )
        return self._search(query, verbose, **kwargs)

    def search_with_target_release(self, status, search_filter='default', filter_out_cve_trackers=False,
                                   verbose=False, **kwargs):
        exclude_labels = ['SecurityTracking'] if filter_out_cve_trackers else []
        query = self._query(
            status=status,
            exclude_labels=exclude_labels,
            target_release=self.target_release()
        )
        return self._search(query, verbose, **kwargs)
