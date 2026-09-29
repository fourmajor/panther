"""Named appearance organization; never upload, overwrite or infer physical changes."""

import json
import os
import uuid
from pathlib import Path

import click

from panther_journal import cloud
from panther_journal.character_details import pages, read_json, private_file, private_open

ROUTES = {
    "appearances": "/character-appearances",
    "appearance-assets": "/character-appearance-assets",
    "selections": "/character-selections",
    "appearance-current": "/character-appearance-current",
}


def listing(name):
    @click.command(name)
    @click.option("--game", required=True)
    @click.option("--character", "character_id", required=True)
    @click.option("--appearance", "appearance_id")
    @click.option("--id", "identity")
    @click.option("--revision")
    def command(game, character_id, appearance_id, identity, revision):
        params = {"gameId": cloud.slug(game), "characterId": cloud.slug(character_id)}
        if name == "appearance-assets":
            if not appearance_id:
                raise click.ClickException("--appearance is required for asset associations")
            params["appearanceId"] = cloud.slug(appearance_id)
        elif appearance_id:
            raise click.ClickException("--appearance applies only to appearance-assets")
        if name == "appearance-current":
            identity = identity or "current"
        if identity:
            params["id"] = cloud.slug(identity)
        if revision:
            if not identity:
                raise click.ClickException("--revision requires --id")
            params["revision"] = revision
        config = cloud.configuration()
        result = (
            cloud.api(config, "GET", ROUTES[name], params=params)
            if identity
            else {"records": pages(config, ROUTES[name], params, "records")}
        )
        click.echo(json.dumps(result, indent=2))

    return command


def saving(name):
    @click.command("save-" + name)
    @click.argument("manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def command(manifest):
        body = read_json(manifest)
        if not isinstance(body, dict) or not body.get("operationId"):
            raise click.ClickException(
                "Use the complete guarded envelope with a stable operationId"
            )
        click.echo(f"Appearance operation: {body['operationId']}", err=True)
        click.echo(
            json.dumps(cloud.api(cloud.configuration(), "POST", ROUTES[name], json=body), indent=2)
        )

    return command


def register(group):
    for name in ROUTES:
        group.add_command(listing(name))
        group.add_command(saving(name))
    for command in (prepare_migration, apply_migration, verify_migration):
        group.add_command(command)


def inventory(config):
    registered, blockers = [], []
    for game in cloud.api(config, "GET", "/games")["games"]:
        gid = game["id"]
        characters = pages(config, "/characters", {"gameId": gid}, "characters")
        # A game may retain its historical legacy flag after an explicit
        # character registration. Still reject a legacy game with no roster.
        if game.get("legacy") and not characters:
            blockers.append(
                {"gameId": gid, "error": "Game must be explicitly registered before migration"}
            )
            continue
        known = {c["id"] for c in characters}
        legacy = pages(
            config, "/character-appearance-migration/game-inventory", {"gameId": gid}, "characters"
        )
        blockers.extend(
            {
                "gameId": gid,
                "characterId": cid,
                "error": "Legacy artwork prefix has no registered character",
            }
            for cid in legacy
            if cid not in known
        )
        registered.extend({"gameId": gid, "characterId": c["id"]} for c in characters)
    return registered, blockers


@click.command("prepare-appearance-migration")
@click.option("--plan", type=click.Path(dir_okay=False, path_type=Path), required=True)
def prepare_migration(plan):
    """Inspect every game and preserve a private, create-only dry-run plan."""
    config = cloud.configuration()
    registered, blockers = inventory(config)
    entries = []
    for character in registered:
        try:
            sources = cloud.api(
                config, "GET", "/character-appearance-migration/inventory", params=character
            )["sourceKeys"]
            prepared = [
                cloud.api(
                    config,
                    "POST",
                    "/character-appearance-migration/prepare",
                    json={**character, "sourceKey": key},
                )["plan"]
                for key in sources
            ]
            entries.append({**character, "sources": prepared, "operationId": uuid.uuid4().hex})
        except click.ClickException as error:
            blockers.append({**character, "error": str(error)})
    private_file(plan, {"schemaVersion": 1, "characters": entries, "blockers": blockers})
    click.echo(f"Prepared {len(entries)} characters; {len(blockers)} blockers. No artwork changed.")


@click.command("apply-appearance-migration")
@click.argument("plan", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--report", type=click.Path(dir_okay=False, path_type=Path), required=True)
def apply_migration(plan, report):
    """Import exact sources serially and activate only a verified complete history."""
    document = read_json(plan)
    if (
        not isinstance(document, dict)
        or document.get("schemaVersion") != 1
        or document.get("blockers")
        or not isinstance(document.get("characters"), list)
    ):
        raise click.ClickException("A blocker-free complete migration plan is required")
    for entry in document["characters"]:
        if not isinstance(entry, dict) or set(entry) != {
            "gameId",
            "characterId",
            "sources",
            "operationId",
        }:
            raise click.ClickException("Invalid character migration envelope")
        if not isinstance(entry["sources"], list) or any(
            not isinstance(source, dict)
            or source.get("gameId") != entry["gameId"]
            or source.get("characterId") != entry["characterId"]
            for source in entry["sources"]
        ):
            raise click.ClickException("Source plans must identify their enclosing character")
    config = cloud.configuration()
    registered, blockers = inventory(config)
    expected = {(c["gameId"], c["characterId"]) for c in document["characters"]}
    if (
        blockers
        or expected != {(c["gameId"], c["characterId"]) for c in registered}
        or len(expected) != len(document["characters"])
    ):
        raise click.ClickException(
            "All-game character inventory changed; prepare a new private plan"
        )
    with private_open(report) as handle:

        def record(value):
            handle.write(json.dumps(value, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

        def request(body, endpoint, identity):
            record({"status": "pending", "operation": identity, "request": body})
            try:
                result = cloud.api(config, "POST", endpoint, json=body)
            except Exception:
                record({"status": "unconfirmed", "operation": identity})
                raise
            record({"status": "confirmed", "operation": identity, "result": result})
            return result

        for entry in document["characters"]:
            character = {k: entry[k] for k in ("gameId", "characterId")}
            sources = cloud.api(
                config, "GET", "/character-appearance-migration/inventory", params=character
            )["sourceKeys"]
            if sorted(sources) != sorted(p["sourceKey"] for p in entry["sources"]):
                raise click.ClickException(
                    "Retained source inventory changed; inspect the private report"
                )
            for source in entry["sources"]:
                request(
                    {"plan": source},
                    "/character-appearance-migration/apply",
                    source["sourceSha256"] + ":" + source["sourceKey"],
                )
            proof = cloud.api(
                config, "POST", "/character-appearance-migration/verify", json=character
            )["verification"]
            request(
                {"verification": proof, "operationId": entry["operationId"]},
                "/character-appearance-migration/finalize",
                entry["operationId"],
            )
    click.echo(
        "Imported all planned histories. Run verify-appearance-migration before declaring cutover complete."
    )


@click.command("verify-appearance-migration")
@click.option("--report", type=click.Path(dir_okay=False, path_type=Path), required=True)
def verify_migration(report):
    """Verify the complete all-game inventory, receipts and migration completion seals."""
    config = cloud.configuration()
    registered, blockers = inventory(config)
    results = []
    for character in registered:
        try:
            result = cloud.api(
                config, "POST", "/character-appearance-migration/verify", json=character
            )
            results.append({**character, **result})
            if not result["completed"]:
                raise click.ClickException("Migration completion seal is missing")
        except click.ClickException as error:
            blockers.append({**character, "error": str(error)})
    private_file(report, {"schemaVersion": 1, "characters": results, "blockers": blockers})
    if blockers:
        raise click.ClickException(
            f"Verification has {len(blockers)} blockers; inspect the private report"
        )
    click.echo(f"Verified {len(registered)} characters across all games.")
