# -*- coding: utf-8 -*-
"""
Elliott is a CLI tool for managing Red Hat release advisories using the Erratatool
web service.
"""

# -----------------------------------------------------------------------------
# Module dependencies
# -----------------------------------------------------------------------------

# Prepare for Python 3
# stdlib
from __future__ import absolute_import, print_function, unicode_literals
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
import asyncio
import datetime
import json
import os
import re
import sys
import time
from typing import Dict, List

# ours
from elliottlib import version, exectools
from elliottlib import Runtime
import elliottlib.constants
import elliottlib.bzutil
import elliottlib.brew
import elliottlib.errata
import elliottlib.exceptions

from elliottlib.cli import cli_opts
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import exit_unauthenticated, green_prefix, YMD
from elliottlib.util import default_release_date, validate_release_date
from elliottlib.util import validate_email_address, red_print, major_from_branch
from elliottlib.util import green_print, red_prefix, minor_from_branch
from elliottlib.util import yellow_print, yellow_prefix, exit_unauthorized, release_from_branch
from elliottlib.util import progress_func, pbar_header
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory, click_coroutine

# cli commands
from elliottlib.cli.list_cli import list_cli
from elliottlib.cli.tarball_sources_cli import tarball_sources_cli
from elliottlib.cli.find_builds_cli import find_builds_cli
from elliottlib.cli.find_bugs_cli import find_bugs_cli
from elliottlib.cli.create_cli import create_cli
from elliottlib.cli.add_metadata_cli import add_metadata_cli
from elliottlib.cli.create_placeholder_cli import create_placeholder_cli
from elliottlib.cli.change_state_cli import change_state_cli
from elliottlib.cli.puddle_advisories_cli import puddle_advisories_cli
from elliottlib.cli.rpmdiff_cli import rpmdiff_cli
from elliottlib.cli.advisory_images_cli import advisory_images_cli
from elliottlib.cli.advisory_impetus_cli import advisory_impetus_cli
from elliottlib.cli.tag_builds_cli import tag_builds_cli
from elliottlib.cli.verify_cvp_cli import verify_cvp_cli
from elliottlib.cli.advisory_drop_cli import advisory_drop_cli
from elliottlib.cli.verify_attached_operators_cli import verify_attached_operators_cli
from elliottlib.cli.verify_attached_bugs_cli import verify_attached_bugs_cli
from elliottlib.cli.attach_cve_flaws_cli import attach_cve_flaws_cli
from elliottlib.cli.get_golang_versions import get_golang_versions_cli

# 3rd party
import bugzilla
import click
import requests
import errata_tool.build
from errata_tool import Erratum, ErrataException
from kerberos import GSSError


# -----------------------------------------------------------------------------
# Constants and defaults
# -----------------------------------------------------------------------------
pass_runtime = click.make_pass_decorator(Runtime)


# -----------------------------------------------------------------------------
# CLI Commands - Please keep these in alphabetical order
# -----------------------------------------------------------------------------
#
#
# Remove bugs
#
@cli.command("remove-bugs", short_help="Remove provided BUGS from ADVISORY")
@click.option('--advisory', '-a', 'advisory',
              default=False, metavar='ADVISORY',
              help='Remove found bugs from ADVISORY')
@use_default_advisory_option
@click.option("--id", metavar='BUGID', default=[],
              multiple=True, required=True,
              help="Bugzilla IDs to add.")
@pass_runtime
def remove_bugs(runtime, advisory, default_advisory_type, id):
    """Remove given BUGS from ADVISORY.

    Remove bugs that have been attached an advisory:

\b
    $ elliott --group openshift-3.7 remove-bugs --id 123456 --advisory 1234123

    Remove two bugs from default rpm advisory. Note that --group is required
    because default advisory is from ocp-build-data:

\b
    $ elliott --group openshift-3.7 remove-bugs --id 123456 --id 3412311 --use-default-advisory rpm


"""
    if bool(advisory) == bool(default_advisory_type):
        raise click.BadParameter("Specify exactly one of --use-default-advisory or advisory arg")

    runtime.initialize()
    bz_data = runtime.gitdata.load_data(key='bugzilla').data
    bzapi = elliottlib.bzutil.get_bzapi(bz_data)

    bug_ids = [bzapi.getbug(i) for i in cli_opts.id_convert(id)]

    green_prefix("Found {} bugs:".format(len(bug_ids)))
    click.echo(" {}".format(", ".join([str(b.bug_id) for b in bug_ids])))

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    if advisory is not False:
        try:
            advs = Erratum(errata_id=advisory)
        except GSSError:
            exit_unauthenticated()

        if advs is False:
            raise ElliottFatalError("Error: Could not locate advisory {advs}".format(advs=advisory))

        try:
            green_prefix("Removing {count} bugs from advisory:".format(count=len(bug_ids)))
            click.echo(" {advs}".format(advs=advisory))
            advs.removeBugs([bug.id for bug in bug_ids])
            advs.commit()
        except ErrataException as ex:
            raise ElliottFatalError(getattr(ex, 'message', repr(ex)))


#
# Get an Advisory
# advisory:get
#
@cli.command("get", short_help="Get information for an ADVISORY")
@click.argument('advisory', type=int, required=False)
@use_default_advisory_option
@click.option('--details', is_flag=True, default=False,
              help="Print the full object of the advisory")
@click.option('--id-only', is_flag=True, default=False,
              help="Print only the ID of the default advisory")
@click.option('--json', 'as_json', metavar="FILE_NAME",
              help="Dump the advisory as JSON to a file (or '-' for stdout)")
@pass_runtime
@click.pass_context
def get(ctx, runtime, default_advisory_type, details, id_only, as_json, advisory):
    """Get details about a specific advisory from the Errata Tool. By
default a brief one-line informational string is printed. Use the
--details option to fetch and print the full details of the advisory.

Use of --id-only will override all other printing options. Requires
using --use-default-advisory. Only the ID of the advisory is printed
to standard out.

Fields for the short format: Release date, State, Synopsys, URL

    Basic one-line output for advisory 123456:

\b
    $ elliott get 123456
    2018-02-23T18:34:40 NEW_FILES OpenShift Container Platform 3.9 bug fix and enhancement update - https://errata.devel.redhat.com/advisory/123456

    Get the full JSON advisory object, use `jq` to print just the
    errata portion of the advisory:

\b
    $ elliott get --json - 123456 | jq '.errata'
    {
      "rhba": {
        "actual_ship_date": null,
        "assigned_to_id": 3002255,
        "batch_id": null,
        ...
"""

    runtime.initialize(no_group=default_advisory_type is None)

    if bool(advisory) == bool(default_advisory_type):
        raise click.BadParameter("Specify exactly one of --use-default-advisory or advisory arg")
    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type, quiet=True)

    if id_only:
        click.echo(advisory)
        return

    try:
        advisory = Erratum(errata_id=advisory)
    except GSSError:
        exit_unauthenticated()

    if details:
        click.echo(advisory)
        return

    if not as_json:
        advisory_string = "{date} {state} {synopsis} {url}".format(
            date=advisory.publish_date_override,
            state=advisory.errata_state,
            synopsis=advisory.synopsis,
            url=advisory.url())
        click.echo(advisory_string)
        return

    json_data = advisory.get_erratum_data()
    json_data['errata_builds'] = advisory.errata_builds
    json_data['current_flags'] = advisory.current_flags
    json_data['rpmdiffs'] = advisory.externalTests(test_type='rpmdiff')

    if as_json == "-":
        click.echo(json.dumps(json_data, indent=4, sort_keys=True))
        return

    with open(as_json, "w") as json_file:
        json.dump(json_data, json_file, indent=4, sort_keys=True)


#
# Repair bugs
# advisory:repair-bugs
#
@cli.command("repair-bugs", short_help="Move bugs attached to ADVISORY from one state to another")
@click.option("--advisory", "-a",
              metavar='ADVISORY',
              help="Repair bugs attached to ADVISORY.")
@click.option("--auto",
              required=False,
              default=False, is_flag=True,
              help="AUTO mode, check all bugs attached to ADVISORY")
@click.option("--id", default=None, metavar='BUGID',
              multiple=True, required=False,
              help="Bugzilla IDs to modify, conflicts with --auto [MULTIPLE]")
@click.option("--from", "original_state",
              multiple=True,
              default=['MODIFIED'],
              type=click.Choice(elliottlib.constants.VALID_BUG_STATES),
              help="Current state of the bugs (default: MODIFIED)")
@click.option("--to", "new_state",
              default='ON_QA',
              type=click.Choice(elliottlib.constants.VALID_BUG_STATES),
              help="Final state of the bugs (default: ON_QA)")
@click.option("--noop", "--dry-run",
              required=False,
              default=False, is_flag=True,
              help="Check bugs attached, print what would change, but don't change anything")
@use_default_advisory_option
@pass_runtime
def repair_bugs(runtime, advisory, auto, id, original_state, new_state, noop, default_advisory_type):
    """Move bugs attached to the advisory from one state to another
state. This is useful if the bugs have changed states *after* they
were attached. Similar to `find-bugs` but in reverse. `repair-bugs`
begins by reading bugs from an advisory, whereas `find-bugs` reads
from bugzilla.

This looks at attached bugs in the provided --from state and moves
them to the provided --to state.

\b
    Background: This is intended for bugs which went to MODIFIED, were
    attached to advisories, set to ON_QA, and then failed
    testing. When this happens their state is reset back to ASSIGNED.

Using --use-default-advisory without a value set for the matching key
in the build-data will cause an error and elliott will exit in a
non-zero state. Most likely you will only want to use the `rpm` state,
but that could change in the future. Use of this option conflicts with
providing an advisory with the -a/--advisory option.

    Move bugs on 123456 FROM the MODIFIED state back TO ON_QA state:

\b
    $ elliott --group=openshift-4.1 repair-bugs --auto --advisory 123456 --from MODIFIED --to ON_QA

    As above, but using the default RPM advisory defined in ocp-build-data:

\b
    $ elliott --group=openshift-4.1 repair-bugs --auto --use-default-advisory rpm --from MODIFIED --to ON_QA

    The previous examples could also be ran like this (MODIFIED and ON_QA are both defaults):

\b
    $ elliott --group=openshift-4.1 repair-bugs --auto --use-default-advisory rpm

    Bug ids may be given manually instead of using --auto:

\b
    $ elliott --group=openshift-4.1 repair-bugs --id 170899 --id 8675309 --use-default-advisory rpm
"""
    if auto and len(id) > 0:
        raise click.BadParameter("Combining the automatic and manual bug modification options is not supported")

    if not auto and len(id) == 0:
        # No bugs were provided
        raise click.BadParameter("If not using --auto then one or more --id's must be provided")

    if advisory and default_advisory_type:
        raise click.BadParameter("Use only one of --use-default-advisory or --advisory")

    if len(id) == 0 and advisory is None and default_advisory_type is None:
        # error, no bugs, advisory, or default selected
        raise click.BadParameter("No input provided: Must use one of --id, --advisory, or --use-default-advisory")

    # Load bugzilla infomation and get a reference to the api
    runtime.initialize()
    bz_data = runtime.gitdata.load_data(key='bugzilla').data
    bzapi = elliottlib.bzutil.get_bzapi(bz_data)
    changed_bug_count = 0
    attached_bugs = []

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    raw_bug_list = []
    if auto:
        click.echo("Fetching Erratum(errata_id={})".format(advisory))
        e = Erratum(errata_id=advisory)
        raw_bug_list = e.errata_bugs
    else:
        click.echo("Bypassed fetching erratum, using provided BZs")
        raw_bug_list = cli_opts.id_convert(id)

    green_print("Getting bugs for advisory")

    # Fetch bugs in parallel because it can be really slow doing it
    # one-by-one when you have hundreds of bugs
    pbar_header("Fetching data for {} bugs: ".format(len(raw_bug_list)),
                "Hold on a moment, we have to grab each one",
                raw_bug_list)
    pool = ThreadPool(cpu_count())
    click.secho("[", nl=False)

    attached_bugs = pool.map(
        lambda bug: progress_func(lambda: bzapi.getbug(bug), '*'),
        raw_bug_list)
    # Wait for results
    pool.close()
    pool.join()
    click.echo(']')

    green_print("Got bugs for advisory")
    for bug in attached_bugs:
        if bug.status in original_state:
            changed_bug_count += 1
            elliottlib.bzutil.set_state(bug, new_state, noop=noop)

    green_print("{} bugs successfullly modified (or would have been)".format(changed_bug_count))


#
# Search for CVE tracker bugs
#
@cli.command("find-cve-trackers", short_help="Find and list CVE tracker bugs for Security issues.")
@click.option('--cve',
              required=False,
              default=None,
              help="CVE number to filter on. (ex. CVE-2011-1000000)")
@click.option('--status', 'status',
              multiple=True,
              required=False,
              default=['NEW', 'ASSIGNED', 'POST', 'MODIFIED', 'ON_QA', 'VERIFIED', 'RELEASE_PENDING'],
              type=click.Choice(elliottlib.constants.VALID_BUG_STATES),
              help="Status the bugs can be in.")
@pass_runtime
def find_cve_trackers(runtime, cve, status):
    """Find Red Hat Bugzilla security bugs and list them out. Automatic attachment of these
    bugs is not supported because security issues generally need to be hand crafted to make
    sure all requirements are met.

    Usage:
\b
    $ elliott --group openshift-3.7 find-cve-trackers
"""
    runtime.initialize()
    bz_data = runtime.gitdata.load_data(key='bugzilla').data

    click.echo("Searching for bugs with target release(s): {tr}".format(tr=", ".join(bz_data['target_release'])))

    bug_list = elliottlib.bzutil.search_for_security_bugs(bz_data, status, cve=cve, verbose=runtime.debug)

    click.echo("Found {} bugs:".format(len(bug_list)))
    for b in bug_list:
        click.echo("{}\t{:15s}\t{}".format(b.bug_id, b.status, b.summary))

#
# Verify images in a payload match the corresponding advisory
# verify-payload
#


@cli.command("verify-payload", short_help="Verify payload contents match advisory builds")
@click.argument("payload")
@click.argument('advisory', type=int)
@click.pass_context
@click_coroutine
async def verify_payload(ctx, payload, advisory):
    """Cross-check that the builds present in PAYLOAD match the builds
attached to ADVISORY. The payload is treated as the source of
truth. If something is absent or different in the advisory it is
treated as an error with the advisory.

\b
    PAYLOAD - Full pullspec of the payload to verify
    ADVISORY - Numerical ID of the advisory

Two checks are made:

\b
 1. Missing in Advisory - No payload components are absent from the given advisory

 2. Payload Advisory Mismatch - The version-release of each payload item match what is in the advisory

Results are summarily printed at the end of the run. They are also
written out to summary_results.json.

     Verify builds in the given payload match the builds attached to
     advisory 41567

 \b
    $ elliott verify-payload quay.io/openshift-release-dev/ocp-release:4.1.0-rc.6 41567

    """
    all_advisory_nvrs = elliottlib.errata.get_advisory_nvrs(advisory)

    click.echo("Found {} builds".format(len(all_advisory_nvrs)))

    all_payload_nvrs = {}
    click.echo("Fetching release info")
    release_export_cmd = 'oc adm release info {} -o json'.format(payload)

    rc, stdout, stderr = exectools.cmd_gather(release_export_cmd)
    if rc != 0:
        # Probably no point in continuing.. can't contact brew?
        print("Unable to run oc release info: out={}  ; err={}".format(stdout, stderr))
        exit(1)
    else:
        click.echo("Got release info")

    payload_json = json.loads(stdout)

    green_prefix("Looping over payload images: ")
    click.echo("{} images to check".format(len(payload_json['references']['spec']['tags'])))
    cmds = [['oc', 'image', 'info', '-o', 'json', tag['from']['name']] for tag in payload_json['references']['spec']['tags']]

    green_prefix("Querying image infos...")
    cmd_results = await asyncio.gather(*[exectools.cmd_gather_async(cmd) for cmd in cmds])

    for image, cmd, cmd_result in zip(payload_json['references']['spec']['tags'], cmds, cmd_results):
        click.echo("----")
        image_name = image['name']
        rc, stdout, stderr = cmd_result
        if rc != 0:
            # Probably no point in continuing.. can't contact brew?
            red_prefix("Unable to run oc image info: ")
            red_print(f"cmd={cmd!r}, out={stdout}  ; err={stderr}")
            exit(1)

        image_info = json.loads(stdout)
        labels = image_info['config']['config']['Labels']

        # The machine-os-content image doesn't follow the standard
        # pattern. We need to skip that image when we find it, it is
        # not attached to advisories.
        if 'com.coreos.ostree-commit' in labels:
            yellow_prefix("Skipping machine-os-content image: ")
            click.echo("Not required for checks")
            continue

        component = labels['com.redhat.component']
        n = image_name
        click.echo("Payload name: {}".format(n))
        click.echo("Brew name: {}".format(component))
        if labels:
            v = labels['version']
            r = labels['release']
            all_payload_nvrs[component] = "{}-{}".format(v, r)
        else:
            print("For image {} Labels doesn't exist, image_info: {}".format(image_name, image_info))

    missing_in_errata = {}
    payload_doesnt_match_errata = {}
    in_pending_advisory = []
    in_shipped_advisory = []
    output = {
        'missing_in_advisory': missing_in_errata,
        'payload_advisory_mismatch': payload_doesnt_match_errata,
        "in_pending_advisory": in_pending_advisory,
        "in_shipped_advisory": in_shipped_advisory,
    }

    green_prefix("Analyzing data: ")
    click.echo("{} images to consider from payload".format(len(all_payload_nvrs)))

    for image, vr in all_payload_nvrs.items():
        yellow_prefix("Cross-checking from payload: ")
        click.echo("{}-{}".format(image, vr))
        if image not in all_advisory_nvrs:
            missing_in_errata[image] = "{}-{}".format(image, vr)
            click.echo("{} in payload not found in advisory".format("{}-{}".format(image, vr)))
        elif image in all_advisory_nvrs and vr != all_advisory_nvrs[image]:
            click.echo("{} from payload has version {} which does not match {} from advisory".format(
                image, vr, all_advisory_nvrs[image]))
            payload_doesnt_match_errata[image] = {
                'payload': vr,
                'errata': all_advisory_nvrs[image]
            }

    if missing_in_errata:  # check if missing images are already shipped or pending to ship
        advisory_nvrs: Dict[int, List[str]] = {}  # a dict mapping advisory numbers to lists of NVRs
        green_print(f"Checking if {len(missing_in_errata)} missing images are shipped...")
        for nvr in missing_in_errata.copy().values():
            # get the list of advisories that this build has been attached to
            build = elliottlib.errata.get_brew_build(nvr)
            # filter out dropped advisories
            advisories = [ad for ad in build.all_errata if ad["status"] != "DROPPED_NO_SHIP"]
            if not advisories:
                red_print("Build {nvr} is not attached to any advisories.")
                continue
            for advisory in advisories:
                if advisory["status"] == "SHIPPED_LIVE":
                    green_print(f"Missing build {nvr} has been shipped with advisory {advisory}.")
                else:
                    yellow_print(f"Missing build {nvr} is in another pending advisory.")
                advisory_nvrs.setdefault(advisory["id"], []).append(nvr)
            name = nvr.rsplit("-", 2)[0]
            del missing_in_errata[name]
        if advisory_nvrs:
            click.echo(f"Getting information of {len(advisory_nvrs)} advisories...")
            for advisory, nvrs in advisory_nvrs.items():
                advisory_obj = elliottlib.errata.get_raw_erratum(advisory)
                adv_type, adv_info = next(iter(advisory_obj["errata"].items()))
                item = {
                    "id": advisory,
                    "type": adv_type.upper(),
                    "url": elliottlib.constants.errata_url + f"/{advisory}",
                    "summary": adv_info["synopsis"],
                    "state": adv_info["status"],
                    "nvrs": nvrs,
                }
                if adv_info["status"] == "SHIPPED_LIVE":
                    in_shipped_advisory.append(item)
                else:
                    in_pending_advisory.append(item)

    green_print("Summary results:")
    click.echo(json.dumps(output, indent=4))
    with open('summary_results.json', 'w') as fp:
        json.dump(output, fp, indent=4)
    green_prefix("Wrote out summary results: ")
    click.echo("summary_results.json")

#
# Poll for rpm-signed state change
# poll-signed
#


@cli.command("poll-signed", short_help="Poll for RPM build 'signed' status")
@click.option("--minutes", "-m", required=False,
              default=15, type=int,
              help="How long to poll before quitting")
@click.option("--advisory", "-a",
              metavar='ADVISORY',
              help="Advisory to watch")
@use_default_advisory_option
@click.option("--noop", "--dry-run",
              required=False,
              default=False, is_flag=True,
              help="Don't actually poll, just print the signed status of each build")
@pass_runtime
def poll_signed(runtime, minutes, advisory, default_advisory_type, noop):
    """Poll for the signed-status of RPM builds attached to
ADVISORY. Returns rc=0 when all builds have been signed. Returns non-0
after MINUTES have passed and all builds have not been signed. This
non-0 return code is the number of unsigned builds remaining. All
builds must show 'signed' for this command to succeed.

    NOTE: The two advisory options are mutually exclusive.

For testing in pipeline scripts this sub-command accepts a --noop
option. When --noop is used the value of --minutes is irrelevant. This
command will print out the signed state of all attached builds and
then exit with rc=0 if all builds are signed and non-0 if builds are
still unsigned. In the non-0 case the return code is the number of
unsigned builds.

    Wait 15 minutes for the default 4.2 advisory to show all RPMS have
    been signed:

    $ elliott -g openshift-4.2 poll-signed --use-default-advisory rpm

    Wait 5 mintes for the provided 4.2 advisory to show all RPMs have
    been signed:

    $ elliott -g openshift-4.2 poll-signed -m 5 --advisory 123456

    Print the signed status of all attached builds, exit
    immediately. Return code is the number of unsigned builds.

\b
    $ elliott -g openshift-4.2 poll-signed --noop --use-default-advisory rpm
"""
    if not (bool(advisory) ^ bool(default_advisory_type)):
        raise click.BadParameter("Use only one of --use-default-advisory or --advisory")

    runtime.initialize(no_group=default_advisory_type is None)

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    if not noop:
        click.echo("Polling up to {} minutes for all RPMs to be signed".format(minutes))

    try:
        e = Erratum(errata_id=advisory)
        all_builds = set([])
        all_signed = False
        # `errata_builds` is a dict with brew tags as keys, values are
        # lists of builds on the advisory with that tag
        for k, v in e.errata_builds.items():
            all_builds = all_builds.union(set(v))
        green_prefix("Fetching initial states: ")
        click.echo("{} builds to check".format(len(all_builds)))
        start_time = datetime.datetime.now()
        while datetime.datetime.now() - start_time < datetime.timedelta(minutes=minutes):
            pbar_header("Getting build signatures: ",
                        "Should be pretty quick",
                        all_builds)
            pool = ThreadPool(cpu_count())
            # Look up builds concurrently
            click.secho("[", nl=False)

            build_sigs = pool.map(
                lambda build: progress_func(
                    lambda: elliottlib.errata.build_signed(build),
                    '*'),
                all_builds)
            # Wait for results
            pool.close()
            pool.join()
            click.echo(']')

            if all(build_sigs):
                all_signed = True
                break
            elif noop:
                # Escape the time-loop
                break
            else:
                yellow_prefix("Not all builds signed: ")
                click.echo("re-checking")
                continue

        if not all_signed:
            red_prefix("Signing incomplete: ")
            if noop:
                click.echo("All builds not signed. ")
            else:
                click.echo("All builds not signed in given window ({} minutes). ".format(minutes))
                exit(1)
        else:
            green_prefix("All builds signed: ")
            click.echo("Enjoy!")
    except ErrataException as ex:
        raise ElliottFatalError(getattr(ex, 'message', repr(ex)))


# Register additional commands / groups
cli.add_command(add_metadata_cli)
cli.add_command(advisory_images_cli)
cli.add_command(advisory_impetus_cli)
cli.add_command(create_placeholder_cli)
cli.add_command(create_cli)
cli.add_command(change_state_cli)
cli.add_command(find_bugs_cli)
cli.add_command(find_builds_cli)
cli.add_command(list_cli)
cli.add_command(puddle_advisories_cli)
cli.add_command(rpmdiff_cli)
cli.add_command(tag_builds_cli)
cli.add_command(tarball_sources_cli)
cli.add_command(verify_cvp_cli)
cli.add_command(advisory_drop_cli)
cli.add_command(verify_attached_operators_cli)
cli.add_command(verify_attached_bugs_cli)
cli.add_command(attach_cve_flaws_cli)


# -----------------------------------------------------------------------------
# CLI Entry point
# -----------------------------------------------------------------------------


def main():
    try:
        cli(obj={})
    except ElliottFatalError as ex:
        # Allow capturing actual tool errors and print them
        # nicely instead of a gross stack-trace.
        # All internal errors that should simply cause the app
        # to exit with an error code should use ElliottFatalError
        red_print(getattr(ex, 'message', repr(ex)))
        sys.exit(1)


if __name__ == '__main__':
    main()
