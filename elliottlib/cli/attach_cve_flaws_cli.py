import bugzilla, click, re
from errata_tool import Erratum
from elliottlib import util, attach_cve_flaws
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory


@cli.command('attach-cve-flaws',
             short_help='Attach corresponding flaw bugs for trackers in advisory (first-fix only)')
@click.option('--advisory', '-a', 'advisory_id',
              type=int,
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
    if sum(map(bool, [advisory_id, default_advisory_type])) != 1:
        raise click.BadParameter("Use one of --use-default-advisory or --advisory")
    runtime.initialize()
    bzurl = runtime.gitdata.bz_server_url()
    bzapi = bugzilla.Bugzilla(bzurl)

    if not advisory_id and default_advisory_type is not None:
        advisory_id = find_default_advisory(runtime, default_advisory_type)

    advisory = Erratum(errata_id=advisory_id)

    # get attached bugs from advisory
    attached_tracker_bugs = attach_cve_flaws.get_tracker_bugs(bzapi, advisory, fields=["target_release", "blocks"])
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

    corresponding_flaw_bugs = attach_cve_flaws.get_corresponding_flaw_bugs(
        bzapi,
        attached_tracker_bugs,
        fields=["depends_on", "alias", "severity"]
    )
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
        first_fix_flaw_bugs = [
            flaw_bug for flaw_bug in corresponding_flaw_bugs
            if attach_cve_flaws.is_first_fix_any(bzapi, flaw_bug, current_target_release)
        ]

    runtime.logger.info('{} out of {} flaw bugs considered "first-fix"'.format(
        len(first_fix_flaw_bugs), len(corresponding_flaw_bugs),
    ))

    if not first_fix_flaw_bugs:
        runtime.logger.info('No "first-fix" bugs found, exiting')
        exit(0)

    cve_boilerplate = runtime.gitdata.load_data(key='erratatool').data['boilerplates']['cve']
    advisory = get_updated_advisory_rhsa(runtime.logger, cve_boilerplate, advisory, first_fix_flaw_bugs)

    flaw_ids = [flaw_bug.id for flaw_bug in first_fix_flaw_bugs]
    runtime.logger.info(f'Request to attach {len(flaw_ids)} bugs to the advisory')
    existing_bug_ids = advisory.errata_bugs
    new_bugs = set(flaw_ids) - set(existing_bug_ids)
    runtime.logger.info(f'Bugs already attached: {len(existing_bug_ids)}')
    runtime.logger.info(f'New bugs ({len(new_bugs)}) : {sorted(new_bugs)}')

    if new_bugs:
        advisory.addBugs(flaw_ids)
    if noop:
        return True

    return advisory.commit()


def get_updated_advisory_rhsa(logger, cve_boilerplate, advisory, flaw_bugs):
    """Given an advisory object, get updated advisory to RHSA

    :param logger: logger object from runtime
    :param cve_boilerplate: cve template for rhsa
    :param advisory: advisory object to update
    :param flaw_bugs: flaw bug objects determined to be attached to the advisory
    :returns: updated advisory object, that can be committed i.e advisory.commit()
    """
    if not attach_cve_flaws.is_security_advisory(advisory):
        logger.info('Advisory type is {}, converting it to RHSA'.format(advisory.errata_type))
        advisory.update(
            errata_type='RHSA',
            security_reviewer=cve_boilerplate['security_reviewer'],
            synopsis=cve_boilerplate['synopsis'],
            description=cve_boilerplate['description'],
            topic=cve_boilerplate['topic'].format(IMPACT="Low"),
            solution=cve_boilerplate['solution'],
            security_impact='Low',
        )

    cve_names = [b.alias[0] for b in flaw_bugs]
    if not advisory.cve_names:
        cve_str = ' '.join(cve_names)
        advisory.update(cve_names=cve_str)
    else:
        cves_not_in_cve_names = [n for n in cve_names if n not in advisory.cve_names]
        if cves_not_in_cve_names:
            s = ' '.join(cves_not_in_cve_names)
            cve_str = f"{advisory.cve_names} {s}".strip()
            advisory.update(cve_names=cve_str)

    highest_impact = attach_cve_flaws.get_highest_security_impact(flaw_bugs)
    logger.info('Adjusting advisory security impact from {} to {}'.format(
        advisory.security_impact, highest_impact
    ))
    advisory.update(security_impact=highest_impact)

    if highest_impact not in advisory.topic:
        topic = cve_boilerplate['topic'].format(IMPACT=highest_impact)
        logger.info('Topic updated to include impact of {}'.format(highest_impact))
        advisory.update(topic=topic)

    return advisory
