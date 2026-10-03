"""Separate, deterministic playback worker for the private local development database."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "infra/lambda/media-api"))
sys.path.insert(0, str(ROOT / "tools"))

import asset_metadata  # noqa: E402
import storage_layout  # noqa: E402
from dev_server import Store  # noqa: E402
from panther_journal import browser_recording, recording_playback  # noqa: E402
from panther_journal.generation_metadata import local  # noqa: E402


def private_root(path):
    root = Path(path).expanduser().resolve()
    if root in {Path.home(), Path("/")} or any((p / ".git").exists() for p in (root, *root.parents)):
        raise ValueError("Use a dedicated private work directory outside Git")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def retain(file, raw):
    """A resume verifies checkpoints; it never replaces previous source or output bytes."""
    if file.is_symlink():
        raise ValueError("Symlinked playback checkpoint rejected")
    try:
        with file.open("xb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError:
        if file.read_bytes() != raw:
            raise ValueError("Retained playback source differs; refusing overwrite")


def process(store, identity, root):
    job = store.get("playback", identity)
    if not job or job.get("status") not in {"WAITING", "QUEUED", "PROCESSING"}:
        return False
    # The process-level database lock makes interrupted PROCESSING jobs safely resumable.
    try:
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise ValueError("Invalid playback job identity")
        if job.get("workflowVersion") != 2 or job.get("setStatus") != "COMPLETE":
            raise ValueError("Playback requires an explicitly completed browser recording")
        key = job["recordingKey"]
        ref = storage_layout.parts(key)
        if ref["game"] != job["gameId"] or ref["representation"] != "original" or ref["filename"] != "recording.json":
            raise ValueError("Recording source is not a same-game original manifest")
        meta, raw = store.object(key)
        pin = job.get("sourceManifestSha256", job.get("manifestSha256"))
        if pin != identity or hashlib.sha256(raw).hexdigest() != pin:
            raise ValueError("Recording manifest checksum changed")
        record = browser_recording.BrowserRecording.model_validate_json(raw)
        if record.gameId != ref["game"] or record.id != ref["asset"] or record.id != job.get("chunkSetId"):
            raise ValueError("Recording identity does not match its completed job")
        folder = private_root(root) / identity
        folder.mkdir(mode=0o700, exist_ok=True)
        if folder.is_symlink():
            raise ValueError("Symlinked playback work folder rejected")
        retain(folder / "recording.json", raw)
        sources = {key: raw}
        prefix = key.rsplit("/", 1)[0] + "/"
        for part in record.parts:
            part_key = prefix + part.file
            _, data = store.object(part_key)
            if len(data) != part.size or hashlib.sha256(data).hexdigest() != part.sha256:
                raise ValueError("Recording part checksum or size changed")
            retain(folder / part.file, data)
            sources[part_key] = data
        browser_recording.verified(folder)
        job.update(status="PROCESSING", message=None)
        store.put("playback", identity, job, record.gameId)
        target, manifest, doc = recording_playback.build(folder)
        audio_key, manifest_key = prefix + target.name, prefix + manifest.name
        outputs = []
        for file, out_key, kind, mime, inputs in (
            (manifest, manifest_key, "recording-playback-manifest", "application/json", doc["sourceKeys"]),
            (target, audio_key, "recording-playback", "audio/mpeg", [manifest_key]),
        ):
            data = file.read_bytes()
            sha = base64.b64encode(hashlib.sha256(data).digest()).decode()
            metadata = asset_metadata.defaults(kind, {
                "title": record.sessionName, "sessionId": record.sessionId,
                "sourceKeys": inputs, "kind": kind, "contentType": mime,
                "extra": {"recordingId": record.id, "chunkSetId": record.id,
                          "sha256": sha, "generation": local("FFmpeg"),
                          "captureWarnings": record.captureWarnings},
            }, file.name, mime, out_key)
            # Same organized-location contract as uploads; SQLite stores stable references.
            storage_layout.location(out_key, kind, metadata)
            outputs.append((out_key, data, metadata))
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for source_key, original in sources.items():
                row = db.execute("SELECT game,data FROM objects WHERE key=?", (source_key,)).fetchone()
                if not row or row != (record.gameId, original):
                    raise ValueError("Completed recording changed during playback assembly")
            for out_key, data, metadata in outputs:
                existing = db.execute("SELECT game,data,metadata FROM objects WHERE key=?", (out_key,)).fetchone()
                if existing and (existing[:2] != (record.gameId, data) or json.loads(existing[2]) != metadata):
                    raise ValueError("Saved playback output differs; refusing overwrite")
                if not existing:
                    db.execute("INSERT INTO objects VALUES (?,?,?,?,?)", (out_key, record.gameId, json.dumps(metadata), data, datetime.now(timezone.utc).isoformat()))
            job.update(status="DONE", message=None, output={"audioKey": audio_key, "manifestKey": manifest_key}, audioKey=audio_key, manifestKey=manifest_key)
            db.execute("UPDATE records SET payload=? WHERE kind='playback' AND id=?", (json.dumps(job), identity))
        return True
    except Exception as exc:
        job.update(status="FAILED", message=str(exc)[:500])
        store.put("playback", identity, job, job.get("gameId", ""))
        return False


def run(database, work_dir, *, once=False):
    store = Store(database)
    root = private_root(work_dir)
    # One worker per database, even if callers choose different output directories.
    lock_path = store.path.with_name(store.path.name + ".playback.lock")
    with lock_path.open("a") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stop = threading.Event()

        def heartbeat():
            while not stop.is_set():
                store.put("service", "playback", {"status": "RUNNING", "updatedAt": time.time()})
                stop.wait(15)

        pulse = threading.Thread(target=heartbeat, daemon=True)
        pulse.start()
        try:
            while True:
                with store.connect() as db:
                    rows = db.execute("SELECT id FROM records WHERE kind='playback' AND json_extract(payload,'$.status') IN ('WAITING','QUEUED','PROCESSING') ORDER BY rowid LIMIT 25").fetchall()
                for (identity,) in rows:
                    process(store, identity, root)
                if once and not rows:
                    return
                if not once:
                    time.sleep(2)
        finally:
            stop.set()
            pulse.join()
            store.put("service", "playback", {"status": "STOPPED", "updatedAt": time.time()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("~/.local/state/panther/development.sqlite"))
    parser.add_argument("--work-dir", type=Path, default=Path("~/.local/state/panther/playback"))
    parser.add_argument("--once", action="store_true", help="Process current completed jobs, then exit")
    args = parser.parse_args()
    os.umask(0o077)
    run(args.database, args.work_dir, once=args.once)


if __name__ == "__main__":
    main()
