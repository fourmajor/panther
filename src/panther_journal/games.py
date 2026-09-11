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


@game.command("set-ruleset")
@click.argument("game_id")
@click.option("--ruleset", required=True, help="Game system name and edition, not rule text.")
@click.option("--if-unset", is_flag=True, help="Only assign when no ruleset is recorded yet.")
@click.option(
    "--expected-ruleset", help="Exact currently recorded value; refuse concurrent changes."
)
def set_ruleset(game_id, ruleset, if_unset, expected_ruleset):
    """Set only a game's ruleset name, preserving roster and assets."""
    if if_unset == (expected_ruleset is not None):
        raise click.UsageError("Choose exactly one of --if-unset or --expected-ruleset.")
    if not 1 <= len(ruleset) <= 120:
        raise click.BadParameter("Ruleset must contain 1–120 characters.")
    try:
        GameSetup.ruleset_name(ruleset)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    body = {
        "gameId": cloud.slug(game_id),
        "ruleset": ruleset,
        "expectedRuleset": None if if_unset else expected_ruleset,
    }
    click.echo(
        json.dumps(cloud.api(cloud.configuration(), "POST", "/game/ruleset", json=body), indent=2)
    )


@player.command("list")
def list_players():
    click.echo(json.dumps(cloud.api(cloud.configuration(), "GET", "/players"), indent=2))


@game.command("set-style")
@click.argument("game_id")
@click.option("--style", required=True, help="Visual style ID from game show.")
@click.option("--if-unset", is_flag=True)
@click.option("--expected-style", help="Exact prior style; refuse concurrent changes.")
def set_style(game_id, style, if_unset, expected_style):
    """Change future visual direction without rewriting or regenerating assets."""
    if if_unset == (expected_style is not None):
        raise click.UsageError("Choose --if-unset or --expected-style.")
    result = cloud.api(
        cloud.configuration(),
        "POST",
        "/game/style",
        json={
            "gameId": cloud.slug(game_id),
            "visualStyle": style,
            "expectedStyle": None if if_unset else expected_style,
        },
    )
    click.echo(json.dumps(result, indent=2))
