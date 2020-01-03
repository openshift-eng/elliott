from __future__ import absolute_import, print_function, unicode_literals
import click
import re

from elliottlib import Runtime, errata, logutil, constants, util
from elliottlib.rpmdiff import RPMDiffClient
from elliottlib.exceptions import ElliottFatalError


@click.group("rpmdiff", short_help="Show or waive RPMDiff failures")
@click.pass_context
def rpmdiff_cli(ctx):
    pass


@rpmdiff_cli.command()
@click.argument("advisory", metavar='ADVISORY', type=click.IntRange(1), required=False)
@click.pass_context
def show(ctx, advisory):
    """ Show RPMDiff failures for an advisory.
    """
    runtime = ctx.obj  # type: Runtime
    if not advisory:
        runtime.initialize()
        advisory = runtime.group_config.advisories.get("rpm", 0)
        if not advisory:
            raise ElliottFatalError("No RPM advisory number configured in ocp-build-data.")
    else:
        runtime.initialize(no_group=True)
    logger = runtime.logger
    logger.info("Fetching RPMDiff runs from Errata Tool for advisory {}...".format(advisory))
    rpmdiff_runs = list(errata.get_rpmdiff_runs(advisory))
    logger.info("Found {} RPMDiff runs.".format(len(rpmdiff_runs)))
    # "good" means PASSED, INFO, or WAIVED
    good_runs = []
    # "bad" means NEEDS_INSPECTION or FAILED
    bad_runs = []
    incomplete_runs = []
    for rpmdiff_run in rpmdiff_runs:
        attr = rpmdiff_run['attributes']
        if attr["status"] in constants.ET_GOOD_EXTERNAL_TEST_STATUSES:
            good_runs.append(rpmdiff_run)
        elif attr["status"] in constants.ET_BAD_EXTERNAL_TEST_STATUSES:
            bad_runs.append(rpmdiff_run)
        else:
            incomplete_runs.append(rpmdiff_run)
    util.green_prefix("good: {}".format(len(good_runs)))
    click.echo(", ", nl=False)
    util.red_prefix("bad: {}".format(len(bad_runs)))
    click.echo(", ", nl=False)
    util.yellow_print("incomplete: {}".format(len(incomplete_runs)))

    if not bad_runs:
        return

    logger.info("Fetching detailed information from RPMDiff for bad RPMDiff runs...")
    rpmdiff_client = RPMDiffClient(constants.RPMDIFF_HUB_URL)
    rpmdiff_client.authenticate()
    for run in bad_runs:
        attr = run["attributes"]
        run_id = attr["external_id"]
        run_url = "{}/run/{}/".format(constants.RPMDIFF_WEB_URL, run_id)
        print("----------------")
        msg = "{0} {1}".format(run["relationships"]["brew_build"]["nvr"], attr["status"])
        if attr["status"] == "NEEDS_INSPECTION":
            util.yellow_print(msg)
        else:
            util.red_print(msg)
        test_results = rpmdiff_client.get_test_results(run_id)
        run_obj = rpmdiff_client.get_run(run_id)

        for result in test_results:
            score = result["score"]
            if score >= 0 and score < 3:  # good test result
                continue
            result_id = result["result_id"]
            test = result["test"]
            details = result["details"]
            test_id = test["test_id"]
            package_name = run_obj["package_name"]
            result_url = run_url + str(test_id) + "/"
            result_msg = "* TEST {0} {2} {1} {3}".format(result_id, constants.RPMDIFF_SCORE_NAMES[score], test["description"], result_url)
            if score == 3:  # NEEDS_INSPECTION
                util.yellow_print(result_msg)
            else:
                util.red_print(result_msg)
            # get last waiver message
            waivers = rpmdiff_client.list_waivers(package_name, test_id, limit=1)
            if waivers:
                util.green_print("    Last waiver: @" + waivers[0]["owner"]["username"] + ": " + waivers[0]["description"])
            else:
                util.yellow_print("    No last waiver found.")
            for detail in details:
                detail_msg = "    * {1} {0}".format(constants.RPMDIFF_SCORE_NAMES[detail["score"]], detail["subpackage"])
                if detail["score"] == 3:
                    util.yellow_print(detail_msg)
                else:
                    util.red_print(detail_msg)
                content = re.sub('^', '        ', detail["content"], flags=re.MULTILINE)
                print(content)
        print()
