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
    settings_file = folder / "capture-settings.json"
    settings = live.read_json(settings_file) if settings_file.exists() else {}
    stale_capture = now - progress > max(90, settings.get("chunkSeconds", 30) * 2 + 15)
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
                segment = {"start": line["start"], "end": line["end"], "text": text}
                if line.get("kind") == "preview-gap":
                    segment["kind"] = "preview-gap"
                if line.get("timingNote"):
                    segment["approximateTiming"] = True
                if line.get('playerId') and line.get('attribution') == 'provisional-enrolled-voice':
                    segment['playerId'] = line['playerId']
                    segment['attribution'] = line['attribution']
                lines.append(segment)
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
        self.presence_ready = threading.Event()
        self.history_wake = threading.Event()
        self.history_flushed = threading.Event()
        self.history_flush_generation = 0
        self.thread = threading.Thread(target=self.run, name="panther-live-web", daemon=True)
        from panther_journal.live_history import run as history_run
        self.history_thread = threading.Thread(target=history_run, args=(self,), name="panther-live-history", daemon=True)

    def __enter__(self):
        self.thread.start()
        self.history_thread.start()
        return self

    def __exit__(self, *_):
        self.stop_event.set()
        self.history_wake.set()
        self.thread.join(timeout=5)
        self.history_thread.join(timeout=5)
        # Best-effort final state; abrupt shutdown/network failure still expires presence.

    def flush_history(self, timeout=45):
        """Bounded final drain after capture/backfill ends; capture is already independent."""
        self.history_flushed.clear()
        self.history_flush_generation += 1
        self.history_wake.set()
        if not self.history_flushed.wait(timeout):
            self.emit("Some full transcript history is not synced yet. Resume this live command to retry; all text remains local.")

    def run(self):
        config, failed = None, False
        while True:
            final = self.stop_event.is_set()
            try:
                payload = snapshot(*self.args)
                if config is None:
                    config = cloud.configuration()
                cloud.api(config, "POST", "/recordings/live", json=payload)
                self.presence_ready.set()
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
            if final:
                return
            self.stop_event.wait(20)
