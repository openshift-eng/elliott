import unittest
from flexmock import flexmock
from elliottlib import constants, exceptions, bzutil
from elliottlib.bzutil import Bug, BugzillaBug, JIRABug, BugzillaBugTracker, JIRABugTracker


class TestAttachCVEFlaws(unittest.TestCase):
    def test_is_tracker_bug_bz(self):
        bug = flexmock(id='1', keywords=constants.TRACKER_BUG_KEYWORDS)
        expected = True
        actual = BugzillaBug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_is_tracker_bug_jira(self):
        bug = flexmock(key='OCPBUGS1', fields=flexmock(labels=constants.TRACKER_BUG_KEYWORDS + ['somethingelse']))
        expected = True
        actual = JIRABug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_is_tracker_bug_fail_bz(self):
        bug = flexmock(id='1', keywords=['SomeOtherKeyword'])
        expected = False
        actual = BugzillaBug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_is_tracker_bug_fail_jira(self):
        bug = flexmock(key='OCPBUGS1', fields=flexmock(labels=['somethingelse']))
        expected = False
        actual = JIRABug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_get_corresponding_flaw_bugs_bz(self):
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
        actual = bug_tracker.get_corresponding_flaw_bugs(tracker_bugs)
        self.assertEqual(expected, actual)

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
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("get_bugs").and_return(flaw_bugs)
        bug_tracker = JIRABugTracker({})
        flaw_bug_tracker = BugzillaBugTracker({})

        expected = (
            {'OCPBUGS-1': [valid_flaw.id], 'OCPBUGS-2': [], 'OCPBUGS-3': [valid_flaw.id]},
            {valid_flaw.id: valid_flaw}
        )
        actual = bug_tracker.get_corresponding_flaw_bugs(tracker_bugs, flaw_bug_tracker)
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
            bug_tracker.get_corresponding_flaw_bugs,
            tracker_bugs, strict=True)

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


if __name__ == "__main__":
    unittest.main()
