
from elliottlib import logutil, Runtime
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import green_prefix, red_prefix

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
@click.option("--default-advisories",
              is_flag=True,
              help="Change state of all advisories of specified group")
@use_default_advisory_option
@click.option("--noop", "--dry-run",
              is_flag=True,
              default=False,
              help="Do not actually change anything")
@pass_runtime
def change_state_cli(runtime, state, advisory, default_advisories, default_advisory_type, noop):
    """Change the state of an ADVISORY. Additional permissions may be
required to change an advisory to certain states.

An advisory may not move between some states until all criteria have
been met. For example, an advisory can not move from NEW_FILES to QE
unless Bugzilla Bugs or JIRA Issues have been attached.

    NOTE: The two advisory options are mutually exclusive and can not
    be used together.

See the find-bugs help for additional information on adding
Bugzilla Bugs.

    Move assembly release advisories to QE

    $ elliott -g openshift-4.10 --assembly 4.10.4 change-state -s QE

    Move group release advisories to QE:

    $ elliott -g openshift-4.5 change-state -s QE --default-advisories

    Move the advisory 123456 to QE:

    $ elliott change-state --state QE --advisory 123456

    Move the advisory 123456 back to NEW_FILES (short option flag):

    $ elliott change-state -s NEW_FILES -a 123456

    Do not actually change state, just check that the command could
    have ran (for example, when testing out pipelines)

    $ elliott change-state -s NEW_FILES -a 123456 --noop
"""
    count_flags = sum(map(bool, [advisory, default_advisory_type, default_advisories]))
    if count_flags > 1:
        raise click.BadParameter("Use only one of --use-default-advisory or --advisory or --default-advisories")

    runtime.initialize(no_group=bool(advisory))

    advisories = []
    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    if advisory:
        advisories.append(advisory)

    if not advisories:
        advisories = list(runtime.group_config.advisories.values())

    click.echo(f"Attempting to move advisories {advisories} to {state}")
    errors = []
    for advisory in advisories:
        try:
            e = Erratum(errata_id=advisory)

            if e.errata_state == state:
                green_prefix(f"No Change ({advisory}): ")
                click.echo(f"Target state is same as current state: {state}")
            # we have 5 different states we can only change the state if it's in NEW_FILES or QE
            # "NEW_FILES",
            # "QE",
            # "REL_PREP",
            # "PUSH_READY",
            # "IN_PUSH"
            elif e.errata_state != 'NEW_FILES' and e.errata_state != 'QE':
                red_prefix(f"Error ({advisory}): ")
                if default_advisory_type is not None:
                    click.echo(f"Could not change '{e.errata_state}', group.yml is probably pointing at old one")
                else:
                    click.echo(f"Can only change the state if it's in NEW_FILES or QE, current state is {e.errata_state}")
            else:
                if noop:
                    green_prefix(f"NOOP ({advisory}): ")
                    click.echo(f"Would have changed state {e.errata_state} ➔ {state}")
                else:
                    # Capture current state because `e.commit()` will
                    # refresh the `e.errata_state` attribute
                    old_state = e.errata_state
                    e.setState(state)
                    e.commit()
                    green_prefix(f"Changed state ({advisory}): ")
                    click.echo(f"{old_state} ➔ {state}")
        except ErrataException as ex:
            click.echo(f'Error fetching/changing state of {advisory}: {ex}')
            errors.append(ex)

    if errors:
        raise Exception(errors)
