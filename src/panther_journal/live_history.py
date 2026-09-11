"""Independent full-preview publication; no audio upload or AWS credentials."""

import hashlib
import json
import re
import time

import click

from panther_journal import cloud
from panther_journal.audio_storage import write_json


def chunk_payload(folder, header, root, config, part):
    from panther_journal import live_transcript as live

    value = live.read_json(root / part.file.replace(".flac", ".json"))
    if value["sourcePart"] != part.model_dump() or value["modelSha256"] != config["settings"]["modelSha256"]:
        raise click.ClickException("History input pins changed")
    if not re.fullmatch(r"attempt-[a-f0-9]{32}", value["attempt"]):
        raise click.ClickException("Invalid history attempt")
    attempt = root / value["attempt"]
    raw = attempt / "recognizer.json"
    if attempt.is_symlink() or raw.is_symlink() or live.audio.digest(raw) != value["recognizerSha256"]:
        raise click.ClickException("Preserved recognition changed")
    live.check_part(folder, part)
    segments = []
    for line in value["segments"]:
        text = " ".join("".join(c for c in line["text"] if c.isprintable()).split())
        if not text:
            continue
        segment = {"start": line["start"], "end": line["end"], "text": text}
        if line.get("kind") == "preview-gap":
            segment["kind"] = "preview-gap"
        if line.get("timingNote"):
            segment["approximateTiming"] = True
        if line.get('playerId') and line.get('attribution') == 'provisional-enrolled-voice':
            segment['playerId'] = line['playerId']
            segment['attribution'] = line['attribution']
        segments.append(segment)
    return {"schemaVersion": 1, "gameId": header["gameId"], "recordingId": header["id"],
            "previewId": root.name, "partIndex": int(part.file[5:9]), "start": part.start,
            "end": part.start + part.duration, "sourceSha256": part.sha256,
            "modelSha256": value["modelSha256"], "recognizerSha256": value["recognizerSha256"],
            "segments": segments}


def publish_pending(folder, header, root, config, api_config, *, limit=4):
    from panther_journal import live_transcript as live

    markers = root / "history-synced"
    if markers.is_symlink():
        raise click.ClickException("Unsafe history status directory")
    markers.mkdir(mode=0o700, exist_ok=True)
    sent = 0
    for part in reversed(live.completed_parts(folder, header)):
        path = root / part.file.replace(".flac", ".json")
        if not path.exists():
            continue
        marker = markers / path.name
        # Acknowledgements expire daily so active histories renew their seven-day retention.
        source_hash = live.audio.digest(path)
        if marker.exists():
            ack = live.read_json(marker)
            if ack.get("localSha256") == source_hash and time.time() - ack["syncedAt"] < 86400:
                continue
        payload = chunk_payload(folder, header, root, config, part)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(encoded) > 240000:
            raise click.ClickException("History chunk exceeds upload limit; original text remains local")
        cloud.api(api_config, "POST", "/recordings/live/history", json=payload)
        write_json(marker, {"localSha256": source_hash, "sha256": hashlib.sha256(encoded).hexdigest(),
                            "syncedAt": time.time()}, replace=True)
        sent += 1
        if sent >= limit:
            break
    return sent


def run(publisher):
    failed, config = False, None
    while not publisher.presence_ready.wait(1):
        if publisher.stop_event.is_set():
            return
    while not publisher.stop_event.is_set():
        generation = publisher.history_flush_generation
        try:
            if config is None:
                config = cloud.configuration()
            count = publish_pending(*publisher.args, config)
            write_json(publisher.root / "history-status.json",
                       {"state": "syncing" if count else "available-text-synced", "checkedAt": time.time()}, replace=True)
            if failed:
                publisher.emit("Full transcript history reconnected.")
            failed = False
            if not count and generation and generation == publisher.history_flush_generation:
                publisher.history_flushed.set()
        except Exception:
            write_json(publisher.root / "history-status.json",
                       {"state": "disconnected", "checkedAt": time.time()}, replace=True)
            if not failed:
                publisher.emit("Transcript history upload delayed; retrying. Local capture and live presence are independent.")
            failed, count = True, 0
        publisher.history_wake.wait(2 if count else 20)
        publisher.history_wake.clear()
