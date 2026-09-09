import json
from pathlib import Path

import click
from pydantic import ValidationError

from panther_journal import cloud
from panther_journal.domain import GameSetup


@click.group()
def game():
    """Create and inspect structured games and their player rosters."""


@game.command("list")
def list_games():
    click.echo(json.dumps(cloud.api(cloud.configuration(), "GET", "/games"), indent=2))


@game.command("show")
@click.argument("game_id")
def show_game(game_id):
    click.echo(
        json.dumps(
            cloud.api(
                cloud.configuration(), "GET", "/game", params={"gameId": cloud.slug(game_id)}
            ),
            indent=2,
        )
    )


@game.command("create")
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def create_game(manifest):
    """Create a game and typed roster atomically from private JSON; never overwrite."""
    if manifest.stat().st_size > 24000:
        raise click.ClickException("Game manifest is too large.")
    try:
        body = GameSetup.model_validate_json(manifest.read_text()).model_dump()
    except (ValueError, ValidationError) as exc:
        raise click.ClickException(f"Invalid game manifest: {exc}") from exc
    click.echo(json.dumps(cloud.api(cloud.configuration(), "POST", "/games", json=body), indent=2))


@click.group()
def player():
    """Inspect structured player identities, distinct from characters and accounts."""


@player.command("list")
def list_players():
    click.echo(json.dumps(cloud.api(cloud.configuration(), "GET", "/players"), indent=2))
