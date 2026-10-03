"""Private ordered video collections through Panther authentication."""

import json
from pathlib import Path
import uuid

import click

from panther_journal import cloud


@click.group()
def videos():
    """Browse/save private video collections; never start generation."""


from panther_journal.tv_library import register as register_tv  # noqa: E402
register_tv(videos)


@videos.command("collections")
@click.option("--game", required=True)
@click.option("--id", "identity", help="Inspect one collection with its exact members.")
def collections(game, identity):
    config = cloud.configuration()
    if identity:
        click.echo(
            json.dumps(
                cloud.api(
                    config,
                    "GET",
                    "/video-collections",
                    params={"gameId": cloud.slug(game), "id": cloud.slug(identity)},
                ),
                indent=2,
            )
        )
        return
    records, cursor, seen = [], None, set()
    while True:
        page = cloud.api(
            config,
            "GET",
            "/video-collections",
            params={"gameId": cloud.slug(game), "cursor": cursor},
        )
        records.extend(page["collections"])
        cursor = page.get("cursor")
        if not cursor:
            break
        if cursor in seen:
            raise click.ClickException(
                "Repeated collection cursor; incomplete results are not presented"
            )
        seen.add(cursor)
    click.echo(json.dumps({"collections": records}, indent=2))


@videos.command("save-collection")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--operation-id",
    default=lambda: uuid.uuid4().hex,
    help="Retain for an exact retry after an uncertain response.",
)
def save_collection(file, operation_id):
    """Save a version-guarded ordered collection from a private JSON file."""
    try:
        if file.stat().st_size > 64 * 1024:
            raise ValueError()
        body = json.loads(file.read_text())
        if not isinstance(body, dict) or set(body) != {
            "gameId",
            "id",
            "name",
            "description",
            "assetKeys",
            "expectedRevision",
        }:
            raise ValueError()
    except (OSError, ValueError):
        raise click.ClickException(
            "Use a bounded JSON collection with gameId, id, name, description, ordered assetKeys and expectedRevision"
        ) from None
    click.echo(f"Collection operation ID: {operation_id} (retain for an exact retry)", err=True)
    click.echo(
        json.dumps(
            cloud.api(
                cloud.configuration(),
                "POST",
                "/video-collections",
                json={**body, "operationId": operation_id},
            ),
            indent=2,
        )
    )


@videos.command("migrate-workspace")
@click.option("--apply", is_flag=True, help="Apply the reviewed all-game inventory; default is a dry run.")
@click.option("--inventory-hash", help="Exact inventoryHash from a reviewed dry run; required with --apply.")
def migrate_workspace(apply, inventory_hash):
    """Import explicit legacy episodes without inventing scenes or changing media."""
    if apply and (not inventory_hash or len(inventory_hash) != 64 or any(c not in "0123456789abcdef" for c in inventory_hash)):
        raise click.ClickException("--apply requires the reviewed --inventory-hash (64 lowercase hex characters)")
    if not apply and inventory_hash:
        raise click.ClickException("--inventory-hash is only used with --apply")
    body = {"schemaVersion": 1, "apply": apply}
    if apply:
        body["expectedInventoryHash"] = inventory_hash
    click.echo(json.dumps(cloud.api(cloud.configuration(), "POST", "/video-workspace/migrate", json=body), indent=2))

from panther_journal.episode_rendering import register as register_episode_rendering  # noqa: E402
register_episode_rendering(videos)
