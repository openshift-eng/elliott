import click, re
from elliottlib.cli.common import cli
from elliottlib import rhcos, cincinnati, util


@cli.command("rhcos", short_help="Show details about RHCOS packages")
@click.option('--latest', '-l', 'latest',
              is_flag=True,
              help='Show details of latest RHCOS builds')
@click.option('--latest-ocp', '-o', 'latest_ocp',
              is_flag=True,
              help='Show details of RHCOS in latest public OCP release for a given version')
@click.option('--release', '-r', 'release',
              help='Show details for this OCP release. Can be a full pullspec or a named release ex: 4.8.4')
@click.option('--arch', 'arch',
              type=click.Choice(util.brew_arches + ['all']),
              help='Specify architecture. Default is x86_64. "all" to get all arches. aarch64 only works for 4.8+')
@click.option('--packages', '-p', 'packages',
              help='Show details only these packages. Comma separated package names')
@click.option('--go', '-g', 'go',
              is_flag=True,
              help='Show go version for packages that are go binaries')
@click.pass_obj
def rhcos_cli(runtime, latest, latest_ocp, release, packages, arch, go):
    """
    Show details about rhcos packages

    Usage:

\b
    $ elliott rhcos -r registry.ci.openshift.org/ocp-s390x/release-s390x:4.8.0-0.nightly-s390x-2021-07-31-070046

\b
    $ elliott rhcos -r 4.6.31 -p runc --go --arch all

\b
    $ elliott --group openshift-4.8 rhcos -l -p runc

\b
    $ elliott --group openshift-4.8 rhcos -l --arch ppc64le

\b
    $ elliott --group openshift-4.8 rhcos -o -p skopeo,podman --arch all
"""
    count_options = sum(map(bool, [release, latest, latest_ocp]))
    if count_options > 1:
        raise click.BadParameter("Use only one of --from-spec, --latest, --latest-ocp")

    if arch and ('/' in release):
        raise click.BadParameter("--arch=all cannot be used with --release <pullspec>")

    if latest or latest_ocp:
        runtime.initialize()
        major = runtime.group_config.vars.MAJOR
        minor = runtime.group_config.vars.MINOR
        version = f'{major}.{minor}'
    else:
        version = re.search(r'(\d+\.\d+).', release).groups()[0]

    arch = 'x86_64' if not arch else arch

    if arch == 'all':
        for a in util.brew_arches:
            _rhcos(version, release, latest, latest_ocp, packages, a, go)
    else:
        _rhcos(version, release, latest, latest_ocp, packages, arch, go)


def get_pullspec(release, arch):
    return f'quay.io/openshift-release-dev/ocp-release:{release}-{arch}'


def _rhcos(version, release, latest, latest_ocp, packages, arch, go):
    if arch == 'aarch64' and version < '4.9':
        return

    build_id = ''
    pullspec = ''
    if latest or latest_ocp:
        if latest:
            print(f'Looking up latest rhcos build id for {version} {arch}')
            build_id = rhcos.latest_build_id(version, arch)
            print(f'Build id found: {build_id}')
        else:
            print(f'Looking up last ocp release for {version} {arch}')
            release = cincinnati.get_latest_candidate_ocp(version, arch)
            if not release:
                return

    if release:
        if '/' in release:
            pullspec = release
        else:
            print(f'OCP release: {release}-{arch}')
            pullspec = get_pullspec(release, arch)


    if pullspec:
        print(f"Looking up rhcos build id for {pullspec}")
        build_id, arch = rhcos.get_build_from_payload(pullspec)
        print(f'Build id found: {build_id}')

    if build_id:
        nvrs = rhcos.get_rpm_nvrs(build_id, version, arch)
        if not nvrs:
            return
        if packages:
            packages = [p.strip() for p in packages.split(',')]
            nvrs = [p for p in nvrs if p[0] in packages]
        if go:
            util.get_golang_rpm_nvrs(nvrs)
            return
        for nvr in nvrs:
            print('{}-{}-{}'.format(*nvr))
