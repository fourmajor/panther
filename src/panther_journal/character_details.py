"""Guarded character fact edits and all-game migrations via Panther authentication."""

import json
import os
import uuid
from pathlib import Path

import click

from panther_journal import cloud


def pages(config, endpoint, params, field):
    result, seen = [], set()
    while True:
        page = cloud.api(config, "GET", endpoint, params=params)
        result.extend(page[field])
        cursor = page.get("cursor")
        if not cursor:
            return result
        if cursor in seen:
            raise click.ClickException("Repeated pagination cursor; inventory is incomplete.")
        seen.add(cursor)
        params = {**params, "cursor": cursor}


def private_open(path):
    # Plans contain private facts. Never place them in a source checkout.
    resolved = path.resolve()
    if any((p / ".git").exists() for p in [resolved.parent, *resolved.parents]):
        raise click.ClickException("Store private plans/reports outside a Git checkout.")
    try:
        descriptor = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise click.ClickException(
            "Cannot create the private file; it must not already exist."
        ) from exc
    return os.fdopen(descriptor, "w")


def private_file(path, value):
    with private_open(path) as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise click.ClickException("Cannot read the private JSON file.") from exc


@click.command("details")
@click.option("--game", required=True)
@click.option("--character", "character_id", required=True)
def details(game, character_id):
    """Read structured facts and their optimistic-lock revision."""
    click.echo(
        json.dumps(
            cloud.api(
                cloud.configuration(),
                "GET",
                "/character-details",
                params={"gameId": cloud.slug(game), "characterId": cloud.slug(character_id)},
            ),
            indent=2,
        )
    )


@click.command("edit-details")
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def edit_details(manifest):
    """Submit an exact guarded edit envelope; retain its operationId for safe retries."""
    body = read_json(manifest)
    if not isinstance(body, dict) or body.get("mode") != "edit" or body.get("dryRun") is not False:
        raise click.ClickException(
            "Expected a complete edit envelope with mode=edit, dryRun=false."
        )
    click.echo(f"Operation: {body.get('operationId', 'missing')}", err=True)
    click.echo(
        json.dumps(
            cloud.api(cloud.configuration(), "POST", "/character-details", json=body), indent=2
        )
    )


def inventory(config):
    games = cloud.api(config, "GET", "/games")["games"]
    records, blockers = [], []
    for game in games:
        game_id = game["id"]
        profiles = pages(config, "/character-details/inventory", {"gameId": game_id}, "profiles")
        if game.get("legacy"):
            blockers.append(
                {
                    "gameId": game_id,
                    "error": "Game must be explicitly registered; no roster is inferred.",
                }
            )
            continue
        records.extend(pages(config, "/characters", {"gameId": game_id}, "characters"))
        blockers.extend(
            {
                "gameId": game_id,
                "characterId": p["characterId"],
                "error": "Artwork profile has no registered character.",
            }
            for p in profiles
            if not p["registered"]
        )
    return records, blockers


@click.command("prepare-details-migration")
@click.option("--plan", type=click.Path(dir_okay=False, path_type=Path), required=True)
def prepare(plan):
    """Dry-run every game's character facts; create an owner-only immutable plan."""
    config = cloud.configuration()
    records, blockers = inventory(config)
    operations = []
    for record in records:
        params = {"gameId": record["gameId"], "characterId": record["id"]}
        try:
            if record.get("schemaVersion") == 2:
                cloud.api(config, "GET", "/character-details/verify", params=params)
                continue
            body = {
                **params,
                "mode": "migrate",
                "details": None,
                "expectedRevision": None,
                "expectedSourceHash": None,
                "operationId": uuid.uuid4().hex,
                "reason": "Version-2 character facts migration",
                "dryRun": True,
            }
            result = cloud.api(config, "POST", "/character-details/migrate", json=body)
            operations.append(result["plan"])
        except click.ClickException as exc:
            blockers.append({**params, "error": str(exc)})
    private_file(
        plan,
        {
            "schemaVersion": 1,
            "operations": operations,
            "blockers": blockers,
            "characterCount": len(records),
        },
    )
    click.echo(
        f"Prepared {len(operations)} operations; {len(blockers)} blockers. No facts changed."
    )


@click.command("apply-details-migration")
@click.argument("plan", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--report", type=click.Path(dir_okay=False, path_type=Path), required=True)
def apply(plan, report):
    """Apply pinned operations serially; stop on conflicts and retain safe retry identities."""
    document = read_json(plan)
    if (
        document.get("schemaVersion") != 1
        or document.get("blockers")
        or not isinstance(document.get("operations"), list)
    ):
        raise click.ClickException("A valid blocker-free migration plan is required.")
    config = cloud.configuration()
    completed = 0
    with private_open(report) as handle:

        def record(value):
            handle.write(json.dumps(value, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

        for body in document["operations"]:
            if body.get("mode") != "migrate" or body.get("dryRun") is not False:
                raise click.ClickException("Invalid migration operation.")
            click.echo(f"Applying operation {body['operationId']}", err=True)
            record({"schemaVersion": 1, "operationId": body["operationId"], "status": "pending"})
            try:
                result = cloud.api(config, "POST", "/character-details/migrate", json=body)
            except Exception:
                record({"operationId": body["operationId"], "status": "unconfirmed"})
                raise
            record({"operationId": body["operationId"], "status": "confirmed", "result": result})
            completed += 1
    click.echo(f"Applied {completed} operations. Run verify-details-migration next.")


@click.command("verify-details-migration")
@click.option("--report", type=click.Path(dir_okay=False, path_type=Path), required=True)
def verify(report):
    """Verify the complete all-game inventory; never silently exempt legacy records."""
    config = cloud.configuration()
    records, blockers = inventory(config)
    for record in records:
        try:
            cloud.api(
                config,
                "GET",
                "/character-details/verify",
                params={"gameId": record["gameId"], "characterId": record["id"]},
            )
        except click.ClickException as exc:
            blockers.append(
                {"gameId": record["gameId"], "characterId": record["id"], "error": str(exc)}
            )
    private_file(report, {"schemaVersion": 1, "characterCount": len(records), "blockers": blockers})
    if blockers:
        raise click.ClickException(
            f"Verification blocked by {len(blockers)} records; see the private report."
        )
    click.echo(f"Verified {len(records)} characters across all games.")


def register(group):
    for command in (details, edit_details, prepare, apply, verify):
        group.add_command(command)
