"""Optional, independent publisher for ephemeral web presence and recent preview text."""

import json
import threading
import time

from panther_journal import cloud
from panther_journal.audio_storage import write_json


def snapshot(folder, header, root, config, now=None):
    from panther_journal import live_transcript as live

    now = time.time() if now is None else now
    parts = live.completed_parts(folder, header)
    running = live.capture_running(folder)
    journal = folder / "segments.csv"
    progress = (
        journal.stat().st_mtime if journal.is_file() else (folder / "capture.json").stat().st_mtime
    )
    stale_capture = now - progress > max(90, header.get("chunkSeconds", 30) * 2 + 15)
    status_file = root / "status.json"
    status = live.read_json(status_file) if status_file.exists() else {"state": "starting"}
    chunks, lines = [], []
    # A bounded recent window, not a parallel permanent transcript asset.
    for part in reversed(parts[config["startIndex"] :]):
        path = root / part.file.replace(".flac", ".json")
        if not path.exists():
            continue
        chunks.append(live.read_json(path))
        if sum(len(c["segments"]) for c in chunks) >= 60:
            break
    for value in reversed(chunks):
        for line in value["segments"]:
            text = " ".join("".join(c for c in line["text"] if c.isprintable()).split())[:500]
            if text:
                lines.append({"start": line["start"], "end": line["end"], "text": text})
    payload = {
        "schemaVersion": 1,
        "gameId": header["gameId"],
        "sessionId": header["sessionId"],
        "recordingId": header["id"],
        "previewId": root.name,
        "observedAt": int(now * 1000),
        "captureState": "stopped" if not running else "stalled" if stale_capture else "recording",
        "captureSeconds": sum(p.duration for p in parts),
        "previewState": status["state"],
        "segments": lines[-60:],
        "omittedChunks": config["startIndex"],
    }
    while len(json.dumps(payload).encode()) > 32000 and payload["segments"]:
        payload["segments"].pop(0)
    return payload


class Publisher:
    """Network delays never block recognition or capture. No audio is sent by this worker."""

    def __init__(self, folder, header, root, config, emit):
        self.args = (folder, header, root, config)
        self.root, self.emit = root, emit
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="panther-live-web", daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop_event.set()
        self.thread.join(timeout=2)
        # A dead/closed preview stops heartbeats; the server/browser expires presence.

    def run(self):
        config, failed = None, False
        while not self.stop_event.is_set():
            try:
                payload = snapshot(*self.args)
                if config is None:
                    config = cloud.configuration()
                cloud.api(config, "POST", "/recordings/live", json=payload)
                write_json(
                    self.root / "web-status.json",
                    {"state": "published", "checkedAt": time.time()},
                    replace=True,
                )
                if failed:
                    self.emit("Web live feed reconnected.")
                failed = False
            except Exception:
                # Never persist API URLs, tokens, transcript text or credential-bearing errors.
                write_json(
                    self.root / "web-status.json",
                    {"state": "disconnected", "checkedAt": time.time()},
                    replace=True,
                )
                if not failed:
                    self.emit(
                        "Web live feed disconnected. Check connectivity / panther login in another terminal. Local recording and preview continue."
                    )
                failed = True
            if self.stop_event.wait(20):
                return
