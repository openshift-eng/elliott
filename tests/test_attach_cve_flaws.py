import unittest
from flexmock import flexmock
from elliottlib import attach_cve_flaws, constants


class TestAttachCVEFlaws(unittest.TestCase):
    def test_is_tracker_bug(self):
        bug = flexmock(keywords=constants.TRACKER_BUG_KEYWORDS)
        expected = True
        actual = attach_cve_flaws.is_tracker_bug(bug)
        self.assertEqual(expected, actual)

    def test_is_tracker_bug_fail(self):
        bug = flexmock(keywords=['SomeOtherKeyword'])
        expected = False
        actual = attach_cve_flaws.is_tracker_bug(bug)
        self.assertEqual(expected, actual)

    def test_get_tracker_bugs(self):
        valid_tracker = flexmock(id=123, keywords=constants.TRACKER_BUG_KEYWORDS)
        invalid_tracker = flexmock(id=456, keywords=[])
        bug_objs = [
            valid_tracker,
            invalid_tracker
        ]
        bugs = [valid_tracker.id, invalid_tracker.id]

        advisory = flexmock(errata_bugs=bugs)
        fields = ["somefield"]
        bzapi = flexmock()
        (bzapi
         .should_receive("getbugs")
         .with_args(bugs, permissive=False, include_fields=['keywords'])
         .and_return(bug_objs))

        (bzapi
         .should_receive("getbugs")
         .with_args([valid_tracker.id], permissive=False, include_fields=fields)
         .and_return([valid_tracker]))

        expected = [valid_tracker]
        actual = attach_cve_flaws.get_tracker_bugs(bzapi, advisory, fields)
        self.assertEqual(expected, actual)

    def test_get_corresponding_flaw_bugs(self):
        tracker_bugs = [
            flexmock(blocks=[1, 2]),
            flexmock(blocks=[2, 3]),
            flexmock(blocks=[4])
        ]
        bugs = [1, 2, 3, 4]
        product = 'Security Response'
        component = 'vulnerability'
        flaw_bugs = [
            flexmock(product=product, component=component),
            flexmock(product=product, component=component),
            flexmock(product='foo', component=component),
            flexmock(product=product, component='bar')
        ]

        fields = ["somefield"]
        bzapi = flexmock()
        (bzapi
         .should_receive("getbugs")
         .with_args(bugs, permissive=False, include_fields=["somefield", "product", "component"])
         .and_return(flaw_bugs))

        expected = 2
        actual = len(attach_cve_flaws.get_corresponding_flaw_bugs(bzapi, tracker_bugs, fields))
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_validate(self):
        bzapi = None
        bug = None
        tr = '4.8.z'
        expected = True
        actual = attach_cve_flaws.is_first_fix_any(bzapi, bug, tr)
        self.assertEqual(expected, actual)

        bzapi = None
        bug = flexmock(depends_on=[])
        tr = '4.8.0'
        expected = True
        actual = attach_cve_flaws.is_first_fix_any(bzapi, bug, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_no_trackers(self):
        bugs = [1, 2]
        flaw_bug = flexmock(depends_on=bugs)
        tr = '4.8.0'
        bzapi = flexmock()

        fields = ['keywords', 'target_release', 'status', 'resolution', 'whiteboard']
        (bzapi
            .should_receive("build_query")
            .with_args(
                product=constants.BUGZILLA_PRODUCT_OCP,
                bug_id=bugs,
                include_fields=fields))
        (bzapi
            .should_receive("query")
            .and_return([flexmock(keywords=['foo'])]))

        expected = True
        actual = attach_cve_flaws.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_missing_component(self):
        bug_objs = [
            flexmock(id=1, keywords=constants.TRACKER_BUG_KEYWORDS, whiteboard='')
        ]
        bugs = [1, 2]
        flaw_bug = flexmock(id=5, depends_on=bugs)
        tr = '4.8.0'

        bzapi = flexmock()
        fields = ['keywords', 'target_release', 'status', 'resolution', 'whiteboard']
        (bzapi
            .should_receive("build_query")
            .with_args(
                product=constants.BUGZILLA_PRODUCT_OCP,
                bug_id=bugs,
                include_fields=fields))
        (bzapi
            .should_receive("query")
            .and_return(bug_objs))

        expected = False
        actual = attach_cve_flaws.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_same_major(self):
        bug_objs = [
            # bug that should be ignored
            flexmock(
                keywords=constants.TRACKER_BUG_KEYWORDS,
                whiteboard='component:runc',
                target_release=['3.11.z'],
                status='RELEASE_PENDING'),
            flexmock(
                keywords=constants.TRACKER_BUG_KEYWORDS,
                whiteboard='component:runc',
                target_release=['4.8.0'],
                status='ON_QA')
        ]
        bugs = [1, 2]
        flaw_bug = flexmock(depends_on=bugs)
        tr = '4.8.0'

        bzapi = flexmock()
        fields = ['keywords', 'target_release', 'status', 'resolution', 'whiteboard']
        (bzapi
            .should_receive("build_query")
            .with_args(
                product=constants.BUGZILLA_PRODUCT_OCP,
                bug_id=bugs,
                include_fields=fields))
        (bzapi
            .should_receive("query")
            .and_return(bug_objs))

        expected = True
        actual = attach_cve_flaws.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_already_fixed(self):
        bug_objs = [
            flexmock(
                keywords=constants.TRACKER_BUG_KEYWORDS,
                whiteboard='component:runc',
                target_release=['4.7.z'],
                status='RELEASE_PENDING'),
            flexmock(
                keywords=constants.TRACKER_BUG_KEYWORDS,
                whiteboard='component:runc',
                target_release=['4.8.0'],
                status='ON_QA')
        ]
        bugs = [1, 2]
        flaw_bug = flexmock(depends_on=bugs)
        tr = '4.8.0'

        bzapi = flexmock()
        fields = ['keywords', 'target_release', 'status', 'resolution', 'whiteboard']
        (bzapi
            .should_receive("build_query")
            .with_args(
                product=constants.BUGZILLA_PRODUCT_OCP,
                bug_id=bugs,
                include_fields=fields))
        (bzapi
            .should_receive("query")
            .and_return(bug_objs))

        expected = False
        actual = attach_cve_flaws.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_any(self):
        bug_objs = [
            flexmock(
                keywords=constants.TRACKER_BUG_KEYWORDS,
                whiteboard='component:runc',
                target_release=['4.7.z'],
                status='RELEASE_PENDING'),
            flexmock(
                keywords=constants.TRACKER_BUG_KEYWORDS,
                whiteboard='component:runc',
                target_release=['4.8.0'],
                status='ON_QA'),
            flexmock(
                keywords=constants.TRACKER_BUG_KEYWORDS,
                whiteboard='component:crio',
                target_release=['4.8.0'],
                status='ON_QA')
        ]
        bugs = [1, 2]
        flaw_bug = flexmock(depends_on=bugs)
        tr = '4.8.0'

        bzapi = flexmock()
        fields = ['keywords', 'target_release', 'status', 'resolution', 'whiteboard']
        (bzapi
            .should_receive("build_query")
            .with_args(
                product=constants.BUGZILLA_PRODUCT_OCP,
                bug_id=bugs,
                include_fields=fields))
        (bzapi
            .should_receive("query")
            .and_return(bug_objs))

        expected = True
        actual = attach_cve_flaws.is_first_fix_any(bzapi, flaw_bug, tr)
        self.assertEqual(expected, actual)


if __name__ == "main":
    unittest.main()
