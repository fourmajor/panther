"""Explicit narrative organization through Panther, never direct AWS mutations."""

import json
from pathlib import Path

import click

from panther_journal import cloud
from panther_journal.character_details import pages, read_json
from panther_journal.illustration_planning import command as plan_illustrations


@click.group()
def novels():
    """Read and organize private stories, books and explicitly selected chapter editions."""


def listing(kind):
    @click.command(kind)
    @click.option("--game", required=True)
    @click.option("--id", "identity")
    @click.option("--revision", help="Read an exact earlier organization revision; requires --id.")
    def command(game, identity, revision):
        config = cloud.configuration()
        params = {"gameId": cloud.slug(game)}
        if identity:
            params["id"] = cloud.slug(identity)
            if revision:
                params["revision"] = revision
            result = cloud.api(config, "GET", "/novel-" + kind, params=params)
        elif revision:
            raise click.ClickException("--revision requires --id")
        else:
            result = {"records": pages(config, "/novel-" + kind, params, "records")}
        click.echo(json.dumps(result, indent=2))

    return command


def saving(kind):
    @click.command("save-" + kind)
    @click.argument("manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def command(manifest):
        body = read_json(manifest)
        if not isinstance(body, dict) or not body.get("operationId"):
            raise click.ClickException("Use a complete guarded envelope with a stable operationId.")
        click.echo(f"Operation: {body['operationId']}", err=True)
        click.echo(
            json.dumps(
                cloud.api(
                    cloud.configuration(),
                    "POST",
                    {
                        "story": "/novel-stories",
                        "book": "/novel-books",
                        "illustrations": "/novel-illustrations",
                    }[kind],
                    json=body,
                ),
                indent=2,
            )
        )

    return command


for command in [
    listing("stories"),
    listing("books"),
    listing("illustrations"),
    saving("story"),
    saving("book"),
    saving("illustrations"),
    plan_illustrations,
]:
    novels.add_command(command)
