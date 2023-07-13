from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.util import green_prefix
from errata_tool import Erratum, ErrataException
import click


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
@click.pass_obj
def change_state_cli(runtime, state, advisory, default_advisories, default_advisory_type, noop):
    """Change the state of an ADVISORY. Additional permissions may be
required to change an advisory to certain states.

An advisory may not move between some states until all criteria have
been met. For example, an advisory can not move from NEW_FILES to QE
unless Bugzilla Bugs or JIRA Issues have been attached.

    NOTE: The two advisory options are mutually exclusive and can not
    be used together.

    Move assembly release advisories to QE

    $ elliott -g openshift-4.10 --assembly 4.10.4 change-state -s QE

    Move the advisory 123456 to QE:

    $ elliott change-state --state QE --advisory 123456

    Move the advisory 123456 back to NEW_FILES (short option flag):

    $ elliott change-state -s NEW_FILES -a 123456

    Do not actually change state, just check the command could run

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
