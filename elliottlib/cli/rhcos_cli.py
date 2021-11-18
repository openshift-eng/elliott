import click
import re
import json
from elliottlib.cli.common import cli
from elliottlib import rhcos, cincinnati, util, exectools


@cli.command("rhcos", short_help="Show details of packages contained in OCP RHCOS builds")
@click.option('--latest', '-l', 'latest',
              is_flag=True,
              help='Show details of latest RHCOS builds')
@click.option('--latest-ocp', '-o', 'latest_ocp',
              is_flag=True,
              help='Show details of RHCOS in latest OCP release (fast channel) for a given version')
@click.option('--release', '-r', 'release',
              help='Show details for this OCP release. Can be a full pullspec or a named release ex: 4.8.4')
@click.option('--arch', 'arch',
              default=None,
              type=click.Choice(util.brew_arches + ['all']),
              help='Specify architecture. Default is x86_64. "all" to get all arches. aarch64 only works for 4.8+')
@click.option('--packages', '-p', 'packages',
              help='Show details for only these package names (comma-separated)')
@click.option('--go', '-g', 'go',
              is_flag=True,
              help='Show go version for packages that are go binaries')
@click.pass_obj
def rhcos_cli(runtime, latest, latest_ocp, release, packages, arch, go):
    """
    Show details of packages contained in OCP RHCOS builds, for either
    the latest RHCOS build or the machine-os-content included in a release image.

    Usage:

\b Pullspec
    $ elliott rhcos -r registry.ci.openshift.org/ocp-s390x/release-s390x:4.8.0-0.nightly-s390x-2021-07-31-070046

\b Nightly
    $ elliott rhcos -r registry.ci.openshift.org/ocp-s390x/release-s390x:4.8.0-0.nightly-s390x-2021-07-31-070046

\b Named Release
    $ elliott rhcos -r 4.6.31 -p runc --go --arch all

\b Assembly Definition
    $ elliott --group openshift-4.8 --assembly 4.8.21 rhcos -p container-selinux

\b Latest RHCOS Build
    $ elliott --group openshift-4.8 rhcos -l -p runc --arch s390x

\b Latest Named Release
    $ elliott --group openshift-4.8 rhcos -o -p skopeo,podman --arch all
"""
    version = ''
    named_assembly = runtime.assembly != 'stream'
    count_options = sum(map(bool, [named_assembly, release, latest, latest_ocp]))
    if count_options != 1:
        raise click.BadParameter("Use one of --assembly, --release, --latest, --latest-ocp")

    def _via_release():
        nonlocal arch, version
        nightly = 'nightly' in release
        if arch and release and ('/' in release or nightly):
            raise click.BadParameter("--arch=all cannot be used with --release <pullspec> or <*nightly*>")

        runtime.initialize(no_group=True)
        version = re.search(r'(\d+\.\d+).', release).groups()[0]
        if nightly:
            for a in util.go_arches:
                if a in release:
                    arch = a

    def _via_latest():
        nonlocal version
        runtime.initialize()
        major = runtime.group_config.vars.MAJOR
        minor = runtime.group_config.vars.MINOR
        version = f'{major}.{minor}'

    rhcos_pullspecs = {}
    if arch == 'all':
        target_arches = util.brew_arches
    else:
        target_arches = [arch]

    def _via_assembly():
        nonlocal arch, rhcos_pullspecs, version
        if not arch:
            raise click.BadParameter("--assembly needs --arch <>")

        runtime.initialize()
        major = runtime.group_config.vars.MAJOR
        minor = runtime.group_config.vars.MINOR
        version = f'{major}.{minor}'
        rhcos_def = runtime.releases_config.releases[runtime.assembly].assembly.rhcos
        if not rhcos_def:
            raise click.BadParameter("only named assemblies with valid rhcos values are supported. If an assembly is "
                                     "based on another, try using the original assembly")

        images = rhcos_def['machine-os-content']['images']

        for a in target_arches:
            if a in images:
                rhcos_pullspecs[a] = images[a]

    if release:
        _via_release()
    elif runtime.assembly:
        _via_assembly()
    else:
        _via_latest()

    logger = runtime.logger
    arch = 'x86_64' if not arch else arch

    for local_arch in target_arches:
        build_id = get_build_id(version, release, latest, latest_ocp, rhcos_pullspecs.get(local_arch), local_arch,
                                logger)
        _via_build_id(build_id, local_arch, version, packages, go, logger)


def get_pullspec(release, arch):
    return f'quay.io/openshift-release-dev/ocp-release:{release}-{arch}'


def get_nightly_pullspec(release, arch):
    suffix = util.go_suffix_for_arch(arch)
    return f'registry.ci.openshift.org/ocp{suffix}/release{suffix}:{release}'


def get_build_id(version, release, latest, latest_ocp, rhcos_pullspec, arch, logger):
    if arch == 'aarch64' and version < '4.9':
        return

    if latest:
        logger.info(f'Looking up latest RHCOS Build for {version} {arch}')
        build_id = rhcos.latest_build_id(version, arch)
        logger.info(f'Build found: {build_id}')
        return build_id

    if latest_ocp:
        logger.info(f'Looking up last OCP Release for {version} {arch} in fast channel')
        release = cincinnati.get_latest_fast_ocp(version, arch)
        if not release:
            return

    if release:
        if '/' in release:
            payload_pullspec = release
        else:
            if 'nightly' in release:
                logger.info(f'OCP Nightly: {release}-{arch}')
                payload_pullspec = get_nightly_pullspec(release, arch)
            else:
                logger.info(f'OCP Release: {release}-{arch}')
                payload_pullspec = get_pullspec(release, arch)

        logger.info(f"Looking up RHCOS Build for {payload_pullspec}")
        build_id, arch = rhcos.get_build_from_payload(payload_pullspec)
        logger.info(f'Build found: {build_id}')
        return build_id

    if rhcos_pullspec:
        image_info_str, _ = exectools.cmd_assert(f'oc image info -o json {rhcos_pullspec}', retries=3)
        image_info = json.loads(image_info_str)
        build_id = image_info['config']['config']['Labels']['version']
        if not build_id:
            raise Exception(
                f'Unable to determine build_id from: {rhcos_pullspec}. Retrieved image info: {image_info_str}')
        return build_id


def _via_build_id(build_id, arch, version, packages, go, logger):
    if not build_id:
        Exception('Cannot find build_id')

    util.green_print(f'Build: {build_id} Arch: {arch}')
    nvrs = rhcos.get_rpm_nvrs(build_id, version, arch)
    if not nvrs:
        return
    if packages:
        packages = [p.strip() for p in packages.split(',')]
        if 'openshift' in packages:
            packages.remove('openshift')
            packages.append('openshift-hyperkube')
        nvrs = [p for p in nvrs if p[0] in packages]
    if go:
        go_rpm_nvrs = util.get_golang_rpm_nvrs(nvrs, logger)
        util.pretty_print_nvrs_go(go_rpm_nvrs, ignore_na=True)
        return
    for nvr in sorted(nvrs):
        print('-'.join(nvr))
