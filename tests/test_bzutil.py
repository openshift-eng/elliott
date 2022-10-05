from datetime import datetime, timezone
import logging
import unittest
from unittest.mock import Mock
import xmlrpc.client

from flexmock import flexmock
import mock
from elliottlib.bzutil import Bug, JIRABugTracker, BugzillaBugTracker, BugzillaBug, JIRABug, BugTracker
from elliottlib import bzutil, constants, exceptions

hostname = "bugzilla.redhat.com"


class TestBug(unittest.TestCase):
    def test_bug(self):
        bug_obj = flexmock(id=2)
        self.assertEqual(Bug(bug_obj).bug.id, bug_obj.id)


class TestJIRABugTracker(unittest.TestCase):
    def test_get_config(self):
        config = {'foo': 1, 'jira_config': {'bar': 2}}
        runtime = flexmock(
            gitdata=flexmock(load_data=flexmock(data=config)),
            get_major_minor=lambda: (4, 9)
        )
        actual = JIRABugTracker.get_config(runtime)
        expected = {'foo': 1, 'bar': 2}
        self.assertEqual(actual, expected)

    def test_get_corresponding_flaw_bugs_jira(self):
        product = 'Security Response'
        component = 'vulnerability'
        valid_flaw = BugzillaBug(flexmock(product=product, component=component, id=9999))
        invalid_flaw = BugzillaBug(flexmock(product=product, component='foo', id=9998))
        flaw_bugs = [valid_flaw, invalid_flaw]

        tracker_bugs = [
            JIRABug(flexmock(key='OCPBUGS-1', fields=flexmock(labels=[f"flaw:bz#{valid_flaw.id}",
                                                                      f"flaw:bz#{invalid_flaw.id}"]))),
            JIRABug(flexmock(key='OCPBUGS-2', fields=flexmock(labels=[f"flaw:bz#{invalid_flaw.id}"]))),
            JIRABug(flexmock(key='OCPBUGS-3', fields=flexmock(labels=[f"flaw:bz#{valid_flaw.id}"])))
        ]

        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("get_bugs").and_return(flaw_bugs)
        flaw_bug_tracker = BugzillaBugTracker({})
        expected = (
            {'OCPBUGS-1': [valid_flaw.id], 'OCPBUGS-2': [], 'OCPBUGS-3': [valid_flaw.id]},
            {valid_flaw.id: valid_flaw}
        )
        actual = BugTracker.get_corresponding_flaw_bugs(tracker_bugs, flaw_bug_tracker)
        self.assertEqual(expected, actual)


class TestBugzillaBugTracker(unittest.TestCase):
    def test_get_config(self):
        config = {'foo': 1, 'bugzilla_config': {'bar': 2}}
        runtime = flexmock(
            gitdata=flexmock(load_data=flexmock(data=config)),
            get_major_minor=lambda: (4, 9)
        )
        actual = BugzillaBugTracker.get_config(runtime)
        expected = {'foo': 1, 'bar': 2}
        self.assertEqual(actual, expected)

    def test_get_corresponding_flaw_bugs(self):
        product = 'Security Response'
        component = 'vulnerability'
        valid_flaw_a = BugzillaBug(flexmock(product=product, component=component, id=1))
        valid_flaw_b = BugzillaBug(flexmock(product=product, component=component, id=2))
        invalid_flaw_c = BugzillaBug(flexmock(product='foo', component=component, id=3))
        invalid_flaw_d = BugzillaBug(flexmock(product=product, component='bar', id=4))
        flaw_bugs = [valid_flaw_a, valid_flaw_b]

        tracker_bugs = [
            BugzillaBug(flexmock(blocks=[valid_flaw_a.id, valid_flaw_b.id], id=10)),
            BugzillaBug(flexmock(blocks=[valid_flaw_b.id, invalid_flaw_c.id, invalid_flaw_d.id], id=11)),
        ]

        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("get_bugs").and_return(flaw_bugs)
        bug_tracker = BugzillaBugTracker({})

        expected = (
            {10: [valid_flaw_a.id, valid_flaw_b.id], 11: [valid_flaw_b.id]},
            {valid_flaw_a.id: valid_flaw_a, valid_flaw_b.id: valid_flaw_b}
        )
        actual = BugTracker.get_corresponding_flaw_bugs(tracker_bugs, bug_tracker)
        self.assertEqual(expected, actual)

    def test_get_corresponding_flaw_bugs_bz_strict(self):
        tracker_bugs = [
            BugzillaBug(flexmock(blocks=[1, 2], id=10)),
            BugzillaBug(flexmock(blocks=[2, 3], id=11)),
            BugzillaBug(flexmock(blocks=[], id=12))
        ]
        product = 'Security Response'
        component = 'vulnerability'
        bug_a = BugzillaBug(flexmock(product=product, component='wrong_component', id=1))
        bug_b = BugzillaBug(flexmock(product='wrong_product', component=component, id=2))
        bug_c = BugzillaBug(flexmock(product=product, component=component, id=3))
        flaw_bugs = [bug_a, bug_b, bug_c]

        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("get_bugs").and_return(flaw_bugs)
        bug_tracker = BugzillaBugTracker({})

        self.assertRaisesRegex(
            exceptions.ElliottFatalError,
            r'^No flaw bugs could be found for these trackers: {10, 12}$',
            BugTracker.get_corresponding_flaw_bugs,
            tracker_bugs, bug_tracker, strict=True)


class TestJIRABug(unittest.TestCase):
    def test_is_placeholder_bug(self):
        bug1 = flexmock(key='OCPBUGS-1',
                        fields=flexmock(
                            summary='Placeholder',
                            components=[flexmock(name='Release')],
                            labels=['Automation']))
        self.assertEqual(JIRABug(bug1).is_placeholder_bug(), True)

        bug2 = flexmock(key='OCPBUGS-2',
                        fields=flexmock(
                            summary='Placeholder',
                            components=[flexmock(name='Foo')],
                            labels=['Bar']))
        self.assertEqual(JIRABug(bug2).is_placeholder_bug(), False)

    def test_is_ocp_bug(self):
        bug1 = flexmock(key='OCPBUGS-1', fields=flexmock(project=flexmock(key='foo')))
        self.assertEqual(JIRABug(bug1).is_ocp_bug(), False)

        bug2 = flexmock(key='OCPBUGS-1', fields=flexmock(project=flexmock(key='OCPBUGS')))
        flexmock(JIRABug).should_receive("is_placeholder_bug").and_return(True)
        self.assertEqual(JIRABug(bug2).is_ocp_bug(), False)

        bug2 = flexmock(key='OCPBUGS-1', fields=flexmock(project=flexmock(key='OCPBUGS')))
        flexmock(JIRABug).should_receive("is_placeholder_bug").and_return(False)
        self.assertEqual(JIRABug(bug2).is_ocp_bug(), True)

    def test_is_tracker_bug(self):
        bug = flexmock(key='OCPBUGS1', fields=flexmock(labels=constants.TRACKER_BUG_KEYWORDS + ['somethingelse']))
        expected = True
        actual = JIRABug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_is_tracker_bug_fail(self):
        bug = flexmock(key='OCPBUGS1', fields=flexmock(labels=['somethingelse']))
        expected = False
        actual = JIRABug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_component_sub_component(self):
        bug = JIRABug(flexmock(
            key="OCPBUGS-43",
            fields=flexmock(components=[flexmock(name="foo / bar")]))
        )
        actual = (bug.component, bug.sub_component)
        expected = ("foo", "bar")
        self.assertEqual(actual, expected)

    def test_component_sub_component_no_whitespace(self):
        bug = JIRABug(flexmock(
            key="OCPBUGS-43",
            fields=flexmock(components=[flexmock(name="foo/bar")]))
        )
        actual = (bug.component, bug.sub_component)
        expected = ("foo", "bar")
        self.assertEqual(actual, expected)

    def test_corresponding_flaw_bug_ids(self):
        bug = JIRABug(flexmock(
            key="OCPBUGS-43",
            fields=flexmock(labels=["foo", "flaw:123", "flaw:bz#456"]))
        )
        actual = bug.corresponding_flaw_bug_ids
        expected = [456]
        self.assertEqual(actual, expected)

    def test_whiteboard_component(self):
        bug = JIRABug(flexmock(key=1, fields=flexmock(labels=["foo"])))
        self.assertIsNone(bug.whiteboard_component)

        bug = JIRABug(flexmock(key=1, fields=flexmock(labels=["component: "])))
        self.assertIsNone(bug.whiteboard_component)

        for expected in ["something", "openvswitch2.15", "trailing_blank 	"]:
            bug = JIRABug(flexmock(key=1, fields=flexmock(labels=[f"component: {expected}"])))
            actual = bug.whiteboard_component
            self.assertEqual(actual, expected.strip())


class TestBugzillaBug(unittest.TestCase):
    def test_is_tracker_bug(self):
        bug = flexmock(id='1', keywords=constants.TRACKER_BUG_KEYWORDS)
        expected = True
        actual = BugzillaBug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_is_tracker_bug_fail(self):
        bug = flexmock(id='1', keywords=['SomeOtherKeyword'])
        expected = False
        actual = BugzillaBug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_whiteboard_component(self):
        bug = BugzillaBug(flexmock(id=1, whiteboard="foo"))
        self.assertIsNone(bug.whiteboard_component)

        bug = BugzillaBug(flexmock(id=2, whiteboard="component: "))
        self.assertIsNone(bug.whiteboard_component)

        for expected in ["something", "openvswitch2.15", "trailing_blank 	"]:
            bug = BugzillaBug(flexmock(id=2, whiteboard=f"component: {expected}"))
            actual = bug.whiteboard_component
            self.assertEqual(actual, expected.strip())

    def test_filter_bugs_by_cutoff_event(self):
        bzapi = mock.MagicMock()
        with mock.patch("elliottlib.bzutil.BugzillaBugTracker.login") as mock_login:
            mock_login.return_value = bzapi
            bug_tracker = bzutil.BugzillaBugTracker({})
        desired_statuses = ["MODIFIED", "ON_QA", "VERIFIED"]
        sweep_cutoff_timestamp = datetime(2021, 6, 30, 12, 30, 00, 0, tzinfo=timezone.utc).timestamp()
        bugs = [
            mock.MagicMock(id=1, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T12:29:00")),
            mock.MagicMock(id=2, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T12:30:00")),
            mock.MagicMock(id=3, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T12:31:00")),
            mock.MagicMock(id=4, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T00:00:00")),
            mock.MagicMock(id=5, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T00:00:00")),
            mock.MagicMock(id=6, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T00:00:00")),
            mock.MagicMock(id=7, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T00:00:00")),
            mock.MagicMock(id=8, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T00:00:00")),
            mock.MagicMock(id=9, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T00:00:00")),
        ]
        bzapi.bugs_history_raw.return_value = {
            "bugs": [
                {
                    "id": 1,
                    "history": [],
                },
                {
                    "id": 2,
                    "history": [],
                },
                {
                    "id": 4,
                    "history": [
                        {
                            "when": xmlrpc.client.DateTime("20210630T01:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T23:59:59"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                            ]
                        },
                    ],
                },
                {
                    "id": 5,
                    "history": [
                        {
                            "when": xmlrpc.client.DateTime("20210630T01:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "NEW", "added": "MODIFIED"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T23:59:59"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "MODIFIED", "added": "ON_QA"},
                            ]
                        },
                    ],
                },
                {
                    "id": 6,
                    "history": [
                        {
                            "when": xmlrpc.client.DateTime("20210630T01:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "NEW", "added": "ASSIGNED"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T23:59:59"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "ASSIGNED", "added": "ON_QA"},
                            ]
                        },
                    ],
                },
                {
                    "id": 7,
                    "history": [
                        {
                            "when": xmlrpc.client.DateTime("20210630T01:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "NEW", "added": "MODIFIED"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T23:59:59"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "MODIFIED", "added": "ON_QA"},
                            ]
                        },
                    ],
                },
                {
                    "id": 8,
                    "history": [
                        {
                            "when": xmlrpc.client.DateTime("20210630T01:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "NEW", "added": "MODIFIED"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T13:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "MODIFIED", "added": "ON_QA"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T23:59:59"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "ON_QA", "added": "VERIFIED"},
                            ]
                        },
                    ],
                },
                {
                    "id": 9,
                    "history": [
                        {
                            "when": xmlrpc.client.DateTime("20210630T01:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "NEW", "added": "MODIFIED"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T13:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "MODIFIED", "added": "ON_QA"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T23:59:59"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "ON_QA", "added": "ASSIGNED"},
                            ]
                        },
                    ],
                },
            ]
        }
        actual = bug_tracker.filter_bugs_by_cutoff_event(bugs, desired_statuses, sweep_cutoff_timestamp)
        self.assertListEqual([1, 2, 4, 5, 7, 8], [bug.id for bug in actual])


class TestBZUtil(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_is_viable_bug(self):
        bug = mock.MagicMock()
        bug.status = "MODIFIED"
        self.assertTrue(bzutil.is_viable_bug(bug))
        bug.status = "ASSIGNED"
        self.assertFalse(bzutil.is_viable_bug(bug))

    def test_to_timestamp(self):
        dt = xmlrpc.client.DateTime("20210615T18:23:22")
        actual = bzutil.to_timestamp(dt)
        self.assertEqual(actual, 1623781402.0)

    def test_approximate_cutoff_timestamp(self):
        koji_api = mock.MagicMock()
        koji_api.getEvent.return_value = {"ts": datetime(2021, 7, 3, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp()}
        metas = [
            mock.MagicMock(),
            mock.MagicMock(),
            mock.MagicMock(),
        ]
        metas[0].get_latest_build.return_value = {"nvr": "a-4.9.0-202107020000.p0"}
        metas[1].get_latest_build.return_value = {"nvr": "b-4.9.0-202107020100.p0"}
        metas[2].get_latest_build.return_value = {"nvr": "c-4.9.0-202107020200.p0"}
        actual = bzutil.approximate_cutoff_timestamp(mock.ANY, koji_api, metas)
        self.assertEqual(datetime(2021, 7, 2, 2, 0, 0, 0, tzinfo=timezone.utc).timestamp(), actual)

        koji_api.getEvent.return_value = {"ts": datetime(2021, 7, 1, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp()}
        actual = bzutil.approximate_cutoff_timestamp(mock.ANY, koji_api, metas)
        self.assertEqual(datetime(2021, 7, 1, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp(), actual)

        koji_api.getEvent.return_value = {"ts": datetime(2021, 7, 4, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp()}
        actual = bzutil.approximate_cutoff_timestamp(mock.ANY, koji_api, [])
        self.assertEqual(datetime(2021, 7, 4, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp(), actual)

    def test_is_first_fix_any_validate(self):
        bzapi = None
        bug = None
        tr = '4.8.z'
        expected = True
        actual = bzutil.is_first_fix_any(bzapi, bug, tr)
        self.assertEqual(expected, actual)

        bzapi = None
        bug = flexmock(depends_on=[])
        tr = '4.8.0'
        expected = True
        actual = bzutil.is_first_fix_any(bzapi, bug, tr)
        self.assertEqual(expected, actual)

    def test_sort_cve_bugs(self):
        flaw_bugs = [
            flexmock(alias=['CVE-2022-123'], severity='Low'),
            flexmock(alias=['CVE-2022-9'], severity='urgent'),
            flexmock(alias=['CVE-2022-10'], severity='urgent'),
            flexmock(alias=['CVE-2021-789'], severity='medium'),
            flexmock(alias=['CVE-2021-100'], severity='medium')
        ]
        sort_list = [b.alias[0] for b in bzutil.sort_cve_bugs(flaw_bugs)]

        self.assertEqual('CVE-2022-9', sort_list[0])
        self.assertEqual('CVE-2022-10', sort_list[1])
        self.assertEqual('CVE-2021-100', sort_list[2])
        self.assertEqual('CVE-2021-789', sort_list[3])
        self.assertEqual('CVE-2022-123', sort_list[4])

    def test_is_first_fix_any_no_valid_trackers(self):
        tr = '4.8.0'
        tracker_bug_ids = [1, 2]
        bug_a = BugzillaBug(flexmock(
            id=1,
            product=constants.BUGZILLA_PRODUCT_OCP,
            keywords=['foo'])
        )
        tracker_bug_objs = [bug_a]
        flaw_bug = flexmock(id=6, depends_on=tracker_bug_ids)
        bzapi = flexmock()
        fields = ['keywords', 'target_release', 'status', 'resolution', 'whiteboard']
        (bzapi
            .should_receive("build_query")
            .with_args(
                product=constants.BUGZILLA_PRODUCT_OCP,
                bug_id=tracker_bug_ids,
                include_fields=fields))
        (bzapi
            .should_receive("query")
            .and_return(tracker_bug_objs))
        (bzapi
            .should_receive("get_bug")
            .and_return(bug_a))

        expected = True
        actual = bzutil.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_missing_whiteboard_component(self):
        tr = '4.8.0'
        bug_a = BugzillaBug(flexmock(
            id=1,
            product=constants.BUGZILLA_PRODUCT_OCP,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            whiteboard='', target_release=[tr]
        ))
        tracker_bug_objs = [bug_a]
        tracker_bugs_ids = [1, 2]
        flaw_bug = flexmock(id=5, product=constants.BUGZILLA_PRODUCT_OCP, depends_on=tracker_bugs_ids)

        bzapi = flexmock()
        fields = ['keywords', 'target_release', 'status', 'resolution', 'whiteboard']
        (bzapi
            .should_receive("build_query")
            .with_args(
                product=constants.BUGZILLA_PRODUCT_OCP,
                bug_id=tracker_bugs_ids,
                include_fields=fields))
        (bzapi
            .should_receive("query")
            .and_return(tracker_bug_objs))
        (bzapi
            .should_receive("get_bug")
            .with_args(1)
            .and_return(bug_a))
        (bzapi.should_receive("get_bug").with_args(2).and_return(bug_a))

        expected = False
        actual = bzutil.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_is_first_fix_group(self):
        tr = '4.8.0'
        bug_a = BugzillaBug(flexmock(
            id=1,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            product=constants.BUGZILLA_PRODUCT_OCP,
            whiteboard='component:runc',
            target_release=['3.11.z'],
            status='RELEASE_PENDING'))
        bug_b = BugzillaBug(flexmock(
            id=2,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            product=constants.BUGZILLA_PRODUCT_OCP,
            whiteboard='component:runc',
            target_release=[tr],
            status='ON_QA'))
        tracker_bug_objs = [bug_a, bug_b]
        tracker_bug_ids = [t.id for t in tracker_bug_objs]
        flaw_bug = BugzillaBug(flexmock(id=3, depends_on=tracker_bug_ids))

        bzapi = flexmock()
        fields = ['keywords', 'target_release', 'status', 'resolution', 'whiteboard']
        (bzapi
            .should_receive("build_query")
            .with_args(
                product=constants.BUGZILLA_PRODUCT_OCP,
                bug_id=tracker_bug_ids,
                include_fields=fields))
        (bzapi
            .should_receive("query")
            .and_return(tracker_bug_objs))
        (bzapi.should_receive("get_bug").with_args(1).and_return(bug_a))
        (bzapi.should_receive("get_bug").with_args(2).and_return(bug_b))

        expected = True
        actual = bzutil.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_already_fixed(self):
        tr = '4.8.0'
        bug_a = BugzillaBug(flexmock(
            id=1,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            product=constants.BUGZILLA_PRODUCT_OCP,
            whiteboard='component:runc',
            target_release=['4.7.z'],
            status='RELEASE_PENDING'))
        bug_b = BugzillaBug(flexmock(
            id=2,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            product=constants.BUGZILLA_PRODUCT_OCP,
            whiteboard='component:runc',
            target_release=[tr],
            status='ON_QA'))
        tracker_bug_objs = [bug_a, bug_b]
        tracker_bug_ids = [t.id for t in tracker_bug_objs]
        flaw_bug = BugzillaBug(flexmock(id=3, depends_on=tracker_bug_ids))

        bzapi = flexmock()
        fields = ['keywords', 'target_release', 'status', 'resolution', 'whiteboard']
        (bzapi
            .should_receive("build_query")
            .with_args(
                product=constants.BUGZILLA_PRODUCT_OCP,
                bug_id=tracker_bug_ids,
                include_fields=fields))
        (bzapi
            .should_receive("query")
            .and_return(tracker_bug_objs))
        (bzapi
            .should_receive("get_bug")
            .and_return(bug_a))

        expected = False
        actual = bzutil.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_any(self):
        tr = '4.8.0'
        bug_a = BugzillaBug(flexmock(
            id=1,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            whiteboard='component:runc',
            product=constants.BUGZILLA_PRODUCT_OCP,
            target_release=['4.7.z'],
            status='RELEASE_PENDING'))
        bug_b = BugzillaBug(flexmock(
            id=2,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            whiteboard='component:runc',
            product=constants.BUGZILLA_PRODUCT_OCP,
            target_release=[tr],
            status='ON_QA'))
        bug_c = BugzillaBug(flexmock(
            id=3,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            whiteboard='component:crio',
            product=constants.BUGZILLA_PRODUCT_OCP,
            target_release=[tr],
            status='ON_QA'))
        tracker_bug_objs = [bug_a, bug_b, bug_c]
        tracker_bug_ids = [t.id for t in tracker_bug_objs]
        flaw_bug = BugzillaBug(flexmock(id=4, depends_on=tracker_bug_ids))

        bzapi = flexmock()
        fields = ['keywords', 'target_release', 'status', 'resolution', 'whiteboard']
        (bzapi
            .should_receive("build_query")
            .with_args(
                product=constants.BUGZILLA_PRODUCT_OCP,
                bug_id=tracker_bug_ids,
                include_fields=fields))
        (bzapi
            .should_receive("query")
            .and_return(tracker_bug_objs))
        (bzapi
            .should_receive("get_bug")
            .with_args(1)
            .and_return(bug_a))
        (bzapi.should_receive("get_bug").with_args(2).and_return(bug_b))
        (bzapi.should_receive("get_bug").with_args(3).and_return(bug_c))

        expected = True
        actual = bzutil.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)


class TestSearchFilter(unittest.TestCase):
    def test_search_filter(self):
        """Verify the bugzilla SearchFilter works as expected"""
        field_name = "component"
        operator = "notequals"
        value = "RFE"
        expected = "&f1=component&o1=notequals&v1=RFE"

        sf = bzutil.SearchFilter(field_name, operator, value)
        self.assertEqual(sf.tostring(1), expected)


class TestGetHigestImpact(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_lowest_to_highest_impact(self):
        trackers = [flexmock(id=index, severity=severity)
                    for index, severity in enumerate(constants.BUG_SEVERITY_NUMBER_MAP.keys())]
        tracker_flaws_map = {
            tracker.id: [] for tracker in trackers
        }
        impact = bzutil.get_highest_impact(trackers, tracker_flaws_map)
        self.assertEqual(impact, constants.SECURITY_IMPACT[4])

    def test_single_impact(self):
        bugs = []
        severity = "high"
        bugs.append(flexmock(severity=severity))
        impact = bzutil.get_highest_impact(bugs, None)
        self.assertEqual(impact, constants.SECURITY_IMPACT[constants.BUG_SEVERITY_NUMBER_MAP[severity]])

    def test_impact_for_tracker_with_unspecified_severity(self):
        bugs = []
        severity = "unspecified"
        bugs.append(flexmock(id=123, severity=severity))
        tracker_flaws_map = {
            123: [flexmock(id=123, severity="medium")],
        }
        impact = bzutil.get_highest_impact(bugs, tracker_flaws_map)
        self.assertEqual(impact, "Moderate")
        tracker_flaws_map = {
            123: [flexmock(id=123, severity="unspecified")],
        }
        impact = bzutil.get_highest_impact(bugs, tracker_flaws_map)
        self.assertEqual(impact, "Low")


if __name__ == "__main__":
    unittest.main()
