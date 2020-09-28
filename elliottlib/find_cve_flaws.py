import requests
import ssl
from elliottlib import constants, bzutil
from requests_kerberos import HTTPKerberosAuth


def get_attached_tracker_bugs(bzapi, advisory_id):
    return bzapi.getbugs([
        bug['id']
        for bug in get_all_attached_bugs(advisory_id)
        if is_tracker_bug(bug)
    ])


def get_all_attached_bugs(advisory_id):
    return [bug['bug'] for bug in get_advisory(advisory_id)['bugs']['bugs']]


def is_tracker_bug(bug):
    return 'Security' in bug['keywords'] and 'SecurityTracking' in bug['keywords']


def get_advisory(advisory_id):
    res = requests.get(
        '{}/api/v1/erratum/{}'.format(constants.errata_url, advisory_id),
        verify=ssl.get_default_verify_paths().openssl_cafile,
        auth=HTTPKerberosAuth(),
    )
    return res.json()


def get_corresponding_flaw_bugs(bzapi, tracker_bugs):
    return bzapi.getbugs(unique(flatten([t.blocks for t in tracker_bugs])))


def is_first_fix(bzapi, flaw_bug, tracker_ids_to_be_ignored=[]):
    other_flaw_trackers = bzapi.getbugs([
        t for t in flaw_bug.depends_on
        if t not in tracker_ids_to_be_ignored
    ])
    return not any([
        t.status == 'RELEASE_PENDING'
        or (
            t.status == 'CLOSED'
            and t.resolution in ['ERRATA', 'CURRENTRELEASE', 'NEXTRELEASE']
        )
        for t in other_flaw_trackers
    ])


def is_security_advisory(advisory):
    return advisory.errata_type == 'RHSA'


def get_highest_security_impact(bugs):
    security_impacts = [bug.severity.lower() for bug in bugs]
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
