from elliottlib import logutil
from elliottlib.cli.common import cli
from elliottlib.util import green_prefix
from errata_tool import Erratum, ErrataException
import click
import string
import re

LOGGER = logutil.getLogger(__name__)
supported_update_fields = [
    'publish_date',
    'text_only',
    'text_only_cpe',
    'owner_email',
    'manager_email',
    'manager_id',
    'qe_email',
    'qe_group',
]


@cli.command("advisory-commons", short_help="Show or update advisory commons for a group of advisories")
@click.argument("advisories", nargs=-1, type=click.IntRange(1), required=False)
@click.option("--field",
              help="Advisory field (like publish_date) to show or update. Examples of show only fields: ["
                   "'errata_state', "
                   "'errata_name', 'content_types', 'synopsis', "
                   "'errata_bugs', "
                   "'errata_type']")
@click.option("--new",
              help="New value of field to update advisories with. --field should be one of"
                   f" {supported_update_fields}")
@click.option("--version-replace",
              help="<existing_version>:<new_version>"
                   "Update synopsis, topic, description fields of advisories with new version."
                   "Example --version-replace '4.7.26:4.7.28' ")
@click.option('--yes', '-y', is_flag=True,
              default=False, type=bool,
              help="Update the advisories (by default only a preview is displayed)")
@click.pass_obj
def advisory_commons_cli(runtime, advisories, field, new, version_replace, yes):
    """Display or Change a common field (like date) across multiple advisories.

Advisories created for an OCP version have common fields, that sometimes
will need updating. This command helps with that.

    NOTE: The two advisory input options (--assembly and --advisories)
    are mutually exclusive and can not be used together.

    Show the field "publish_date" for all advisories for an assembly/group/advisories

    $ elliott -g openshift-4.8 --assembly 4.8.8 advisory-commons --field "publish_date"

    $ elliott -g openshift-3.11 advisory-commons --field "publish_date"

    $ elliott advisory-commons 80825 80824 --field "publish_date"

    (Preview) update field "publish_date" for all advisories for an assembly

    $ elliott -g openshift-4.8 --assembly 4.8.8 advisory-commons --field "publish_date" --new "2021-Aug-31"

    (Commit) update field "publish_date" for all advisories for an assembly

    $ elliott -g openshift-4.8 --assembly 4.8.8 advisory-commons --field "publish_date" --new "2021-Aug-31" --yes
"""
    noop = not yes
    count_flags = sum(map(bool, [runtime.group, advisories]))
    if count_flags > 1:
        raise click.BadParameter("Use only one of --group or advisories param")

    count_flags = sum(map(bool, [field, version_replace]))
    if count_flags > 1:
        raise click.BadParameter("Use only one of --field or --version-replace")

    if new:
        if field not in supported_update_fields:
            raise click.BadParameter(f"Only these fields are supported for update: {supported_update_fields}")
    if not advisories:
        runtime.initialize()
        advisories = runtime.group_config.advisories.values()

    errors = []
    for advisory_id in advisories:
        update = False
        try:
            advisory = Erratum(errata_id=advisory_id)
            green_prefix(f"{advisory_id}: ")

            if field:
                current = getattr(advisory, field)
                click.echo(f"{field} = {current}")
            if new:
                if new == current:
                    click.echo(f"No change. New value is same as current value: {field} = {current}")
                else:
                    click.echo(f"Preparing update to {field}: {current} ➔ {new}")
                    advisory = _update_advisory(field, new, advisory)
                    update = True
            elif version_replace:
                rex = r"^(\d.\d+.\d+):(\d.\d+.\d+)$"
                match = re.search(rex, version_replace)
                if not match:
                    click.BadParameter(f"--version-replace needs to be of format {rex}. example '4.5.6:4.7.8'")
                search_version, replace_version = match.groups()

                # special case for description
                f = "description"
                click.echo(f"<{f}>")
                current = getattr(advisory, f)
                lines_to_match = [
                    "This advisory contains the RPM packages for Red Hat OpenShift Container Platform {version}",
                    "quay.io/openshift-release-dev/ocp-release:{version}"
                ]
                for line in lines_to_match:
                    search_line = line.format(version=search_version)
                    if search_line in current:
                        replace_line = line.format(version=replace_version)
                        new_value = current.replace(search_line, replace_line)
                        click.echo(f"Preparing line update: {search_line} ➔ {replace_line}")
                        update = True
                if update:
                    _update_advisory(f, new_value, advisory)
                else:
                    click.echo("No change. New value is same as current value")

                # rest of the fields
                fields = ["synopsis", "topic"]
                for f in fields:
                    click.echo(f"<{f}>")
                    current = getattr(advisory, f)
                    new_value = current.replace(search_version, replace_version)
                    if current == new_value:
                        click.echo("No change. New value is same as current value")
                    else:
                        click.echo(f"Preparing update: {current} ➔ {new_value}")
                        _update_advisory(f, new_value, advisory)
                        update = True

            if not noop and update:
                advisory.commit()
                click.echo("Committed change")
        except ErrataException as ex:
            click.echo(f'Error fetching/changing {advisory_id}: {ex}')
            errors.append(ex)
    if errors:
        raise Exception(errors)


def _update_advisory(field, value, advisory):
    update_kwarg = {}
    if field == 'publish_date':
        update_kwarg['date'] = value
    else:
        update_kwarg[field] = value
    advisory.update(**update_kwarg)
    return advisory
