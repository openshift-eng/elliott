import bugzilla, click, re
from errata_tool import Erratum
from elliottlib import util
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.attach_cve_flaws import get_attached_tracker_bugs, \
    get_corresponding_flaw_bugs, is_first_fix, is_security_advisory, \
    get_highest_security_impact, is_advisory_impact_smaller_than


@cli.command('attach-cve-flaws',
             short_help='Attach corresponding flaw bugs for trackers in advisory (first-fix only)')
@click.option('--advisory', '-a', 'advisory_id',
              default=False,
              help='Find tracker bugs in given advisory')
@click.option("--noop", "--dry-run",
              required=False,
              default=False, is_flag=True,
              help="Print what would change, but don't change anything")
@use_default_advisory_option
@click.pass_obj
def attach_cve_flaws_cli(runtime, advisory_id, noop, default_advisory_type):
    """Attach corresponding flaw bugs for trackers in advisory (first-fix only).

    Also converts advisory to RHSA, if not already.

    Example:

    $ elliott --group openshift-4.6 attach-cve-flaws --use-default-advisory image
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
    bzurl = runtime.gitdata.bz_server_url()
    bzapi = bugzilla.Bugzilla(bzurl)

    if not advisory_id and default_advisory_type is not None:
        advisory_id = find_default_advisory(runtime, default_advisory_type)

    # get attached bugs from advisory
    attached_tracker_bugs = get_attached_tracker_bugs(bzapi, advisory_id)
    runtime.logger.info('found {} tracker bugs attached to the advisory: {}'.format(
        len(attached_tracker_bugs), sorted(bug.id for bug in attached_tracker_bugs)
    ))
    if len(attached_tracker_bugs) == 0:
        exit(0)

    # validate and get target_release
    current_target_release, err = util.get_target_release(attached_tracker_bugs)
    if err:
        runtime.logger.error(err)
        exit(1)
    runtime.logger.info('current_target_release: {}'.format(current_target_release))

    corresponding_flaw_bugs = get_corresponding_flaw_bugs(bzapi, attached_tracker_bugs)
    runtime.logger.info('found {} corresponding flaw bugs: {}'.format(
        len(corresponding_flaw_bugs), sorted(bug.id for bug in corresponding_flaw_bugs)
    ))

    # current_target_release is digit.digit.[z|0]
    # if current_target_release is GA then run first-fix bug filtering
    # for GA not every flaw bug is considered first-fix
    # for z-stream every flaw bug is considered first-fix
    if current_target_release[-1] == 'z':
        runtime.logger.info("detected z-stream target release, every flaw bug is considered first-fix")
        first_fix_flaw_bugs = corresponding_flaw_bugs
    else:
        runtime.logger.info("detected GA release, applying first-fix filtering..")
        attached_tracker_ids = [tracker.id for tracker in attached_tracker_bugs]
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
        advisory.update(
            errata_type='RHSA',
            security_reviewer=cve_boilerplate['security_reviewer'],
            synopsis=cve_boilerplate['synopsis'],
            description=cve_boilerplate['description'],
            topic=cve_boilerplate['topic'],
            solution=cve_boilerplate['solution'],
            security_impact='Low',
        )

    cves = ' '.join([flaw_bug.alias[0] for flaw_bug in first_fix_flaw_bugs])

    cve_str = cves
    if advisory.cve_names and cves not in advisory.cve_names:
        cve_str = "{} {}".format(advisory.cve_names, cves).strip()
    advisory.update(cve_names=cve_str)
    runtime.logger.info('List of *new* CVEs: {}'.format(cves))

    highest_impact = get_highest_security_impact(first_fix_flaw_bugs)
    if is_advisory_impact_smaller_than(advisory, highest_impact):
        runtime.logger.info('Adjusting advisory security impact from {} to {}'.format(
            advisory.security_impact, highest_impact
        ))
        advisory.update(security_impact=highest_impact)

    flaw_ids = [flaw_bug.id for flaw_bug in first_fix_flaw_bugs]
    runtime.logger.info('Adding the following BZs to the advisory: {}'.format(flaw_ids))
    advisory.addBugs(flaw_ids)

    if noop:
        print('DRY-RUN: The following changes would have been applied to the advisory:')
        print(advisory)
        return True

    return advisory.commit()
