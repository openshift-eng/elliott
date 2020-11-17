import requests
import ssl
from elliottlib import constants, bzutil, errata, util
from requests_kerberos import HTTPKerberosAuth


def get_attached_tracker_bugs(bzapi, advisory_id):
    return bzapi.getbugs([
        bug['id']
        for bug in get_all_attached_bugs(advisory_id)
        if is_tracker_bug(bug)
    ])


def get_all_attached_bugs(advisory_id):
    return [bug['bug'] for bug in errata.get_raw_erratum(advisory_id)['bugs']['bugs']]


def is_tracker_bug(bug):
    return 'Security' in bug['keywords'] and 'SecurityTracking' in bug['keywords']


def is_flaw_bug(bug):
    return bug.product == 'Security Response'


def get_advisory(advisory_id):
    return errata.ErrataConnector()._get(f'/api/v1/erratum/{advisory_id}')


def get_corresponding_flaw_bugs(bzapi, tracker_bugs):
    blocking_bugs = bzapi.getbugs(unique(flatten([t.blocks for t in tracker_bugs])))
    return [flaw_bug for flaw_bug in blocking_bugs if is_flaw_bug(flaw_bug)]


def is_first_fix(bzapi, flaw_bug, current_target_release, tracker_ids_to_be_ignored=[]):
    other_flaw_trackers = bzapi.query(bzapi.build_query(
        product='OpenShift Container Platform',
        bug_id=[t for t in flaw_bug.depends_on if t not in tracker_ids_to_be_ignored],
    ))

    def _filter_tracker(bug):
        current_major_version = util.minor_version_tuple(current_target_release[0])[0]
        bug_target_major_version = util.minor_version_tuple(bug.target_release[0])[0]
        return bug_target_major_version == current_major_version

    def _already_fixed(bug):
        if bug.status == 'RELEASE_PENDING':
            return True
        if bug.status == 'CLOSED' and bug.resolution in ['ERRATA', 'CURRENTRELEASE', 'NEXTRELEASE']:
            return True
        return False

    return not any([_already_fixed(t) for t in filter(_filter_tracker, other_flaw_trackers)])


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
