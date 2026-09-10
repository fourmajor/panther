"""Explicit, resumable metadata migration plans through Panther authentication."""

import json
import os
from pathlib import Path

import click

from panther_journal import cloud


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


@assets.command("migrate")
@click.argument("plan", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--apply", is_flag=True, help="Apply the inspected plan; otherwise validate without writing.")
@click.option("--report", required=True, type=click.Path(path_type=Path), help="New private JSONL audit report; never overwrite an earlier report.")
def migrate(plan, apply, report):
    """Dry-run/apply a schemaVersion-1 plan with migrations[] and pinned expectedVersionId.

    Each entry contains schemaVersion, key, expectedVersionId, kind, metadata, and reason.
    File bytes are never accepted or replaced. Retries reuse the same plan.
    """
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
                    result = cloud.api(config, "POST", "/asset-migrations", json={**entry, "dryRun": not apply})
                except click.ClickException:
                    output.write(json.dumps({"key": entry["key"], "status": "interrupted-inspect-before-retry"}) + "\n")
                    output.flush()
                    os.fsync(output.fileno())
                    raise
                output.write(json.dumps({"request": entry, "result": result}) + "\n")
                output.flush()
                os.fsync(output.fileno())
                click.echo(f"{result['status']}: {entry['key']}")
    except FileExistsError:
        raise click.ClickException("Report already exists. Keep it and choose a new report path.")
    click.echo(f"Verified {len(records)} migration responses; report: {report}")
