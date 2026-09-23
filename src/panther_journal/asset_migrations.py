"""Explicit, resumable metadata migration plans through Panther authentication."""

import json
import os
import copy
import hashlib
from pathlib import Path

import click

from panther_journal import cloud, generation_metadata as generation


@click.group()
def assets():
    """Audit assets and apply version-guarded metadata migrations."""


@assets.command("catalog")
@click.option("--game", required=True)
def catalog(game):
    """List the complete game asset catalog, including exact recorded provenance."""
    config = cloud.configuration()
    records, cursor = [], None
    while True:
        page = cloud.api(config, "GET", "/assets", params={"gameId": cloud.slug(game), "cursor": cursor})
        records.extend(page["assets"])
        cursor = page.get("cursor")
        if not cursor:
            break
    click.echo(json.dumps({"gameId": game, "assets": records}, indent=2))


@assets.command("rebuild-index")
@click.option("--mode", type=click.Choice(["dry-run", "apply", "verify"]), default="dry-run")
@click.option("--report", required=True, type=click.Path(path_type=Path))
def rebuild_index(mode, report):
    """Rebuild/verify the browsing projection for ALL games; never change source files."""
    config = cloud.configuration()
    failures = 0
    with report.open("x") as stream:
        report.chmod(0o600)
        for game in cloud.api(config, "GET", "/games")["games"]:
            cursor, seen, count = None, set(), 0
            while True:
                page = cloud.api(config, "POST", "/asset-index/rebuild", json={
                    "gameId": game["id"], "mode": mode, "cursor": cursor})
                stream.write(json.dumps(page) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
                count += len(page["records"])
                failures += sum(r["status"] == "mismatch" for r in page["records"])
                click.echo(f"{game['id']}: {count} records {mode}", err=True)
                cursor = page.get("cursor")
                if not cursor:
                    break
                if cursor in seen:
                    raise click.ClickException("Repeated maintenance cursor; stopped")
                seen.add(cursor)
    if failures:
        raise click.ClickException(f"{failures} index mismatches; inspect the private report")
    if mode == "verify":
        cloud.api(config, "POST", "/asset-index/rebuild", json={"mode": "activate"})
        click.echo("All games verified; indexed browsing is active.")


def generation_plan(records, facts):
    """Version-1 backfill: preserve metadata/bytes; only explicitly evidenced facts enrich defaults."""
    if not isinstance(facts, dict) or set(facts) - {r["key"] for r in records}:
        raise click.ClickException("Generation facts must reference inventoried assets only")
    migrations = []
    for record in records:
        details = copy.deepcopy(record["metadata"])
        extra = details.setdefault("extra", {})
        desired = facts.get(record["key"], extra.get("generation", generation.unknown()))
        if not isinstance(desired, dict) or desired.get("schemaVersion") != 1:
            raise click.ClickException("Generation facts require schemaVersion 1")
        if extra.get("generation") == desired:
            continue
        extra["generation"] = desired
        migrations.append({"schemaVersion": 1, "key": record["key"],
                           "expectedVersionId": record["versionId"], "kind": record["kind"],
                           "metadata": details, "reason": "Generation metadata v1: explicit evidence or unknown; original bytes and provenance retained"})
    return {"schemaVersion": 1, "migrations": migrations}


def version_plan(records, appearances):
    """Backfill every asset; group only verified official selections from profile history."""
    known = {record["key"]: record for record in records}
    assigned = {}
    for (game, character, kind), keys in appearances.items():
        series = "appearance-" + hashlib.sha256(f"{game}/{character}/{kind}".encode()).hexdigest()[:24]
        previous = None
        for number, key in enumerate(keys, 1):
            if key not in known:
                raise click.ClickException(f"Official appearance is missing from inventory: {key}")
            if key in assigned:
                raise click.ClickException(f"Appearance belongs to multiple version series: {key}")
            assigned[key] = {"schemaVersion": 1, "seriesId": series, "number": number,
                             **({"previousKey": previous} if previous else {})}
            previous = key
    migrations = []
    for record in records:
        details = copy.deepcopy(record["metadata"])
        extra = details.setdefault("extra", {})
        default = {"schemaVersion": 1, "seriesId": hashlib.sha256(record["key"].encode()).hexdigest()[:24], "number": 1}
        desired = assigned.get(record["key"], default)
        if extra.get("version") == desired:
            continue
        if "version" in extra and extra["version"] != default:
            raise click.ClickException(f"Existing version record differs; investigate before replanning: {record['key']}")
        extra["version"] = desired
        migrations.append({"schemaVersion": 1, "key": record["key"],
                           "expectedVersionId": record["versionId"], "kind": record["kind"],
                           "metadata": details, "reason": "Asset versions v1: profile-backed appearance series or explicit singleton; original bytes retained"})
    return {"schemaVersion": 1, "migrations": migrations}


@assets.command("version-plan")
@click.option("--output", required=True, type=click.Path(path_type=Path))
def plan_versions(output):
    """Inventory ALL games and prepare a private, version-pinned appearance backfill."""
    config = cloud.configuration()
    records, appearances = [], {}
    for game in cloud.api(config, "GET", "/games")["games"]:
        game_id = game["id"]
        cursor = None
        while True:
            page = cloud.api(config, "GET", "/assets", params={"gameId": game_id, "cursor": cursor})
            for asset in page["assets"]:
                info = cloud.api(config, "GET", "/object-url", params={"key": asset["key"]})
                records.append({k: info[k] for k in ("key", "versionId", "kind", "metadata")})
            cursor = page.get("cursor")
            if not cursor:
                break
        for character in cloud.api(config, "GET", "/characters", params={"gameId": game_id})["characters"]:
            history = cloud.api(config, "GET", "/character-versions", params={"gameId": game_id, "characterId": character["id"]})
            for kind, field in (("model", "models"), ("portrait", "portraits")):
                keys = [item["key"] for item in reversed(history[field])]
                if keys:
                    appearances[(game_id, character["id"], kind)] = keys
    try:
        plan = version_plan(records, appearances)
        with output.open("x") as stream:
            output.chmod(0o600)
            json.dump(plan, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError):
        raise click.ClickException("Could not create a new private plan; never overwrite a prior plan") from None
    click.echo(f"Inventoried {len(records)} assets in all games; planned {len(plan['migrations'])} version records. Dry-run with assets migrate.")


@assets.command("generation-plan")
@click.option("--facts", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Private JSON map of exact asset keys to evidence-backed generation records.")
@click.option("--output", required=True, type=click.Path(path_type=Path))
def plan_generation(facts, output):
    """Inventory ALL games and prepare a generation-v1 migration. No cloud writes."""
    config = cloud.configuration()
    records = []
    for game in cloud.api(config, "GET", "/games")["games"]:
        cursor = None
        while True:
            page = cloud.api(config, "GET", "/assets", params={"gameId": game["id"], "cursor": cursor})
            for asset in page["assets"]:
                info = cloud.api(config, "GET", "/object-url", params={"key": asset["key"]})
                records.append({k: info[k] for k in ("key", "versionId", "kind", "metadata")})
            cursor = page.get("cursor")
            if not cursor:
                break
    try:
        supplied = json.loads(facts.read_text()) if facts else {}
        plan = generation_plan(records, supplied)
        with output.open("x") as stream:
            output.chmod(0o600)
            json.dump(plan, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError):
        raise click.ClickException("Could not read facts or create a new private plan; never overwrite a prior plan") from None
    click.echo(f"Inventoried {len(records)} assets across all games; planned {len(plan['migrations'])} metadata updates. Dry-run with assets migrate.")


@assets.command("migrate")
@click.argument("plan", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--apply", is_flag=True, help="Apply the inspected plan; otherwise validate without writing.")
@click.option("--report", required=True, type=click.Path(path_type=Path), help="New private JSONL audit report; never overwrite an earlier report.")
def migrate(plan, apply, report):
    """Dry-run/apply a schemaVersion-1 plan with migrations[] and pinned expectedVersionId.

    Each entry contains schemaVersion, key, expectedVersionId, kind, metadata, and reason.
    File bytes are never accepted or replaced. Retries reuse the same plan.
    """
    run_migrations(plan, apply, report, "/asset-migrations")


def run_migrations(plan, apply, report, endpoint, extra=None):
    try:
        document = json.loads(plan.read_text())
        if document.get("schemaVersion") != 1 or not isinstance(document.get("migrations"), list):
            raise ValueError()
        records = document["migrations"]
        if not records or len(records) > 5000:
            raise ValueError()
        if len({r["key"] for r in records}) != len(records):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise click.ClickException("Invalid migration plan; expected unique pinned assets.")
    config = cloud.configuration()
    try:
        with report.open("x", encoding="utf-8") as output:
            report.chmod(0o600)
            for entry in records:
                try:
                    result = cloud.api(config, "POST", endpoint, json={**entry, **(extra or {}), "dryRun": not apply})
                except click.ClickException:
                    output.write(json.dumps({"key": entry["key"], "status": "interrupted-inspect-before-retry"}) + "\n")
                    output.flush()
                    os.fsync(output.fileno())
                    raise
                output.write(json.dumps({"request": entry, "endpoint": endpoint,
                                         "operation": extra or {}, "dryRun": not apply, "result": result}) + "\n")
                output.flush()
                os.fsync(output.fileno())
                click.echo(f"{result['status']}: {entry['key']}")
    except FileExistsError:
        raise click.ClickException("Report already exists. Keep it and choose a new report path.")
    click.echo(f"Verified {len(records)} migration responses; report: {report}")
