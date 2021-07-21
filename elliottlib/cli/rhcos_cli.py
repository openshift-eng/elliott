import click
from elliottlib.cli.common import cli
from elliottlib import rhcos, cincinnati, util


@cli.command("rhcos", short_help="Show details about RHCOS packages")
@click.option('--from-spec', '-s', 'pullspec',
              help='Show details of RHCOS in the given payload pullspec')
@click.option('--latest', '-l', 'latest',
              is_flag=True,
              help='Show details of latest RHCOS builds')
@click.option('--latest-ocp', '-o', 'latest_ocp',
              is_flag=True,
              help='Show details of RHCOS in latest public OCP release for a given version')
@click.option('--packages', '-p', 'packages',
              help='Show details only these packages. Comma separated package names')
@click.option('--arch', 'arch',
              type=click.Choice(util.brew_arches + ['all']),
              help='Specify architecture. Default is x86_64. "all" to get all arches. aarch64 only works for 4.8+')
@click.option('--go', '-g', 'go',
              is_flag=True,
              help='Show go version for packages that are go binaries')
@click.pass_obj
def rhcos_cli(runtime, pullspec, latest, latest_ocp, packages, arch, go):
    """
    Show details about rhcos packages

    Usage:

\b
    $ elliott --group openshift-4.6 rhcos -s quay.io/openshift-release-dev/ocp-release:4.6.31-x86_64

\b
    $ elliott --group openshift-4.8 rhcos -l -p runc

\b
    $ elliott --group openshift-4.8 rhcos -l --arch ppc64le

\b
    $ elliott --group openshift-4.8 rhcos -o -p skopeo,podman --arch all
"""
    count_options = sum(map(bool, [pullspec, latest, latest_ocp]))
    if count_options > 1:
        raise click.BadParameter("Use only one of --from-spec, --latest, --latest-ocp")

    if arch and not (latest or latest_ocp):
        raise click.BadParameter("--arch can only be used with --latest, --latest-ocp")

    runtime.initialize()
    major = runtime.group_config.vars.MAJOR
    minor = runtime.group_config.vars.MINOR
    version = f'{major}.{minor}'
    arch = 'x86_64' if not arch else arch

    if arch == 'all':
        for a in util.brew_arches:
            _rhcos(version, pullspec, latest, latest_ocp, packages, a, go)
    else:
        _rhcos(version, pullspec, latest, latest_ocp, packages, arch, go)


def _rhcos(version, pullspec, latest, latest_ocp, packages, arch, go):
    if arch == 'aarch64' and version < '4.8':
        return

    build_id = ''
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
            print(f'OCP release found: {release}')
            pullspec = f'quay.io/openshift-release-dev/ocp-release:{release}-{arch}'

    if pullspec:
        print(f"Looking up rhcos build id for {pullspec}")
        build_id, arch = rhcos.get_build_from_payload(pullspec)
        print(f'Build id found: {build_id}')

    if build_id:
        nvrs = rhcos.get_rpm_nvrs(build_id, version, arch)
        if packages:
            packages = [p.strip() for p in packages.split(',')]
            nvrs = [p for p in nvrs if p[0] in packages]
        if go:
            util.get_golang_rpm_nvrs(nvrs)
            return
        for nvr in nvrs:
            print('{}-{}-{}'.format(*nvr))
