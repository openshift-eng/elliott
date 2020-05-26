from __future__ import absolute_import, print_function, unicode_literals

from elliottlib import logutil, Runtime
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import green_prefix, green_print

from errata_tool import Erratum, ErrataException
import click

LOGGER = logutil.getLogger(__name__)

pass_runtime = click.make_pass_decorator(Runtime)


#
# Set advisory state
# change-state
#
@cli.command("change-state", short_help="Change ADVISORY state")
@click.option("--state", '-s', required=True,
              type=click.Choice(['NEW_FILES', 'QE', 'REL_PREP']),
              help="New state for the Advisory. NEW_FILES, QE, REL_PREP")
@click.option("--advisory", "-a", metavar='ADVISORY', type=int,
              help="Change state of ADVISORY")
@use_default_advisory_option
@click.option("--noop", "--dry-run",
              required=False,
              default=False, is_flag=True,
              help="Do not actually change anything")
@pass_runtime
def change_state_cli(runtime, state, advisory, default_advisory_type, noop):
    """Change the state of an ADVISORY. Additional permissions may be
required to change an advisory to certain states.

An advisory may not move between some states until all criteria have
been met. For example, an advisory can not move from NEW_FILES to QE
unless Bugzilla Bugs or JIRA Issues have been attached.

    NOTE: The two advisory options are mutually exclusive and can not
    be used together.

See the find-bugs help for additional information on adding
Bugzilla Bugs.

    Move the advisory 123456 from NEW_FILES to QE state:

    $ elliott change-state --state QE --advisory 123456

    Move the advisory 123456 back to NEW_FILES (short option flag):

    $ elliott change-state -s NEW_FILES -a 123456

    Do not actually change state, just check that the command could
    have ran (for example, when testing out pipelines)

    $ elliott change-state -s NEW_FILES -a 123456 --noop
"""
    if not (bool(advisory) ^ bool(default_advisory_type)):
        raise click.BadParameter("Use only one of --use-default-advisory or --advisory")

    runtime.initialize(no_group=default_advisory_type is None)

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    if noop:
        prefix = "[NOOP] "
    else:
        prefix = ""

    try:
        e = Erratum(errata_id=advisory)

        if e.errata_state == state:
            green_prefix("{}No change to make: ".format(prefix))
            click.echo("Target state is same as current state")
            return
        # we have 5 different states we can only change the state if it's in NEW_FILES or QE
        # "NEW_FILES",
        # "QE",
        # "REL_PREP",
        # "PUSH_READY",
        # "IN_PUSH"
        if e.errata_state != 'NEW_FILES' and e.errata_state != 'QE':
            if default_advisory_type is not None:
                raise ElliottFatalError("Error: Could not change '{state}' advisory {advs}, group.yml is probably pointing at old one".format(state=e.errata_state, advs=advisory))
            else:
                raise ElliottFatalError("Error: we can only change the state if it's in NEW_FILES or QE, current state is {s}".format(s=e.errata_state))
        else:
            if noop:
                green_prefix("{}Would have changed state: ".format(prefix))
                click.echo("{} ➔ {}".format(e.errata_state, state))
                return
            else:
                # Capture current state because `e.commit()` will
                # refresh the `e.errata_state` attribute
                old_state = e.errata_state
                e.setState(state)
                e.commit()
                green_prefix("Changed state: ")
                click.echo("{old_state} ➔ {new_state}".format(
                    old_state=old_state,
                    new_state=state))
    except ErrataException as ex:
        raise ElliottFatalError(getattr(ex, 'message', repr(ex)))

    green_print("Successfully changed advisory state")
