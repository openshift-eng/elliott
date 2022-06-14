import unittest
from flexmock import flexmock
from elliottlib import constants, exceptions, bzutil
from elliottlib.bzutil import Bug, BugzillaBug, JIRABug


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

    def test_get_corresponding_flaw_bugs(self):
        tracker_bugs = [
            flexmock(blocks=[1, 2], id=10),
            flexmock(blocks=[2, 3, 4], id=11),
        ]
        bugs = [1, 2, 3, 4]
        product = 'Security Response'
        component = 'vulnerability'
        bug_a = flexmock(product=product, component=component, id=1)
        flexmock(bug_a).should_receive("is_flaw_bug").and_return(True)
        bug_b = flexmock(product=product, component=component, id=2)
        flexmock(bug_b).should_receive("is_flaw_bug").and_return(True)
        bug_c = flexmock(product='foo', component=component, id=3)
        flexmock(bug_c).should_receive("is_flaw_bug").and_return(False)
        bug_d = flexmock(product=product, component='bar', id=4)
        flexmock(bug_d).should_receive("is_flaw_bug").and_return(False)
        flaw_bugs = [
            bug_a,
            bug_b,
            bug_c,
            bug_d
        ]

        fields = ["somefield"]
        bzapi = flexmock()
        flexmock(bzapi).should_receive("get_bugs").with_args(bugs, include_fields=["somefield", "product", "component"]).and_return(flaw_bugs)

        expected = 2
        actual = len(bzutil.get_corresponding_flaw_bugs(bzapi, tracker_bugs, fields)[1])
        self.assertEqual(expected, actual)

    def test_validate_tracker_has_flaw(self):
        tracker_bugs = [
            flexmock(blocks=[1, 2], id=10),
            flexmock(blocks=[2, 3], id=11),
            flexmock(blocks=[], id=12)
        ]
        product = 'Security Response'
        component = 'vulnerability'
        bug_a = flexmock(product=product, component='wrong_component', id=1)
        flexmock(bug_a).should_receive("is_flaw_bug").and_return(False)
        bug_b = flexmock(product='wrong_product', component=component, id=2)
        flexmock(bug_b).should_receive("is_flaw_bug").and_return(False)
        bug_c = flexmock(product=product, component=component, id=3)
        flexmock(bug_c).should_receive("is_flaw_bug").and_return(True)
        flaw_bugs = [bug_a, bug_b, bug_c]

        bzapi = flexmock()
        (bzapi
         .should_receive("get_bugs")
         .and_return(flaw_bugs))

        self.assertRaisesRegex(
            exceptions.ElliottFatalError,
            r'^No flaw bugs could be found for these trackers: {10, 12}$',
            bzutil.get_corresponding_flaw_bugs,
            bzapi, tracker_bugs, ['some_field'], strict=True)

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

    def test_is_first_fix_any_no_trackers(self):
        tr = '4.8.0'
        tracker_bug_ids = [1, 2]
        bug_a = flexmock(id=1, product=constants.BUGZILLA_PRODUCT_OCP, keywords=['foo'], whiteboard='', target_release=[tr])
        flexmock(bug_a).should_receive("is_tracker_bug").and_return(False)
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
            .should_receive("get_bugs")
            .and_return([]))

        expected = True
        actual = bzutil.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_missing_component(self):
        tr = '4.8.0'
        bug_a = flexmock(id=1, product=constants.BUGZILLA_PRODUCT_OCP, keywords=constants.TRACKER_BUG_KEYWORDS, whiteboard='', target_release=[tr])
        flexmock(bug_a).should_receive("is_tracker_bug").and_return(True)
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
            .should_receive("get_bugs")
            .and_return(tracker_bug_objs))

        expected = False
        actual = bzutil.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_same_major(self):
        bug_a = flexmock(
            id=1,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            product=constants.BUGZILLA_PRODUCT_OCP,
            whiteboard='component:runc',
            target_release=['3.11.z'],
            status='RELEASE_PENDING')
        flexmock(bug_a).should_receive("is_tracker_bug").and_return(True)
        bug_b = flexmock(
            id=2,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            product=constants.BUGZILLA_PRODUCT_OCP,
            whiteboard='component:runc',
            target_release=['4.8.0'],
            status='ON_QA')
        flexmock(bug_b).should_receive("is_tracker_bug").and_return(True)
        tracker_bug_objs = [
            # bug that should be ignored
            bug_a,
            bug_b
        ]
        tracker_bug_ids = [t.id for t in tracker_bug_objs]
        flaw_bug = flexmock(id=3, depends_on=tracker_bug_ids)
        tr = '4.8.0'

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
            .should_receive("get_bugs")
            .and_return(tracker_bug_objs))

        expected = True
        actual = bzutil.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_already_fixed(self):
        bug_a = flexmock(
            id=1,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            whiteboard='component:runc',
            product=constants.BUGZILLA_PRODUCT_OCP,
            target_release=['4.7.z'],
            status='RELEASE_PENDING')
        flexmock(bug_a).should_receive("is_tracker_bug").and_return(True)
        bug_b = flexmock(
            id=2,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            whiteboard='component:runc',
            product=constants.BUGZILLA_PRODUCT_OCP,
            target_release=['4.8.0'],
            status='ON_QA')
        flexmock(bug_b).should_receive("is_tracker_bug").and_return(True)
        tracker_bug_objs = [bug_a, bug_b]
        tracker_bug_ids = [t.id for t in tracker_bug_objs]
        flaw_bug = flexmock(id=3, depends_on=tracker_bug_ids)
        tr = '4.8.0'

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
            .should_receive("get_bugs")
            .and_return(tracker_bug_objs))

        expected = False
        actual = bzutil.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_any(self):
        bug_a = flexmock(
            id=1,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            whiteboard='component:runc',
            product=constants.BUGZILLA_PRODUCT_OCP,
            target_release=['4.7.z'],
            status='RELEASE_PENDING')
        bug_b = flexmock(
            id=2,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            whiteboard='component:runc',
            product=constants.BUGZILLA_PRODUCT_OCP,
            target_release=['4.8.0'],
            status='ON_QA')
        bug_c = flexmock(
            id=3,
            keywords=constants.TRACKER_BUG_KEYWORDS,
            whiteboard='component:crio',
            product=constants.BUGZILLA_PRODUCT_OCP,
            target_release=['4.8.0'],
            status='ON_QA')
        flexmock(bug_a).should_receive("is_tracker_bug").and_return(True)
        flexmock(bug_b).should_receive("is_tracker_bug").and_return(True)
        flexmock(bug_c).should_receive("is_tracker_bug").and_return(True)
        tracker_bug_objs = [bug_a, bug_b, bug_c]
        tracker_bug_ids = [t.id for t in tracker_bug_objs]
        flaw_bug = flexmock(id=4, depends_on=tracker_bug_ids)
        tr = '4.8.0'

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
            .should_receive("get_bugs")
            .and_return(tracker_bug_objs))

        expected = True
        actual = bzutil.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
