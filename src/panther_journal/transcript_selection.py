"""Canonical reading pointers are explicit application data, never transcript edits."""

import json
import uuid
from pathlib import Path

import click

from panther_journal import cloud


@click.group()
def transcripts():
    """Inspect/select a session's canonical reading version; preserve every source."""


@transcripts.command("selection")
@click.option("--game", required=True)
@click.option("--session", required=True)
def selection(game, session):
    click.echo(
        json.dumps(
            cloud.api(
                cloud.configuration(),
                "GET",
                "/transcript-selection",
                params={"gameId": cloud.slug(game), "sessionId": cloud.slug(session)},
            ),
            indent=2,
        )
    )


@transcripts.command("select")
@click.option("--game", required=True)
@click.option("--session", required=True)
@click.option("--key", required=True)
@click.option(
    "--expected-revision", default=None, help="Omit only when no canonical selection exists."
)
@click.option("--reason", required=True)
@click.option(
    "--operation-id",
    default=lambda: uuid.uuid4().hex,
    help="Retain this ID for an exact retry after an uncertain response.",
)
def select(game, session, key, expected_revision, reason, operation_id):
    """Choose the exact immutable transcript. This does not assert human verification."""
    click.echo(f"Selection operation ID: {operation_id} (retain for an exact retry)", err=True)
    click.echo(
        json.dumps(
            cloud.api(
                cloud.configuration(),
                "POST",
                "/transcript-selection",
                json={
                    "gameId": cloud.slug(game),
                    "sessionId": cloud.slug(session),
                    "key": key,
                    "expectedRevision": expected_revision,
                    "reason": reason,
                    "operationId": operation_id,
                },
            ),
            indent=2,
        )
    )


@transcripts.command("summary-worker")
@click.option("--work-dir", type=click.Path(path_type=Path), required=True)
@click.option("--once", is_flag=True)
def summary_worker(work_dir, once):
    """Generate queued immutable reading summaries through the ChatGPT subscription."""
    from panther_journal.transcript_summaries import run_worker

    run_worker(work_dir, once)


@transcripts.command("summaries-rebuild")
@click.option("--report", type=click.Path(path_type=Path), required=True)
@click.option(
    "--apply",
    is_flag=True,
    help="Ensure version 1 summaries for all registered games; default is inventory only.",
)
@click.option(
    "--verify",
    is_flag=True,
    help="Verify every discovered source has a READY checksum-bound summary.",
)
def summaries_rebuild(report, apply, verify):
    """Inventory/backfill summaries through bounded Panther-authenticated catalog pages."""
    from panther_journal.transcript_summaries import rebuild

    rebuild(report, apply, verify)
