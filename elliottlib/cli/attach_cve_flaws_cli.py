from typing import Dict, List, Set
import click
import sys
import traceback
import asyncio
from errata_tool import Erratum

from elliottlib import constants
from elliottlib.cli.common import (cli, click_coroutine, find_default_advisory,
                                   use_default_advisory_option)
from elliottlib.errata_async import AsyncErrataAPI, AsyncErrataUtils
from elliottlib.errata import is_security_advisory
from elliottlib.runtime import Runtime
from elliottlib.bzutil import Bug, get_highest_security_impact, is_first_fix_any, JIRABugTracker


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
@click.option("--into-default-advisories",
              is_flag=True,
              help='Run for all advisories values defined in [group|releases].yml')
@click.pass_obj
@click_coroutine
async def attach_cve_flaws_cli(runtime: Runtime, advisory_id: int, noop: bool, default_advisory_type: str, into_default_advisories: bool):
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
    if sum(map(bool, [advisory_id, default_advisory_type, into_default_advisories])) != 1:
        raise click.BadParameter("Use one of --use-default-advisory or --advisory or --into-default-advisories")
    runtime.initialize()
    if into_default_advisories:
        advisories = runtime.group_config.advisories.values()
    elif default_advisory_type:
        advisories = [find_default_advisory(runtime, default_advisory_type)]
    else:
        advisories = [advisory_id]

    # Flaw bugs associated with jira tracker bugs
    # exist in bugzilla. so to work with jira trackers
    # we need both bugzilla and jira instances initialized
    if runtime.only_jira:
        runtime.use_jira = True

    exit_code = 0
    for advisory_id in advisories:
        runtime.logger.info("Getting advisory %s", advisory_id)
        advisory = Erratum(errata_id=advisory_id)

        tasks = []
        for bug_tracker in runtime.bug_trackers.values():
            flaw_bug_tracker = runtime.bug_trackers['bugzilla']
            tasks.append(asyncio.get_event_loop().create_task(get_flaws(runtime, advisory, bug_tracker,
                                                              flaw_bug_tracker, noop)))
        try:
            lists_of_flaw_bugs = await asyncio.gather(*tasks)
            flaw_bugs = list(set(sum(lists_of_flaw_bugs, [])))
            if flaw_bugs:
                bug_tracker = runtime.bug_trackers['bugzilla']
                _update_advisory(runtime, advisory, flaw_bugs, bug_tracker, noop)
        except Exception as e:
            runtime.logger.error(traceback.format_exc())
            runtime.logger.error(f'Exception: {e}')
            exit_code = 1
    sys.exit(exit_code)


async def get_flaws(runtime, advisory, bug_tracker, flaw_bug_tracker, noop):
    # get attached bugs from advisory
    advisory_bug_ids = bug_tracker.advisory_bug_ids(advisory)
    if not advisory_bug_ids:
        runtime.logger.info(f'Found 0 {bug_tracker.type} bugs attached')
        return []

    attached_tracker_bugs: List[Bug] = bug_tracker.get_tracker_bugs(advisory_bug_ids, verbose=runtime.debug)
    runtime.logger.info(f'Found {len(attached_tracker_bugs)} {bug_tracker.type} tracker bugs attached: '
                        f'{sorted([b.id for b in attached_tracker_bugs])}')
    if not attached_tracker_bugs:
        return []

    # validate and get target_release
    current_target_release = Bug.get_target_release(attached_tracker_bugs)
    tracker_flaws, flaw_id_bugs = bug_tracker.get_corresponding_flaw_bugs(
        attached_tracker_bugs,
        flaw_bug_tracker,
        strict=True
    )
    runtime.logger.info(f'Found {len(flaw_id_bugs)} {flaw_bug_tracker.type} corresponding flaw bugs:'
                        f' {sorted(flaw_id_bugs.keys())}')

    # current_target_release is digit.digit.[z|0]
    # if current_target_release is GA then run first-fix bug filtering
    # for GA not every flaw bug is considered first-fix
    # for z-stream every flaw bug is considered first-fix
    if current_target_release[-1] == 'z':
        runtime.logger.info("Detected z-stream target release, every flaw bug is considered first-fix")
        first_fix_flaw_bugs = list(flaw_id_bugs.values())
    else:
        runtime.logger.info("Detected GA release, applying first-fix filtering..")
        first_fix_flaw_bugs = [
            flaw_bug for flaw_bug in flaw_id_bugs.values()
            if is_first_fix_any(flaw_bug_tracker, flaw_bug, current_target_release)
        ]

    runtime.logger.info(f'{len(first_fix_flaw_bugs)} out of {len(flaw_id_bugs)} flaw bugs considered "first-fix"')
    if not first_fix_flaw_bugs:
        return []

    runtime.logger.info('Associating CVEs with builds')
    errata_config = runtime.gitdata.load_data(key='erratatool').data
    errata_api = AsyncErrataAPI(errata_config.get("server", constants.errata_url))
    try:
        await errata_api.login()
        await associate_builds_with_cves(errata_api, advisory, attached_tracker_bugs, tracker_flaws, flaw_id_bugs, noop)
    except ValueError as e:
        runtime.logger.warn(f"Error associating builds with cves: {e}")
    finally:
        await errata_api.close()
    return first_fix_flaw_bugs


def _update_advisory(runtime, advisory, flaw_bugs, bug_tracker, noop):
    advisory_id = advisory.errata_id
    errata_config = runtime.gitdata.load_data(key='erratatool').data
    cve_boilerplate = errata_config['boilerplates']['cve']
    advisory, updated = get_updated_advisory_rhsa(runtime.logger, cve_boilerplate, advisory, flaw_bugs)
    if not noop and updated:
        runtime.logger.info("Updating advisory details %s", advisory_id)
        advisory.commit()

    flaw_ids = [flaw_bug.id for flaw_bug in flaw_bugs]
    runtime.logger.info(f'Attaching {len(flaw_ids)} flaw bugs')
    bug_tracker.attach_bugs(advisory_id, flaw_ids, noop)


async def associate_builds_with_cves(errata_api: AsyncErrataAPI, advisory: Erratum, attached_tracker_bugs: List[Bug], tracker_flaws, flaw_id_bugs: Dict[int, Bug], dry_run: bool):
    attached_builds = [b for pv in advisory.errata_builds.values() for b in pv]
    cve_components_mapping: Dict[str, Set[str]] = {}
    for tracker in attached_tracker_bugs:
        component_name = tracker.whiteboard_component
        if not component_name:
            raise ValueError(f"Bug {tracker.id} doesn't have a valid whiteboard component.")
        flaw_ids = tracker_flaws[tracker.id]
        for flaw_id in flaw_ids:
            if len(flaw_id_bugs[flaw_id].alias) != 1:
                raise ValueError(f"Bug {flaw_id} should have exactly 1 alias.")
            cve = flaw_id_bugs[flaw_id].alias[0]
            cve_components_mapping.setdefault(cve, set()).add(component_name)

    await AsyncErrataUtils.associate_builds_with_cves(errata_api, advisory.errata_id, attached_builds, cve_components_mapping, dry_run=dry_run)


def get_updated_advisory_rhsa(logger, cve_boilerplate: dict, advisory: Erratum, flaw_bugs):
    """Given an advisory object, get updated advisory to RHSA

    :param logger: logger object from runtime
    :param cve_boilerplate: cve template for rhsa
    :param advisory: advisory object to update
    :param flaw_bugs: Collection of flaw bug objects to be attached to the advisory
    :returns: updated advisory object and a boolean indicating if advisory was updated
    """
    updated = False
    if not is_security_advisory(advisory):
        logger.info('Advisory type is {}, converting it to RHSA'.format(advisory.errata_type))
        updated = True
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
        updated = True
    else:
        cves_not_in_cve_names = [n for n in cve_names if n not in advisory.cve_names]
        if cves_not_in_cve_names:
            s = ' '.join(cves_not_in_cve_names)
            cve_str = f"{advisory.cve_names} {s}".strip()
            advisory.update(cve_names=cve_str)
            updated = True

    if updated:
        formatted_cve_list = '\n'.join([
            f'* {b.summary.replace(b.alias[0], "").strip()} ({b.alias[0]})' for b in flaw_bugs
        ])
        formatted_description = cve_boilerplate['description'].format(CVES=formatted_cve_list)
        advisory.update(description=formatted_description)

    highest_impact = get_highest_security_impact(flaw_bugs)
    if highest_impact != advisory.security_impact:
        logger.info(f'Adjusting advisory security impact from {advisory.security_impact} to {highest_impact}')
        advisory.update(security_impact=highest_impact)
        updated = True

    if highest_impact not in advisory.topic:
        topic = cve_boilerplate['topic'].format(IMPACT=highest_impact)
        logger.info('Topic updated to include impact of {}'.format(highest_impact))
        advisory.update(topic=topic)

    return advisory, updated
