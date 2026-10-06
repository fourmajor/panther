"""Read-only access to historical TV organization through Panther sign-in."""

import json
from pathlib import Path

import click

from panther_journal import cloud
from panther_journal.character_details import pages


def listing(kind):
    @click.command(kind)
    @click.option("--game", required=True)
    @click.option("--id", "identity")
    @click.option("--revision", help="Read exact organization history; requires --id.")
    def command(game, identity, revision):
        config = cloud.configuration()
        params = {"gameId": cloud.slug(game)}
        path = {"series": "/tv-series", "legacy-episodes": "/tv-episodes", "episodes": "/episodes"}[kind]
        if identity:
            params["id"] = cloud.slug(identity)
            if revision:
                params["revision"] = revision
            result = cloud.api(config, "GET", path, params=params)
        elif revision:
            raise click.ClickException("--revision requires --id")
        else:
            result = {"records": pages(config, path, params, "records")}
        click.echo(json.dumps(result, indent=2))

    return command


def register(group):
    for command in [listing("series"), listing("legacy-episodes"), listing("episodes")]:
        group.add_command(command)
    group.add_command(propose_storyboard)


@click.command("propose-storyboard")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def propose_storyboard(file):
    """Publish a guarded scene-owned AI proposal; never approve it or generate video."""
    try:
        if file.stat().st_size > 64 * 1024:
            raise ValueError("Proposal is too large")
        body = json.loads(file.read_text("utf-8"))
        required = {"gameId", "episodeId", "id", "name", "expectedRevision", "operationId", "storyboardProposalShots"}
        if not isinstance(body, dict) or not required <= set(body) <= required | {"description"}:
            raise ValueError("Use a guarded scene envelope with storyboardProposalShots")
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from error
    result = cloud.api(cloud.configuration(), "POST", "/scenes", json=body)
    click.echo(json.dumps(result, indent=2))
