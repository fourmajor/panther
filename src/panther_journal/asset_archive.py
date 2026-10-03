"""Panther-authenticated logical asset archives and versioned reference migration."""

import json
import uuid
import click
from panther_journal.cloud import api, configuration


@click.command("archive")
@click.option("--game", required=True)
@click.option("--key", required=True)
@click.option(
    "--sha256", required=True, help="Exact base64 SHA-256 from the current immutable asset."
)
@click.option("--operation-id", default=lambda: uuid.uuid4().hex)
def archive(game, key, sha256, operation_id):
    """Remove one asset from current browsing, retaining bytes and historical links."""
    result = api(
        configuration(),
        "POST",
        "/assets/delete",
        json={"gameId": game, "key": key, "sha256": sha256, "operationId": operation_id},
    )
    click.echo(json.dumps(result))


@click.command("archive-migrate")
@click.option("--game")
@click.option("--all-games", is_flag=True)
@click.option(
    "--mode", type=click.Choice(["dry-run", "apply", "verify", "activate"]), default="dry-run"
)
def archive_migrate(game, all_games, mode):
    """Backfill and verify current asset references for every game before activation."""
    if bool(game) == bool(all_games):
        raise click.UsageError("Choose --game or --all-games")
    config = configuration()
    if mode == "activate":
        if not all_games:
            raise click.UsageError("Activation requires --all-games")
        click.echo(
            json.dumps(api(config, "POST", "/assets/archive-migration", json={"mode": "activate"}))
        )
        return
    games = [game] if game else [record["id"] for record in api(config, "GET", "/games")["games"]]
    for game_id in games:
        result = api(
            config, "POST", "/assets/archive-migration", json={"gameId": game_id, "mode": mode}
        )
        click.echo(
            json.dumps(
                {"mode": mode, "references": result["references"], "status": result["status"]}
            )
        )
