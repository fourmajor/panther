"""Explicit, resumable metadata migration plans through Panther authentication."""

import json
import os
import copy
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
