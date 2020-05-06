from __future__ import absolute_import, print_function, unicode_literals
from future.builtins import str
import os
import errno
import shutil
import koji
import errata_tool
import tempfile
import pipes
import click
from typing import List, Set, Dict, Tuple, Text, Optional
from elliottlib import constants, tarball_sources, util, logutil, brew

LOGGER = logutil.getLogger(__name__)


@click.group("tarball-sources", short_help="Create or publish tarball sources")
@click.pass_context
def tarball_sources_cli(ctx):
    runtime = ctx.obj
    runtime.initialize(no_group=True)


@tarball_sources_cli.command()
@click.argument("advisories", nargs=-1, type=click.IntRange(1), required=True)
@click.option("--out-dir", type=click.Path(), default="./", help="Output directory for tarball sources.")
@click.option("--out-layout", type=click.Choice(["hierarchical", "flat"]),
              default="hierarchical", show_default=True,
              help="Layout of output directory.")
@click.option("--component", "components", multiple=True, help="Koji/Brew component names or build NVRs to filter on. Can be specified multiple times.")
@click.option("-f", "--force", is_flag=True, help="Force overwrite existing files.")
@click.pass_context
def create(ctx, advisories, out_dir, out_layout, components, force):
    """ Create tarball sources for advisories.

    To create tarball sources for Brew component (package) logging-fluentd-container that was shipped on advisories 45606, 45527, and 46049:
    $ elliott tarball-sources create --component logging-fluentd-container --out-dir=out/ 45606 45527 46049
    """

    if not force and os.path.isdir(out_dir) and os.listdir(out_dir):
        util.red_print(
            "Output directory {} is not empty.\n\
Use --force to add new tarball sources to an existing directory.".format(os.path.abspath(out_dir)))
        exit(1)
    mkdirs(out_dir)

    working_dir = os.path.join(ctx.obj.working_dir, "tarball-sources")
    LOGGER.debug("Use working directory {}.".format(
        os.path.abspath(working_dir)))
    mkdirs(working_dir)

    # `nvr_dirs` is a dict with brew build NVRs as keys, values are
    # a set of directories for the generated tarballs,
    # since a build can be attached to multiple advisories.
    # For example:
    # nvr_dirs = {
    #   "logging-fluentd-container-v3.11.141-2": {
    #     "RHOSE/RHEL-7-OSE-3.11/45606/release/"
    #   },
    #   "logging-fluentd-container-v4.1.14-201908291507": {
    #     "RHOSE/RHEL-7-OSE-4.1/45527/release/"
    #   },
    #   "logging-fluentd-container-v4.1.15-201909041605": {
    #     "RHOSE/RHEL-7-OSE-4.1/46049/release/"
    #   }
    # }
    nvr_dirs = {}  # type: Dict[str, Set[str]]

    # Getting build NVRs for specified Koji/Brew components from advisories
    # NOTE This is SLOW. However doing this in parallel doesn't work
    # due to a race condition existing in the implementation of `errata_tool.Erratum`'s parant class ErrataConnector.
    for advisory in advisories:
        click.echo(
            "Finding builds from advisory {}...".format(advisory))
        builds = tarball_sources.find_builds_from_advisory(
            advisory, components)
        if not builds:
            util.yellow_print(
                "No matched builds found from advisory {}. Wrong advisory number?".format(advisory))
            continue
        util.green_print(
            "Found {} matched build(s) from advisory {}".format(len(builds), advisory))
        for nvr, product, product_version in builds:
            util.green_print("\t{}\t{}\t{}".format(
                nvr, product, product_version))

        for nvr, product, product_version in builds:
            if nvr not in nvr_dirs:
                nvr_dirs[nvr] = set()
            if out_layout == "flat":
                nvr_dirs[nvr].add(out_dir)
            else:
                nvr_dirs[nvr].add(os.path.join(
                    out_dir, product_version, str(advisory), "release"))

    if not nvr_dirs:
        util.red_print("Exiting because no matched builds from all specified advisories.")
        exit(1)

    # Check build infos from Koji/Brew
    # in order to figure out the source Git repo and commit hash for each build.
    click.echo("Fetching build infos for {} from Koji/Brew...".format(
        ", ".join(nvr_dirs.keys())))
    brew_session = koji.ClientSession(constants.BREW_HUB)
    brew_builds = brew.get_build_objects(nvr_dirs.keys(), brew_session)

    # Ready to generate tarballs
    tarball_sources_list = []
    for build_info in brew_builds:
        nvr = build_info["nvr"]
        tarball_filename = nvr + ".tar.gz"
        click.echo("Generating tarball source {} for {}...".format(
            tarball_filename, nvr))

        with tempfile.NamedTemporaryFile(suffix="-" + tarball_filename, dir=working_dir) as temp_tarball:
            temp_tarball_path = temp_tarball.name
            LOGGER.debug(
                "Temporary tarball file is {}".format(temp_tarball_path))

            tarball_sources.generate_tarball_source(temp_tarball, nvr + "/", os.path.join(working_dir, "repos", build_info["name"]),
                                                    build_info["source"])
            for dest_dir in nvr_dirs[nvr]:
                mkdirs(dest_dir)
                tarball_abspath = os.path.abspath(
                    os.path.join(dest_dir, tarball_filename))
                if os.path.exists(tarball_abspath):
                    util.yellow_print(
                        "File {} will be overwritten.".format(tarball_abspath))

                LOGGER.debug("Copying {} to {}...".format(
                    temp_tarball_path, tarball_abspath))
                shutil.copyfile(temp_tarball_path, tarball_abspath)  # `shutil.copyfile` uses default umask
                tarball_sources_list.append(tarball_abspath)
                util.green_print(
                    "Created tarball source {}.".format(tarball_abspath))

    print_success_message(tarball_sources_list, out_dir)


def mkdirs(path):
    """ Make sure a directory exists. Similar to shell command `mkdir -p`.

    This function will not be necessary when fully migrated to Python 3.
    """
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno != errno.EEXIST:  # ignore if dest_dir exists
            raise


def print_success_message(tarball_sources_list, out_dir):
    relative_paths = [os.path.join(os.path.relpath(os.path.dirname(
        path), out_dir), os.path.basename(path)) for path in tarball_sources_list]
    relative_paths.sort()

    util.green_print("""

All tarball sources are successfully created.

To send all tarball sources to rcm-guest, run:

    rsync -avz --no-perms --no-owner --no-group {} ocp-build@rcm-guest.app.eng.bos.redhat.com:/mnt/rcm-guest/ocp-client-handoff/

Then notify RCM (https://projects.engineering.redhat.com/projects/RCM/issues) that the following tarball sources have been uploaded to rcm-guest:

{}
    """.format(pipes.quote(os.path.abspath(out_dir) + "/"), "\n".join(relative_paths)))
