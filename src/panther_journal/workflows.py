"""Authenticated workflow observation and local finishing telemetry, never execution."""

import json
import threading
from contextvars import ContextVar
from pathlib import Path

import click

from panther_journal import cloud
from panther_journal.audio_storage import write_json

CURRENT = ContextVar("panther_workshop_reporter", default=None)


@click.group()
def workflows():
    """Inspect workflows, rebuild their projection, or import genuine local checkpoints."""


@workflows.command("list")
@click.option("--game", required=True, callback=lambda _c, _p, v: cloud.slug(v))
@click.option("--id", "identity")
@click.option("--cursor")
def listing(game, identity, cursor):
    config = cloud.configuration()
    click.echo(json.dumps(cloud.api(config, "GET", "/workflows", params={"gameId": game, **({"id": identity} if identity else {}), **({"cursor": cursor} if cursor else {})}), indent=2))


@workflows.command("rebuild")
def rebuild():
    """Backfill all four durable job sources, in bounded resumable pages. No source writes."""
    config = cloud.configuration()
    for kind in ("editorial", "model", "playback", "transcription"):
        cursor = None
        while True:
            result = cloud.api(config, "POST", "/workflows/rebuild", json={"kind": kind, "cursor": cursor})
            click.echo(json.dumps(result))
            cursor = result["cursor"]
            if not cursor:
                break


class Reporter:
    """Observe completed checkpoints; a reporting failure never destroys local work.

    The latest unacknowledged observation is a private outbox, with no credentials.
    Refreshes continue only while a process is alive; stale reports are visible in UI.
    """

    def __init__(self, folder, identity, game, title, names, kind="video-production"):
        self.folder, self.identity, self.game, self.title = folder, identity, game, title
        self.kind = kind
        self.stages = [{"id": name, "label": name.replace("-", " ").capitalize(), "status": "pending"} for name in names]
        self.state, self.revision, self.config = "running", None, None
        self.mutex, self.stop = threading.RLock(), threading.Event()
        self.thread = None

    def payload(self):
        return {"kind": self.kind, "gameId": self.game, "runId": self.identity, "title": self.title, "status": self.state, "stages": self.stages, "expectedRevision": self.revision}

    def send(self):
        with self.mutex:
            write_json(self.folder / "workshop-progress.json", self.payload(), replace=True)
            try:
                if self.config is None:
                    self.config = cloud.configuration()
                result = cloud.api(self.config, "POST", "/workflow-progress", json=self.payload())
                self.revision = result["workflow"]["revision"]
                write_json(self.folder / "workshop-progress.json", self.payload(), replace=True)
            except click.ClickException as exc:
                # A restart has no persisted privilege or session token. Obtain the
                # latest observation revision and retry at the next check-in.
                if "observation changed" in str(exc).lower() or "revision changed" in str(exc).lower():
                    try:
                        result = cloud.api(self.config, "GET", "/workflows", params={"gameId": self.game, "id": self.kind + "~" + self.identity})
                        self.revision = result["workflow"]["revision"]
                        result = cloud.api(self.config, "POST", "/workflow-progress", json=self.payload())
                        self.revision = result["workflow"]["revision"]
                    except click.ClickException:
                        pass
                click.echo("Panther progress reporting unavailable; local checkpoints retained. " + str(exc), err=True)

    def enter(self):
        self.send()
        self.token = CURRENT.set(self)
        self.thread = threading.Thread(target=self.tick, daemon=True)
        self.thread.start()

    def tick(self):
        while not self.stop.wait(60):
            self.send()

    def stage(self, name, state):
        with self.mutex:
            for item in self.stages:
                if item["id"] == name:
                    item["status"] = state
            self.send()

    def close(self, state):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=35)
        self.state = state
        self.send()
        CURRENT.reset(self.token)


@workflows.command("import-production")
@click.argument("directory", type=click.Path(exists=True, path_type=Path))
def import_production(directory):
    """Report historical local receipts; never run missing stages or claim unrecorded work."""
    directory = directory.resolve()
    manifest = json.loads((directory / "manifest.json").read_text())
    result_file = directory / "result.json"
    result = json.loads(result_file.read_text()) if result_file.exists() else None
    receipts = sorted(directory.glob("*/complete.json"))
    completed = [p.parent.name for p in receipts]
    if not completed:
        raise click.ClickException("No completed production receipts to report")
    identity = directory.name
    if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
        raise click.ClickException("Expected immutable production run directory")
    from panther_journal import video_production as production
    for receipt in receipts:
        value = json.loads(receipt.read_text())
        if value.get("identity") != identity:
            raise click.ClickException("Foreign checkpoint; no history imported")
        production.stage(directory, receipt.parent.name, identity, lambda _d: (_ for _ in ()).throw(click.ClickException("Missing historical receipt")))
    prepare = "preparation" in completed
    names = ["inputs", "preparation"] if prepare else ["inputs", *["shot-" + shot["id"] for shot in manifest["shots"]], "sound", "delivery", "final-review"]
    if result:
        checksums = json.loads((directory / "result-sha256.json").read_text())
        if checksums != {"sha256": production.digest(result_file), "manifestSha256": production.digest(directory / "manifest.json")}:
            raise click.ClickException("Historical result checksum changed")
    report = Reporter(directory, identity, manifest["gameId"], manifest["title"], names)
    report.stages = [{"id": name, "label": name.replace("-", " ").capitalize(), "status": "done" if name in completed else "pending"} for name in names]
    report.state = "done" if set(names) <= set(completed) and (result or prepare) else "paused"
    report.send()


def report_video(plan_id):
    """Publish only ledger evidence. Does not consult fal, change budgets or submit."""
    from panther_journal import video
    with video.database() as db:
        plan, approved = video.read_plan(db, plan_id)
        attempts = db.execute("SELECT * FROM attempts WHERE plan_id=? ORDER BY ordinal", (plan_id,)).fetchall()
    latest = {row["shot"]: row for row in attempts}
    folder = video.private_root() / "workflow-observations" / plan_id
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = plan["manifest"]
    names = [shot["id"] for shot in manifest["shots"]]
    report = Reporter(folder, plan_id, manifest["gameId"], "Video generation · " + (manifest.get("sessionId") or plan_id[:8]), names, kind="video-generation")
    states = {"SUBMITTED": "queued", "IN_QUEUE": "queued", "IN_PROGRESS": "running", "COMPLETED": "done", "FAILED": "failed", "UNAVAILABLE": "unknown", "SUBMITTING": "unknown"}
    report.stages = [{"id": shot["id"], "label": f"Render {shot['id']} · {shot['model']}", "status": states.get(latest[shot["id"]]["state"], "unknown") if shot["id"] in latest else "pending"} for shot in manifest["shots"]]
    values = {stage["status"] for stage in report.stages}
    report.state = "done" if values == {"done"} else "unknown" if "unknown" in values else "failed" if "failed" in values else "running" if "running" in values else "queued" if approved else "paused"
    report.send()


@workflows.command("import-video-ledger")
def import_video_ledger():
    """Backfill every local generation plan; never poll providers or spend."""
    from panther_journal import video
    with video.database() as db:
        ids = [row["id"] for row in db.execute("SELECT id FROM plans").fetchall()]
    for identity in ids:
        report_video(identity)
        click.echo("Reported plan " + identity)
