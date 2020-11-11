import bugzilla
import click
from errata_tool import Erratum
from elliottlib import Runtime, bzutil
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.find_cve_flaws import get_attached_tracker_bugs, \
    get_corresponding_flaw_bugs, is_first_fix, is_security_advisory, \
    get_highest_security_impact, is_advisory_impact_smaller_than


pass_runtime = click.make_pass_decorator(Runtime)


@cli.command('find-cve-flaws',
             short_help='Attach corresponding flaw bugs for trackers in advisory (first-fix only)')
@use_default_advisory_option
@pass_runtime
def find_cve_flaws_cli(runtime, default_advisory_type):
    """Attach corresponding flaw bugs for trackers in advisory (first-fix only).

    Also converts advisory to RHSA, if not already.

    Example:

    $ elliott --group openshift-4.6 find-cve-flaws --use-default-advisory image
    INFO Cloning config data from https://github.com/openshift/ocp-build-data.git
    INFO Using branch from group.yml: rhaos-4.6-rhel-8
    INFO found 114 tracker bugs attached to the advisory
    INFO found 58 corresponding flaw bugs
    INFO 23 out of 58 flaw bugs considered "first-fix"
    INFO Adding the following BZs to the advisory: [1880456, 1858827, 1880460,
    1847310, 1857682, 1857550, 1857551, 1857559, 1848089, 1848092, 1849503,
    1851422, 1866148, 1858981, 1852331, 1861044, 1857081, 1857977, 1848647,
    1849044, 1856529, 1843575, 1840253]
    """
    runtime.initialize()
    bzurl = runtime.gitdata.load_data(key='bugzilla').data['server']
    bzapi = bugzilla.Bugzilla(bzurl)

    if default_advisory_type is not None:
        advisory_id = find_default_advisory(runtime, default_advisory_type)

    attached_tracker_bugs = get_attached_tracker_bugs(bzapi, advisory_id)
    # # @TODO: remove this block before merge, let it here for now because it
    # # is useful for testing the PR, when BZs are not yet attached to an advisory
    # attached_tracker_bugs = bzapi.query(bzapi.build_query(
    #     product='OpenShift Container Platform',
    #     status=['MODIFIED', 'ON_QA', 'VERIFIED'],
    #     target_release='3.11.z',
    #     keywords=['Security', 'SecurityTracking'],
    # ))
    runtime.logger.info('found {} tracker bugs attached to the advisory'.format(
        len(attached_tracker_bugs)
    ))

    corresponding_flaw_bugs = get_corresponding_flaw_bugs(bzapi, attached_tracker_bugs)
    runtime.logger.info('found {} corresponding flaw bugs'.format(
        len(corresponding_flaw_bugs)
    ))

    attached_tracker_ids = [tracker.id for tracker in attached_tracker_bugs]
    current_target_release = "{MAJOR}.{MINOR}.z".format(**runtime.group_config.vars)
    first_fix_flaw_bugs = [
        flaw_bug for flaw_bug in corresponding_flaw_bugs
        if is_first_fix(bzapi, flaw_bug, current_target_release, attached_tracker_ids)
    ]
    runtime.logger.info('{} out of {} flaw bugs considered "first-fix"'.format(
        len(first_fix_flaw_bugs), len(corresponding_flaw_bugs),
    ))

    if not first_fix_flaw_bugs:
        runtime.logger.info('No "first-fix" bugs found, exiting')
        exit(0)

    advisory = Erratum(errata_id=advisory_id)
    if not is_security_advisory(advisory):
        runtime.logger.info('Advisory type is {}, converting it to RHSA'.format(advisory.errata_type))
        cve_boilerplate = runtime.gitdata.load_data(key='erratatool').data['boilerplates']['cve']
        cves = ' '.join([flaw_bug.alias[0] for flaw_bug in first_fix_flaw_bugs])
        advisory.update(
            errata_type='RHSA',
            security_reviewer=cve_boilerplate['security_reviewer'],
            synopsis=cve_boilerplate['synopsis'],
            description=cve_boilerplate['description'],
            topic=cve_boilerplate['topic'],
            solution=cve_boilerplate['solution'],
            cves=cves,
        )
        print('List of CVEs: {}'.format(cves))

    highest_impact = get_highest_security_impact(first_fix_flaw_bugs)
    if is_advisory_impact_smaller_than(advisory, highest_impact):
        runtime.logger.info('Adjusting advisory security impact from {} to {}'.format(
            advisory.security_impact, highest_impact
        ))
        advisory.update(security_impact=highest_impact)

    flaw_ids = [flaw_bug.id for flaw_bug in first_fix_flaw_bugs]
    runtime.logger.info('Adding the following BZs to the advisory: {}'.format(flaw_ids))
    advisory.addBugs(flaw_ids)

    return advisory.commit()
