from elliottlib import constants, errata, util
from elliottlib import bzutil


def get_attached_tracker_bugs(bzapi, advisory_id):
    return bzapi.getbugs([
        bug['id']
        for bug in get_all_attached_bugs(advisory_id)
        if is_tracker_bug(keywords=bug['keywords'])
    ], permissive=False)  # fail if you cannot get all tracker bugs


def get_all_attached_bugs(advisory_id):
    return [bug['bug'] for bug in errata.get_raw_erratum(advisory_id)['bugs']['bugs']]


def is_tracker_bug(bug=None, keywords=None):
    if bug is None and keywords is None:
        raise ValueError("must pass at least 1 param, either bug object or value of bug keywords")
    if keywords is None:
        keywords = bug.keywords
    return 'Security' in keywords and 'SecurityTracking' in keywords


def get_advisory(advisory_id):
    return errata.ErrataConnector()._get(f'/api/v1/erratum/{advisory_id}')


def get_corresponding_flaw_bugs(bzapi, tracker_bugs):
    blocking_bugs = bzapi.getbugs(
        unique(flatten([t.blocks for t in tracker_bugs])),
        permissive=False
    )
    return [flaw_bug for flaw_bug in blocking_bugs if bzutil.is_flaw_bug(flaw_bug)]


def is_first_fix_any(bzapi, flaw_bug, current_target_release):
    """
    Check if a flaw bug is considered a first-fix for a target release
    for any of its components
    """
    # get all tracker bugs for a flaw bug
    tracker_ids = flaw_bug.depends_on
    if len(tracker_ids) == 0:
        # No trackers found
        # is a first fix
        return True

    # filter tracker bugs by OCP product
    tracker_bugs = [b for b in bzapi.query(bzapi.build_query(
        product='OpenShift Container Platform',
        bug_id=tracker_ids,
    )) if is_tracker_bug(b)]
    if len(tracker_bugs) == 0:
        # No OCP trackers found
        # is a first fix
        return True

    # make sure 3.X or 4.X bugs are being compared to each other
    def same_major_release(bug):
        current_major_version = util.minor_version_tuple(current_target_release)[0]
        bug_target_major_version = util.minor_version_tuple(bug.target_release[0])[0]
        return bug_target_major_version == current_major_version

    def already_fixed(bug):
        pending = bug.status == 'RELEASE_PENDING'
        closed = bug.status == 'CLOSED' and bug.resolution in ['ERRATA', 'CURRENTRELEASE', 'NEXTRELEASE']
        if pending or closed:
            return True
        return False

    # group trackers by components
    component_tracker_groups = dict()
    for b in tracker_bugs:
        component = bzutil.get_whiteboard_component(b)
        if not component:
            print("could not find component for bug. cannot reliably determine if bug is first fix or not")
            return False

        if component not in component_tracker_groups:
            component_tracker_groups[component] = set()
        component_tracker_groups[component].add(b)

    # if any tracker bug for the flaw bug
    # has been fixed for the same major release version
    # then it is not a first fix
    def is_first_fix_group(trackers):
        for b in trackers:
            if same_major_release(b) and already_fixed(b):
                return False
        return True

    # if for any component is_first_fix_group is true
    # then flaw bug is first fix
    for _, trackers in component_tracker_groups.items():
        if is_first_fix_group(trackers):
            return True

    return False


def is_security_advisory(advisory):
    return advisory.errata_type == 'RHSA'


def get_highest_security_impact(bugs):
    security_impacts = set(bug.severity.lower() for bug in bugs)
    if 'urgent' in security_impacts:
        return 'Critical'
    if 'high' in security_impacts:
        return 'Important'
    if 'medium' in security_impacts:
        return 'Moderate'
    return 'Low'


def is_advisory_impact_smaller_than(advisory, impact):
    i = [None] + constants.SECURITY_IMPACT
    return i.index(advisory.security_impact) < i.index(impact)


def flatten(lst):
    return [item for sublist in lst for item in sublist]


def unique(lst):
    return list(set(lst))
