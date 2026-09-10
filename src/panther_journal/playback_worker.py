"""Completed-set submission and deterministic local playback worker; no AI or AWS credentials."""

import json
import os
from pathlib import Path
import threading
import time

import click
import requests

from panther_journal import cloud, recording as audio, recording_playback
from panther_journal.audio_storage import lock
from panther_journal.model_workflow import download


def complete_set(folder, config, record):
    """Only call after all immutable source uploads succeed. The server verifies the entire set."""
    return cloud.api(config, "POST", "/recording-sets/complete", json={
        "gameId": record.gameId,
        "recordingKey": f"games/{record.gameId}/assets/{record.id}/original/recording.json",
        "manifestSha256": audio.digest(folder / "recording.json"), "status": "COMPLETE",
    })


class Lease:
    def __init__(self, config, claim):
        self.config = config
        self.body = {"jobId": claim["job"]["jobId"], "lease": claim["lease"]}
        self.stop = threading.Event()
        self.error = None

    def heartbeat(self):
        cloud.api(self.config, "POST", "/recording-playback-jobs/heartbeat", json=self.body)

    def loop(self):
        while not self.stop.wait(60):
            try:
                self.heartbeat()
            except Exception:
                self.error = True
                return

    def check(self):
        if self.error:
            raise click.ClickException("Playback lease lost; local files retained for retry.")

    def __enter__(self):
        self.heartbeat()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop.set()
        self.thread.join(timeout=70)


def process(config, claim, root):
    job = claim["job"]
    if job.get("workflowVersion") != 1 or job.get("setStatus") != "COMPLETE":
        raise click.ClickException("Worker requires an explicitly completed version-1 chunk set.")
    # Keep each exact immutable set/version separate. Never consult the capture machine's files.
    cloud.slug(job["jobId"])
    folder = root / job["jobId"]
    folder.mkdir(mode=0o700, exist_ok=True)
    with Lease(config, claim) as lease:
        refs = [job["recording"], *job["chunks"]]
        prefix = f"games/{job['gameId']}/assets/{job['chunkSetId']}/original/"
        for i, ref in enumerate(refs):
            name = "recording.json" if i == 0 else f"part-{i - 1:04d}.flac"
            if ref["key"] != prefix + name or (folder / name).is_symlink():
                raise click.ClickException("Invalid completed-set input path.")
            lease.check()
            try:
                download(config, ref, folder / name)
            except requests.RequestException:
                # requests exceptions can contain a full credential-bearing signed URL.
                raise click.ClickException("Playback input download failed; checkpoints retained for retry.") from None
        record = audio.verified(folder)
        if record.id != job["chunkSetId"] or record.gameId != job["gameId"]:
            raise click.ClickException("Completed set identity mismatch.")
        target, manifest, _ = recording_playback.build(folder)
        lease.check()
        manifest_key = audio.upload_one(config, manifest, record, "recording-playback-manifest")
        lease.check()
        audio.upload_one(config, target, record, "recording-playback", source_keys=[manifest_key])
        lease.check()
        return cloud.api(config, "POST", "/recording-playback-jobs/complete", json=lease.body)


@click.group("playback")
def playback():
    """Completed recording sets and continuous playback workflows."""


@playback.command("jobs")
@click.option("--job-id")
def jobs(job_id):
    config, cursor = cloud.configuration(), None
    while True:
        result = cloud.api(config, "GET", "/recording-playback-jobs",
            params={k: v for k, v in {"jobId": job_id, "cursor": cursor}.items() if v})
        click.echo(json.dumps(result, indent=2))
        cursor = result.get("cursor")
        if not cursor:
            break


@playback.command("complete-set")
@click.option("--game", required=True)
@click.option("--recording-key", required=True)
@click.option("--manifest-sha256", required=True)
def commit(game, recording_key, manifest_sha256):
    """Explicitly mark an already-uploaded set complete. All declared chunks must exist and match."""
    click.echo(json.dumps(cloud.api(cloud.configuration(), "POST", "/recording-sets/complete", json={
        "gameId": game, "recordingKey": recording_key, "manifestSha256": manifest_sha256,
        "status": "COMPLETE",
    }), indent=2))


@playback.command("worker")
@click.option("--work-dir", type=click.Path(path_type=Path), required=True)
@click.option("--once", is_flag=True)
def worker(work_dir, once):
    """Assemble completed sets on this laptop; idle cloud workflows just wait."""
    root = work_dir.expanduser().resolve()
    if root in {Path.home(), Path("/")} or any((p / ".git").exists() for p in (root, *root.parents)):
        raise click.ClickException("Worker data belongs in a dedicated private directory outside Git.")
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ("ffmpeg", "ffprobe"):
        audio.executable(name)
    with lock(root, "worker.lock"):
        config = cloud.configuration()
        while True:
            claimed = cloud.api(config, "POST", "/recording-playback-jobs/claim", json={"workflowVersion": 1})
            if claimed.get("job"):
                result = process(config, claimed, root)
                click.echo(json.dumps({"jobId": result["jobId"], "status": result["status"]}))
            if once:
                return
            if not claimed.get("job"):
                time.sleep(60)
