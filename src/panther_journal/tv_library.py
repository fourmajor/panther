"""Guarded TV organization through the existing Panther sign-in."""

import json
from pathlib import Path

import click

from panther_journal import cloud
from panther_journal.character_details import pages, read_json


def listing(kind):
    @click.command(kind)
    @click.option("--game", required=True)
    @click.option("--id", "identity")
    @click.option("--revision", help="Read exact organization history; requires --id.")
    def command(game, identity, revision):
        config = cloud.configuration()
        params = {"gameId": cloud.slug(game)}
        path = "/tv-series" if kind == "series" else "/tv-episodes"
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


def saving(kind):
    @click.command("save-" + kind)
    @click.argument("manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def command(manifest):
        body = read_json(manifest)
        if not isinstance(body, dict) or not body.get("operationId"):
            raise click.ClickException("Use a complete guarded envelope with a stable operationId.")
        click.echo(f"TV organization operation: {body['operationId']}", err=True)
        click.echo(
            json.dumps(
                cloud.api(
                    cloud.configuration(),
                    "POST",
                    "/tv-series" if kind == "series" else "/tv-episodes",
                    json=body,
                ),
                indent=2,
            )
        )

    return command


def register(group):
    for command in [listing("series"), listing("episodes"), saving("series"), saving("episode")]:
        group.add_command(command)
