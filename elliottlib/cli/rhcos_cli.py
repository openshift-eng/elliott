import click
import re
import json
from elliottlib.cli.common import cli
from elliottlib import rhcos, cincinnati, util, exectools


@cli.command("rhcos", short_help="Show details of packages contained in OCP RHCOS builds")
@click.option('--release', '-r', 'release',
              help='Show details for this OCP release. Can be a full pullspec or a named release ex: 4.8.4')
@click.option('--arch', 'arch',
              default='x86_64',
              type=click.Choice(util.brew_arches + ['all']),
              help='Specify architecture. Default is x86_64. "all" to get all arches. aarch64 only works for 4.8+')
@click.option('--packages', '-p', 'packages',
              help='Show details for only these package names (comma-separated)')
@click.option('--go', '-g', 'go',
              is_flag=True,
              help='Show go version for packages that are go binaries')
@click.pass_obj
def rhcos_cli(runtime, release, packages, arch, go):
    """
    Show packages in an RHCOS build in a payload image.
    There are several ways to specify the location of the RHCOS build.

    Usage:

\b Nightly
    $ elliott rhcos -r 4.8.0-0.nightly-s390x-2021-07-31-070046

\b Named Release
    $ elliott rhcos -r 4.6.31

\b Any Pullspec
    $ elliott rhcos -r <pullspec>

\b Assembly Definition
    $ elliott --group openshift-4.8 --assembly 4.8.21 rhcos

\b Only lookup specified package(s)
    $ elliott rhcos -r 4.6.31 -p "openshift,runc,cri-o,selinux-policy"

\b Also lookup go build version (if available)
    $ elliott rhcos -r 4.6.31 -p openshift --go

\b Specify arch (default being x64)
    $ elliott rhcos -r 4.6.31 --arch s390x -p openshift

\b Get all arches (supported only for named release and assembly)
    $ elliott rhcos -r 4.6.31 --arch all -p openshift
"""
    named_assembly = runtime.assembly not in ['stream', 'test']
    count_options = sum(map(bool, [named_assembly, release]))
    if count_options != 1:
        raise click.BadParameter("Use one of --assembly or --release")

    nightly = release and 'nightly' in release
    pullspec = release and '/' in release
    named_release = not (nightly or pullspec or named_assembly)
    if arch == "all" and (pullspec or nightly):
        raise click.BadParameter("--arch=all cannot be used with --release <pullspec> or <*nightly*>")

    if release:
        runtime.initialize(no_group=True)
        major, minor = re.search(r'(\d+)\.(\d+).', release).groups()
        major, minor = int(major), int(minor)
        if nightly:
            for a in util.go_arches:
                if a in release:
                    arch = a
    else:
        runtime.initialize()
        major = runtime.group_config.vars.MAJOR
        minor = runtime.group_config.vars.MINOR

    version = f'{major}.{minor}'
    logger = runtime.logger

    if arch == 'all':
        target_arches = util.brew_arches
        if major == 4 and minor < 9:
            target_arches.remove("aarch64")
    else:
        target_arches = [arch]

    payload_pullspecs = []
    if release:
        if pullspec:
            payload_pullspecs.append(release)
        elif nightly:
            payload_pullspecs.append(get_nightly_pullspec(release, arch))
        elif named_release:
            for local_arch in target_arches:
                p = get_pullspec(release, local_arch)
                payload_pullspecs.append(p)
        build_ids = [get_build_id_from_image_pullspec(p) for p in payload_pullspecs]
    elif named_assembly:
        rhcos_pullspecs = get_rhcos_pullspecs_from_assembly(runtime)
        build_ids = [(get_build_id_from_rhcos_pullspec(p, logger), arch) for arch, p in rhcos_pullspecs.items() if
                     arch in target_arches]

    for build, local_arch in build_ids:
        _via_build_id(build, local_arch, version, packages, go, logger)


def get_pullspec(release, arch):
    return f'quay.io/openshift-release-dev/ocp-release:{release}-{arch}'


def get_nightly_pullspec(release, arch):
    suffix = util.go_suffix_for_arch(arch)
    return f'registry.ci.openshift.org/ocp{suffix}/release{suffix}:{release}'


def get_rhcos_pullspecs_from_assembly(runtime):
    rhcos_def = runtime.releases_config.releases[runtime.assembly].assembly.rhcos
    if not rhcos_def:
        raise click.BadParameter("only named assemblies with valid rhcos values are supported. If an assembly is "
                                 "based on another, try using the original assembly")

    images = rhcos_def['machine-os-content']['images']
    return images


def get_build_id_from_image_pullspec(pullspec):
    util.green_print(f"Image pullspec: {pullspec}")
    build_id, arch = rhcos.get_build_from_payload(pullspec)
    return build_id, arch


def get_build_id_from_rhcos_pullspec(pullspec, logger):
    logger.info(f"Looking up BuildID from RHCOS pullspec: {pullspec}")
    image_info_str, _ = exectools.cmd_assert(f'oc image info -o json {pullspec}', retries=3)
    image_info = json.loads(image_info_str)
    build_id = image_info['config']['config']['Labels']['version']
    if not build_id:
        raise Exception(
            f'Unable to determine build_id from: {pullspec}. Retrieved image info: {image_info_str}')
    return build_id


def _via_build_id(build_id, arch, version, packages, go, logger):
    if not build_id:
        Exception('Cannot find build_id')

    arch = util.brew_arch_for_go_arch(arch)
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
