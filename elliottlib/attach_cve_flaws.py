from typing import Dict, List

from bugzilla.bug import Bug

from elliottlib import bzutil, constants, errata, exceptions, logutil, util

logger = logutil.getLogger(__name__)


def get_tracker_bugs(bzapi, advisory, fields) -> List[Bug]:
    """
    Fetches and returns tracker bug objects from bugzilla
    for the given advisory object
    """
    bug_ids = advisory.errata_bugs
    bug_objs = [b for b in bzapi.getbugs(
        bug_ids,
        permissive=False,
        include_fields=fields)
        if is_tracker_bug(b)
    ]
    return bug_objs


def get_all_attached_bugs(advisory_id):
    return [bug['bug'] for bug in errata.get_raw_erratum(advisory_id)['bugs']['bugs']]


def is_tracker_bug(bug):
    """
    For a given bug object check if it's
    a tracker bug or not
    """
    for k in constants.TRACKER_BUG_KEYWORDS:
        if k not in bug.keywords:
            return False
    return True


def get_advisory(advisory_id):
    return errata.ErrataConnector()._get(f'/api/v1/erratum/{advisory_id}')


def get_corresponding_flaw_bugs(bzapi, tracker_bugs, fields, strict=False):
    """
    Get corresponding flaw bugs objects for the
    given tracker bug objects
    :return (tracker_flaws, flaw_id_bugs): tracker_flaws is a dict with tracker bug id as key and list of flaw bug id as value,
                                        flaw_bugs is a dict with flaw bug id as key and flaw bug object as value
    """
    # fields needed for is_flaw_bug()
    if "product" not in fields:
        fields.append("product")
    if "component" not in fields:
        fields.append("component")

    blocking_bugs = bzutil.get_bugs(bzapi, unique(flatten([t.blocks for t in tracker_bugs])), include_fields=fields)
    flaw_id_bugs: Dict[int, Bug] = {bug.id: bug for bug in blocking_bugs.values() if bzutil.is_flaw_bug(bug)}

    # Validate that each tracker has a corresponding flaw bug
    flaw_ids = set(flaw_id_bugs.keys())
    no_flaws = set()
    for tracker in tracker_bugs:
        if not set(tracker.blocks).intersection(flaw_ids):
            no_flaws.add(tracker.id)
    if no_flaws:
        msg = f'No flaw bugs could be found for these trackers: {no_flaws}'
        if strict:
            raise exceptions.ElliottFatalError(msg)
        else:
            logger.warn(msg)

    tracker_flaws: Dict[int, List[int]] = {
        tracker.id: [blocking for blocking in tracker.blocks if blocking in flaw_id_bugs]
        for tracker in tracker_bugs
    }
    return tracker_flaws, flaw_id_bugs


def is_first_fix_any(bzapi, flaw_bug, current_target_release):
    """
    Check if a flaw bug is considered a first-fix for a GA target release
    for any of its trackers components. A return value of True means it should be
    attached to an advisory.
    """
    # all z stream bugs are considered first fix
    if current_target_release[-1] != '0':
        return True

    # get all tracker bugs for a flaw bug
    tracker_ids = flaw_bug.depends_on
    if not tracker_ids:
        # No trackers found
        # is a first fix
        # shouldn't happen ideally
        return True

    # filter tracker bugs by OCP product
    tracker_bugs = [b for b in bzapi.query(bzapi.build_query(
        product=constants.BUGZILLA_PRODUCT_OCP,
        bug_id=tracker_ids,
        include_fields=["keywords", "target_release", "status", "resolution", "whiteboard"]
    )) if is_tracker_bug(b)]
    if not tracker_bugs:
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
    component_not_found = '[NotFound]'
    for b in tracker_bugs:
        # filter out trackers that don't belong ex. 3.X bugs for 4.X target release
        if not same_major_release(b):
            continue
        component = bzutil.get_whiteboard_component(b)
        if not component:
            component = component_not_found

        if component not in component_tracker_groups:
            component_tracker_groups[component] = set()
        component_tracker_groups[component].add(b)

    if component_not_found in component_tracker_groups:
        invalid_trackers = sorted([b.id for b in component_tracker_groups[component_not_found]])
        logger.warning(f"For flaw bug {flaw_bug.id} - these tracker bugs do not have a valid "
                       f"whiteboard component value: {invalid_trackers} "
                       "Cannot reliably determine if flaw bug is first "
                       "fix. Check tracker bugs manually")
        return False

    # if any tracker bug for the flaw bug
    # has been fixed for the same major release version
    # then it is not a first fix
    def is_first_fix_group(trackers):
        for b in trackers:
            if already_fixed(b):
                return False
        return True

    # if for any component is_first_fix_group is true
    # then flaw bug is first fix
    for component, trackers in component_tracker_groups.items():
        if is_first_fix_group(trackers):
            logger.info(f'{flaw_bug.id} considered first-fix for component: {component} for trackers: '
                        f'{[t.id for t in trackers]}')
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
