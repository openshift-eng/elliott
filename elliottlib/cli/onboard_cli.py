import re
import sys

import click
from ruamel.yaml import YAML

from elliottlib.cli.common import cli, click_coroutine, pass_runtime
from elliottlib.runtime import Runtime

yaml = YAML()


@cli.group("onboard", short_help="Helpers for onboarding an image or rpm")
@click_coroutine
async def onboard_cli():
    """ Helper command for onboarding an image or rpm with with OCP production build managed by ART.
    """
    pass


@onboard_cli.command("new-image")
@pass_runtime
@click_coroutine
async def new_image_cli(runtime: Runtime):
    """ Generate an image metadata for ocp-build-data.
    """
    source_repo_url = input("Source github repo: ").strip()
    source_repo_url_pattern = re.compile(r"^(?:(?:https://|ssh://git@)github\.com/|git@github\.com:)openshift(?:-priv)?/([\w-]+)(?:\.git)?$")
    match = source_repo_url_pattern.fullmatch(source_repo_url)
    if not match:
        click.echo("Invalid source github repo. The repo must be in the Github openshift org: https://source.redhat.com/groups/public/atomicopenshift/atomicopenshift_wiki/guidelines_for_requesting_new_content_managed_by_ocp_art#first-onboard-your-component-with-dptp-ci", file=sys.stderr)
        exit(1)
    source_repo_name = match[1]
    source_repo_url = f"git@github.com:openshift-priv/{source_repo_name}.git"

    is_golang = input("Is this a golang image [Y/n]?").strip().lower() in {"", "y", "yes"}

    distgit_repo_url = input("Dist-Git URL: ").strip()
    distgit_repo_url_pattern = re.compile(r"(?:containers/)?([\w-]+)(?:\.git)?$")
    if not distgit_repo_url_pattern.search(distgit_repo_url):
        click.echo("Invalid ditgit repo. See https://source.redhat.com/groups/public/atomicopenshift/atomicopenshift_wiki/guidelines_for_requesting_new_content_managed_by_ocp_art#jive_content_id_You_must_make_Comet_requests_first", file=sys.stderr)
        exit(1)

    owner_emails_text = input("Owner emails (seperated by space): ").strip()
    owner_emails = []
    for email in owner_emails_text.split():
        # TODO: email format check
        owner_emails.append(email)

    if not owner_emails:
        click.echo("Invalid owner emails. See https://source.redhat.com/groups/public/atomicopenshift/atomicopenshift_wiki/guidelines_for_requesting_new_content_managed_by_ocp_art#jive_content_id_Review_OWNERS_file", file=sys.stderr)
        exit(1)

    dockerfile_path = input("Dockerfile path (/Dockerfile): ").strip() or "Dockerfile"
    if dockerfile_path.startswith(("/", "./")):
        dockerfile_path = dockerfile_path.split("/", 1)[1]

    image_name = input("Image name (openshift/ose-foo-bar): ").strip()
    image_name_pattern = re.compile(r"^(?:openshift/)?([\w-]+)$")
    match = image_name_pattern.match(image_name)
    if not match:
        click.echo("Invalid image name.", file=sys.stderr)
        exit(1)
    image_name = f"openshift/{match[1]}"

    for_payload = input("Is this a CVO payload [N/y]?").strip().lower() in {"y", "yes"}
    if for_payload and not image_name.startswith("openshift/ose-"):
        click.echo("Payload image name must start with 'openshift/ose-'.", file=sys.stderr)
        exit(1)

    image_meta = {
        "mode": "wip",
        "content": {
            "source": {
                "git": {
                    "url": source_repo_url,
                    "branch": {
                        "target": "release-{MAJOR}.{MINOR}"
                    }
                },
                "dockerfile": dockerfile_path
            }
        },
        "name": image_name,
        "for_payload": for_payload,
        "owners": owner_emails,
    }
    if is_golang:
        image_meta["container_yaml"] = {
            "go": {
                "modules": [
                    {
                        "module": f"github.com/openshift/{source_repo_name}"
                    }
                ]
            }
        }

    yaml.dump(image_meta, stream=sys.stdout)

    pass
