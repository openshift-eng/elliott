from typing import Dict, List, Set
import click
from errata_tool import Erratum

from elliottlib import bzutil, constants
from elliottlib.cli.common import (cli, click_coroutine, find_default_advisory,
                                   use_default_advisory_option)
from elliottlib.errata_async import AsyncErrataAPI, AsyncErrataUtils
from elliottlib.errata import is_security_advisory
from elliottlib.runtime import Runtime
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker, Bug, get_corresponding_flaw_bugs, get_highest_security_impact, is_first_fix_any


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
@click_coroutine
async def attach_cve_flaws_cli(runtime: Runtime, advisory_id: int, noop: bool, default_advisory_type: str):
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
    if not advisory_id and default_advisory_type is not None:
        advisory_id = find_default_advisory(runtime, default_advisory_type)

    runtime.logger.info("Getting advisory %s", advisory_id)
    advisory = Erratum(errata_id=advisory_id)
    if runtime.use_jira:
        await attach_cve_flaws(runtime, advisory_id, advisory, noop, JIRABugTracker(
            JIRABugTracker.get_config(runtime)))
    await attach_cve_flaws(runtime, advisory_id, advisory, noop, BugzillaBugTracker(
        BugzillaBugTracker.get_config(runtime)))


async def attach_cve_flaws(runtime, advisory_id, advisory, noop, bug_tracker):
    # get attached bugs from advisory
    runtime.logger.info("Querying bugs for CVE trackers")
    fields = ["target_release", "blocks", 'whiteboard', 'keywords']
    advisory_bug_ids = bug_tracker.advisory_bug_ids(advisory)
    attached_tracker_bugs = [bug for bug in bug_tracker.get_bugs(advisory_bug_ids, include_fields=fields,
                                                                 permissive=True) if bug.is_tracker_bug()]
    runtime.logger.info(f'Found {len(attached_tracker_bugs)} {bug_tracker.type} tracker bugs attached to the advisory: '
                        f'{sorted(bug.id for bug in attached_tracker_bugs)}')

    if len(attached_tracker_bugs) == 0:
        return

    # validate and get target_release
    current_target_release = Bug.get_target_release(attached_tracker_bugs)
    runtime.logger.info(f'current_target_release: {current_target_release}')

    tracker_flaws, flaw_id_bugs = get_corresponding_flaw_bugs(
        bug_tracker,
        attached_tracker_bugs,
        fields=["depends_on", "alias", "severity", "summary"],
        strict=True
    )
    runtime.logger.info(f'Found {len(flaw_id_bugs)} corresponding flaw bugs: {sorted(flaw_id_bugs.keys())}')

    # current_target_release is digit.digit.[z|0]
    # if current_target_release is GA then run first-fix bug filtering
    # for GA not every flaw bug is considered first-fix
    # for z-stream every flaw bug is considered first-fix
    if current_target_release[-1] == 'z':
        runtime.logger.info("detected z-stream target release, every flaw bug is considered first-fix")
        first_fix_flaw_bugs = list(flaw_id_bugs.values())
    else:
        runtime.logger.info("detected GA release, applying first-fix filtering..")
        first_fix_flaw_bugs = [
            flaw_bug for flaw_bug in flaw_id_bugs.values()
            if is_first_fix_any(bug_tracker, flaw_bug, current_target_release)
        ]

    runtime.logger.info(f'{len(first_fix_flaw_bugs)} out of {len(flaw_id_bugs)} flaw bugs considered "first-fix"')

    if not first_fix_flaw_bugs:
        runtime.logger.info(f'No "first-fix" {bug_tracker.type} bugs found')
        return

    errata_config = runtime.gitdata.load_data(key='erratatool').data
    cve_boilerplate = errata_config['boilerplates']['cve']
    advisory = get_updated_advisory_rhsa(runtime.logger, cve_boilerplate, advisory, first_fix_flaw_bugs)
    if not noop:
        runtime.logger.info("Updating advisory details %s", advisory_id)
        advisory.commit()

    flaw_ids = [flaw_bug.id for flaw_bug in first_fix_flaw_bugs]
    runtime.logger.info(f'Request to attach {len(flaw_ids)} bugs to the advisory')
    existing_bug_ids = bug_tracker.advisory_bug_ids(advisory)
    new_bugs = set(flaw_ids) - set(existing_bug_ids)
    runtime.logger.info(f'Bugs already attached: {len(existing_bug_ids)}')
    runtime.logger.info(f'New bugs ({len(new_bugs)}) : {sorted(new_bugs)}')

    if not noop and new_bugs:
        runtime.logger.info('Attaching bugs %s', flaw_ids)
        bug_tracker.attach_bugs(flaw_ids)

    runtime.logger.info('Associating CVEs with builds')
    errata_api = AsyncErrataAPI(errata_config.get("server", constants.errata_url))
    try:
        await errata_api.login()
        await associate_builds_with_cves(errata_api, advisory, attached_tracker_bugs, tracker_flaws, flaw_id_bugs, noop)
    except ValueError as e:
        click.echo(f"Error associating builds with cves: {e}")
    finally:
        await errata_api.close()


async def associate_builds_with_cves(errata_api: AsyncErrataAPI, advisory: Erratum, attached_tracker_bugs: List[Bug], tracker_flaws: Dict[int, List[int]], flaw_id_bugs: Dict[int, Bug], dry_run: bool):
    attached_builds = [b for pv in advisory.errata_builds.values() for b in pv]
    cve_components_mapping: Dict[str, Set[str]] = {}
    for tracker in attached_tracker_bugs:
        component_name = bzutil.get_whiteboard_component(tracker)
        if not component_name:
            raise ValueError(f"Bug {tracker.id} doesn't have a valid component name in its whiteboard field.")
        flaw_ids = tracker_flaws[tracker.id]
        for flaw_id in flaw_ids:
            if len(flaw_id_bugs[flaw_id].alias) != 1:
                raise ValueError(f"Bug {flaw_id} should have exact 1 alias.")
            cve = flaw_id_bugs[flaw_id].alias[0]
            cve_components_mapping.setdefault(cve, set()).add(component_name)

    await AsyncErrataUtils.associate_builds_with_cves(errata_api, advisory.errata_id, attached_builds, cve_components_mapping, dry_run=dry_run)


def get_updated_advisory_rhsa(logger, cve_boilerplate: dict, advisory: Erratum, flaw_bugs: list):
    """Given an advisory object, get updated advisory to RHSA

    :param logger: logger object from runtime
    :param cve_boilerplate: cve template for rhsa
    :param advisory: advisory object to update
    :param flaw_bugs: flaw bug objects determined to be attached to the advisory
    :returns: updated advisory object, that can be committed i.e advisory.commit()
    """
    if not is_security_advisory(advisory):
        logger.info('Advisory type is {}, converting it to RHSA'.format(advisory.errata_type))
        advisory.update(
            errata_type='RHSA',
            security_reviewer=cve_boilerplate['security_reviewer'],
            synopsis=cve_boilerplate['synopsis'],
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

    highest_impact = get_highest_security_impact(flaw_bugs)
    logger.info('Adjusting advisory security impact from {} to {}'.format(
        advisory.security_impact, highest_impact
    ))
    advisory.update(security_impact=highest_impact)

    if highest_impact not in advisory.topic:
        topic = cve_boilerplate['topic'].format(IMPACT=highest_impact)
        logger.info('Topic updated to include impact of {}'.format(highest_impact))
        advisory.update(topic=topic)

    formatted_cve_list = '\n'.join([
        f'* {b.summary.replace(b.alias[0],"").strip()} ({b.alias[0]})' for b in flaw_bugs
    ])
    formatted_description = cve_boilerplate['description'].format(CVES=formatted_cve_list)
    advisory.update(description=formatted_description)

    return advisory
