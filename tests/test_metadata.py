import unittest

import re
import datetime

from unittest.mock import MagicMock, Mock, patch

from elliottlib.metadata import Metadata
from elliottlib.brew import BuildStates
from elliottlib.model import Model


class TestMetadata(unittest.TestCase):

    def setUp(self) -> None:
        data_obj = MagicMock(key="foo", filename="foo.yml", data={"name": "foo"})
        runtime = MagicMock()
        runtime.group_config.urls.cgit = "https://distgit.example.com/cgit"
        runtime.group_config.scan_freshness.threshold_hours = 6
        runtime.logger = Mock()

        koji_mock = Mock()
        koji_mock.__enter__ = Mock()
        koji_mock.__enter__.return_value = koji_mock
        koji_mock.__exit__ = Mock()

        runtime.pooled_koji_client_session = Mock()
        runtime.pooled_koji_client_session.return_value = koji_mock

        self.package_id = 5
        koji_mock.getPackage = Mock(return_value={'name': 'foo-container', 'id': self.package_id})
        koji_mock.listTags = Mock(return_value=[{'name': 'rhaos-4.7-rhel-8-candidate'}])

        runtime.assembly = 'hotfix_a'
        image_meta = Metadata("image", runtime, data_obj)
        image_meta.logger = Mock()
        image_meta.get_component_name = Mock(return_value='foo-container')
        image_meta.branch_major_minor = Mock(return_value='4.7')
        image_meta.branch = Mock(return_value='rhaos-4.7-rhel-8')
        image_meta.candidate_brew_tags = Mock(return_value=['rhaos-4.7-rhel-8-candidate', 'rhaos-4.7-rhel-7-candidate'])

        self.runtime = runtime
        self.meta = image_meta
        self.koji_mock = koji_mock

    def build_record(self, creation_dt: datetime.datetime, assembly, name='foo-container',
                     version='4.7.0', p='p0', epoch=None, git_commit='4c0ed6d',
                     release_prefix=None, release_suffix='',
                     build_state: BuildStates = BuildStates.COMPLETE,
                     is_rpm: bool = False):
        """
        :return: Returns an artificial brew build record.
        """
        if not release_prefix:
            release_prefix = creation_dt.strftime('%Y%m%d%H%M%S')

        release = release_prefix

        if p:
            release += f'.{p}'

        if git_commit:
            release += f'.g{git_commit[:7]}'

        if assembly is not None:
            release += f'.assembly.{assembly}{release_suffix}'

        ver_prefix = '' if is_rpm else 'v'

        return {
            'name': name,
            'package_name': name,
            'version': version,
            'release': release,
            'epoch': epoch,
            'nvr': f'{name}-{ver_prefix}{version}-{release}',
            'build_id': creation_dt.timestamp(),
            'creation_event_id': creation_dt.timestamp(),
            'creation_ts': creation_dt.timestamp(),
            'creation_time': creation_dt.isoformat(),
            'state': build_state.value,
            'package_id': self.package_id,
        }

    def _list_builds(self, builds, packageID=None, state=None, pattern=None, queryOpts=None):
        """
        A simple replacement of koji's listBuilds API. The vital input to this
        the `builds` variable. It will be filtered based on
        some of the parameters passed to this method.
        """
        pattern_regex = re.compile(r'.*')
        if pattern:
            regex = pattern.replace('.', "\\.")
            regex = regex.replace('*', '.*')
            pattern_regex = re.compile(regex)

        refined = list(builds)
        refined = [build for build in refined if pattern_regex.match(build['nvr'])]

        if packageID is not None:
            refined = [build for build in refined if build['package_id'] == packageID]

        if state is not None:
            refined = [build for build in refined if build['state'] == state]

        refined.sort(key=lambda e: e['creation_ts'], reverse=True)
        return refined

    def test_get_latest_build(self):
        runtime = self.runtime
        meta = self.meta
        koji_mock = self.koji_mock
        now = datetime.datetime.now(datetime.timezone.utc)

        def list_builds(packageID=None, state=None, pattern=None, queryOpts=None):
            return self._list_builds(builds, packageID=packageID, state=state, pattern=pattern, queryOpts=queryOpts)

        koji_mock.listBuilds.side_effect = list_builds

        # If listBuilds returns nothing, no build should be returned
        builds = []
        self.assertIsNone(meta.get_latest_build(default=None))

        # If listBuilds returns a build from an assembly that is not ours
        # get_latest_builds should not return it.
        builds = [
            self.build_record(now, assembly='not_ours')
        ]
        self.assertIsNone(meta.get_latest_build(default=None))

        # If there is a build from the 'stream' assembly, it should be
        # returned.
        builds = [
            self.build_record(now, assembly='not_ours'),
            self.build_record(now, assembly='stream')
        ]
        self.assertEqual(meta.get_latest_build(default=None), builds[1])

        # If there is a build for our assembly, it should be returned
        builds = [
            self.build_record(now, assembly=runtime.assembly)
        ]
        self.assertEqual(meta.get_latest_build(default=None), builds[0])

        # If there is a build for our assembly and stream, our assembly
        # should be preferred even if stream is more recent.
        builds = [
            self.build_record(now - datetime.timedelta(hours=5), assembly='stream'),
            self.build_record(now, assembly='not_ours'),
            self.build_record(now, assembly=runtime.assembly)
        ]
        self.assertEqual(meta.get_latest_build(default=None), builds[2])

        # The most recent assembly build should be preferred.
        builds = [
            self.build_record(now - datetime.timedelta(hours=5), assembly='stream'),
            self.build_record(now - datetime.timedelta(hours=5), assembly=runtime.assembly),
            self.build_record(now, assembly='not_ours'),
            self.build_record(now, assembly=runtime.assembly)
        ]
        self.assertEqual(meta.get_latest_build(default=None), builds[3])

        # Make sure that just matching the prefix of an assembly is not sufficient.
        builds = [
            self.build_record(now - datetime.timedelta(hours=5), assembly='stream'),
            self.build_record(now - datetime.timedelta(hours=5), assembly=runtime.assembly),
            self.build_record(now, assembly='not_ours'),
            self.build_record(now, assembly=f'{runtime.assembly}b')
        ]
        self.assertEqual(meta.get_latest_build(default=None), builds[1])

        # But, a proper suffix like '.el8' should still match.
        builds = [
            self.build_record(now - datetime.timedelta(hours=5), assembly='stream'),
            self.build_record(now - datetime.timedelta(hours=5), assembly=runtime.assembly),
            self.build_record(now, assembly='not_ours'),
            self.build_record(now, assembly=f'{runtime.assembly}', release_suffix='.el8')
        ]
        self.assertEqual(meta.get_latest_build(default=None), builds[3])

        # By default, we should only be finding COMPLETE builds
        builds = [
            self.build_record(now - datetime.timedelta(hours=5), assembly='stream', build_state=BuildStates.COMPLETE),
            self.build_record(now, assembly='stream', build_state=BuildStates.FAILED),
        ]
        self.assertEqual(meta.get_latest_build(default=None), builds[0])

        # By default, we should only be finding COMPLETE builds
        builds = [
            self.build_record(now - datetime.timedelta(hours=5), assembly=None, build_state=BuildStates.COMPLETE),
            self.build_record(now, assembly=None, build_state=BuildStates.FAILED),
            self.build_record(now, assembly=None, build_state=BuildStates.COMPLETE),
        ]
        self.assertEqual(meta.get_latest_build(default=None, assembly=''), builds[2])

        # Check whether extra pattern matching works
        builds = [
            self.build_record(now - datetime.timedelta(hours=5), assembly='stream'),
            self.build_record(now - datetime.timedelta(hours=25), assembly='stream', release_prefix='99999.g1234567', release_suffix='.el8'),
            self.build_record(now - datetime.timedelta(hours=5), assembly=runtime.assembly),
            self.build_record(now, assembly='not_ours'),
            self.build_record(now - datetime.timedelta(hours=8), assembly=f'{runtime.assembly}')
        ]
        self.assertEqual(meta.get_latest_build(default=None, extra_pattern='*.g1234567.*'), builds[1])

    def test_get_latest_build_multi_target(self):
        meta = self.meta
        koji_mock = self.koji_mock
        now = datetime.datetime.now(datetime.timezone.utc)

        def list_builds(packageID=None, state=None, pattern=None, queryOpts=None):
            return self._list_builds(builds, packageID=packageID, state=state, pattern=pattern, queryOpts=queryOpts)

        koji_mock.listBuilds.side_effect = list_builds

        # If listBuilds returns nothing, no build should be returned
        builds = []
        self.assertIsNone(meta.get_latest_build(default=None))

        meta.meta_type = 'rpm'

        # Make sure basic RPM search works (no 'v' prefix for version)
        builds = [
            self.build_record(now, assembly='not_ours', is_rpm=True),
            self.build_record(now, assembly='stream', is_rpm=True)
        ]
        self.assertEqual(meta.get_latest_build(default=None), builds[1])

        builds = [
            self.build_record(now, assembly='not_ours', is_rpm=True),
            self.build_record(now, assembly='stream', is_rpm=True, release_suffix='.el8')
        ]
        self.assertEqual(meta.get_latest_build(default=None), builds[1])  # No target should find el7 or el8
        self.assertIsNone(meta.get_latest_build(default=None, el_target='rhel-7'))
        self.assertEqual(meta.get_latest_build(default=None, el_target='rhel-8'), builds[1])

        builds = [
            self.build_record(now, assembly='not_ours', is_rpm=True),
            self.build_record(now, assembly='stream', is_rpm=True, release_suffix='.el7'),
            self.build_record(now - datetime.timedelta(hours=1), assembly='stream', is_rpm=True, release_suffix='.el8')
        ]
        self.assertEqual(meta.get_latest_build(default=None), builds[1])  # Latest is el7 by one hour
        self.assertEqual(meta.get_latest_build(default=None, el_target='rhel-7'), builds[1])
        self.assertEqual(meta.get_latest_build(default=None, el_target='rhel-8'), builds[2])


if __name__ == '__main__':
    unittest.main()
