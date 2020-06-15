# WIP WIP WIP

import bugzilla
import click
import koji
import re

from packaging import version

from elliottlib import brew, constants, Runtime
from elliottlib.cli.common import cli


pass_runtime = click.make_pass_decorator(Runtime)


@cli.command('golang-cve', short_help='...')
@click.option('--flaw-bz-id', required=True)
@click.option('--fixed-in', multiple=True, required=True)
@pass_runtime
def golang_cve_cli(runtime, flaw_bz_id, fixed_in):

    runtime.initialize()

    ocp_version = '{MAJOR}.{MINOR}'.format(**runtime.group_config.vars)
    bugzilla_url = runtime.gitdata.load_data(key='bugzilla').data['server']
    brewhub_url = runtime.group_config.urls.brewhub or constants.BREW_HUB

    bugzilla_api = bugzilla.Bugzilla(bugzilla_url)
    tracker_bugs = get_tracker_bugs(bugzilla_api, flaw_bz_id, ocp_version)

    report = {}
    for bug in tracker_bugs:
        report[extract_component_from_whiteboard(bug.whiteboard)] = {'bug': bug, 'rpms': []}

    brew_session = koji.ClientSession(runtime.group_config.urls.brewhub or constants.BREW_HUB)
    rpm_builds, _ = brew_session.listTaggedRPMS(
        tag=runtime.group_config.build_profiles.rpm.default.targets[0],
        latest=True
    )

    buildroots = {}

    for rpm in rpm_builds:

        if not rpm['buildroot_id'] in buildroots:
            buildroots[rpm['buildroot_id']] = brew_session.getBuildrootListing(rpm['buildroot_id'])

        buildroot = buildroots[rpm['buildroot_id']]
        for dependency in buildroot:
            if dependency['name'] == 'golang' or re.match(r'^go-toolset-\d\.\d{2}$', dependency['name']):
                if rpm['name'] in report:
                    report[rpm['name']]['rpms'].append(rpm)

    for name, item in report.items():
        print(name)
        print('    bug: {} - {}'.format(item['bug'].id, item['bug'].status))
        print('    rpms:')
        for rpm in item['rpms']:
            print('        {}-{}, buildroot {}, arch {}'.format(rpm['name'], rpm['release'], rpm['buildroot_id'], rpm['arch']))
            for dependency in buildroots[rpm['buildroot_id']]:
                if dependency['name'] == 'golang' or re.match(r'^go-toolset-\d\.\d{2}$', dependency['name']):
                    print('            buildroot {} has {}, version {}'.format(rpm['buildroot_id'], dependency['name'], dependency['version']))
                    fixed = False
                    for v in fixed_in:
                        if version.parse(dependency['version']) >= version.parse(v):
                            fixed = True
                    print('            CVE fixed: {}'.format(fixed))
        print()


def get_tracker_bugs(bugzilla_api, flaw_bz_id, ocp_version):
    flaw_bz = bugzilla_api.getbug(flaw_bz_id)
    all_tracker_bugs = bugzilla_api.getbugs(flaw_bz.depends_on)
    tracker_bugs_for_ocp_version = filter(
        lambda bug: only_major_minor(bug.version) == ocp_version,
        all_tracker_bugs
    )
    return list(tracker_bugs_for_ocp_version)


def only_major_minor(version):
    match = re.match(r'(?P<major>\d+)\.(?P<minor>\d+)', version)
    if not match:
        return False
    return '{}.{}'.format(match.group('major'), match.group('minor'))


def extract_component_from_whiteboard(whiteboard_contents):
    return whiteboard_contents.replace('component:', '')
