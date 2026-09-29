"""An advisory display around the existing recorder, never an audio producer."""

from __future__ import annotations

import asyncio
import json
import math
import signal
import subprocess
import sys
import time

import click
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Button, Footer, RichLog, Static

from panther_journal import recording as audio


def read_json(path, maximum=65536):
    if not path.exists():
        return {}
    if path.is_symlink() or path.stat().st_size > maximum:
        raise ValueError("Unsafe or oversized status file")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Invalid status file")
    return value


class RecorderBackend:
    """Separate processes keep capture independent of Textual and recognition latency."""

    def __init__(self, game, session, device, seconds, root, chunk_seconds, sync, live):
        self.game, self.session, self.device = game, session, device
        self.seconds, self.chunk_seconds = seconds, chunk_seconds
        self.sync, self.live = sync, live
        self.root = audio.private_folder(root, game, session)
        self.folder = None
        self.process = self.preview = None
        self.stopping = False
        self.started = time.time()
        self.ended = None

    def start(self):
        command = [
            sys.executable,
            "-m",
            "panther_journal.cli",
            "recording",
            "start",
            "--game",
            self.game,
            "--session",
            self.session,
            "--device",
            self.device,
            "--output-root",
            str(self.root),
            "--chunk-seconds",
            str(self.chunk_seconds),
        ]
        command.append("--sync" if self.sync else "--no-sync")
        if self.seconds:
            command += ["--seconds", str(self.seconds)]
        with (self.root / "controller.log").open("x") as log:
            self.process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True
            )

    def stop(self):
        if self.process and self.process.poll() is None and not self.stopping:
            self.stopping = True
            try:
                self.process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass  # It finalized between poll and the stop request.

    def close(self):
        self.stop()
        if self.process:
            try:
                self.process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                # Do not kill a controller that may be preserving its final chunk.
                click.echo(
                    f"Recorder still finalizing. Inspect {self.root}; do not delete it.", err=True
                )
        if self.preview and self.preview.poll() is None:
            try:
                self.preview.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                self.preview.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.preview.terminate()  # Only the read-only recognizer, never capture.

    def snapshot(self):
        if not self.folder:
            folders = list(self.root.glob("recording-*/capture.json"))
            if len(folders) == 1:
                self.folder = folders[0].parent
        running = self.process is not None and self.process.poll() is None
        if not running and self.process is not None and self.ended is None:
            self.ended = time.time()
        result = dict(
            running=running,
            stopping=self.stopping,
            folder=self.folder,
            elapsed=max(0, (self.ended or time.time()) - self.started),
            parts=0,
            synced=0,
            capture="Starting recorder…",
            backup="Disabled",
            preview="Disabled",
            text=None,
            peak=None,
            events=[],
        )
        if not self.folder:
            if not running:
                result["events"].append(
                    f"Recorder did not start. Check microphone permissions and {self.root / 'controller.log'}."
                )
            return result
        if self.live and self.preview is None and running and not self.stopping:
            command = [
                sys.executable,
                "-m",
                "panther_journal.cli",
                "recording",
                "live",
                str(self.folder),
                "--from-start",
            ]
            if not self.sync:
                command.append("--local-only")
            with (self.folder / "tui-preview.log").open("x") as log:
                self.preview = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
        result["parts"] = len(list((self.folder / "checkpoints").glob("part-*.json")))
        for name, label in [
            ("capture-meter.json", "meter"),
            ("sync-status.json", "sync"),
            ("recording.json", "recording"),
        ]:
            try:
                result[label] = read_json(
                    self.folder / name, 2 * 1024 * 1024 if label == "recording" else 65536
                )
                if label == "recording" and result[label]:
                    audio.Recording.model_validate(result[label])
            except (OSError, ValueError):
                result[label] = {}
                result["events"].append(
                    f"Cannot read {name}; check disk access. Capture status is unknown."
                )
        meter = result["meter"]
        if (
            meter
            and isinstance(meter.get("checkedAt"), (int, float))
            and time.time() - meter["checkedAt"] <= 3
        ):
            peak = meter.get("peak")
            if isinstance(peak, (int, float)) and math.isfinite(peak) and 0 <= peak <= 1:
                result["peak"] = peak
            result["capture"] = (
                "Capturing locally"
                if running and meter.get("running")
                else "Finalizing local audio"
                if running
                else "Stopped"
            )
            if meter.get("errorCode"):
                result["events"].append(
                    f"Capture fault {meter['errorCode']}: audio may be incomplete. Inspect capture.log and run recording audit; originals retained."
                )
        else:
            result["capture"] = (
                "Capture signal unknown — meter unavailable/stale" if running else "Stopped"
            )
            if running and result["elapsed"] > 5:
                result["events"].append(
                    "Capture meter unavailable/stale. Check microphone and capture.log; recording presence is not sound-quality confirmation."
                )
        if self.sync:
            sync = result["sync"]
            result["synced"] = sync.get("partsSynced", 0)
            result["backup"] = (
                "Complete"
                if sync.get("complete") and not sync.get("error")
                else f"{result['synced']} chunks confirmed; remainder pending"
            )
            if sync.get("error"):
                result["events"].append(
                    f"Cloud backup failed ({sync['error']}). Local audio retained. Check Panther login/network, then run recording sync on this folder."
                )
            elif running and time.time() - sync.get("checkedAt", self.started) > 90:
                result["events"].append(
                    "Cloud backup status is stale. Check sync.log and Panther login/network; local capture continues."
                )
        if self.live:
            result["preview"] = "Starting local recognizer…"
            previews = sorted((self.folder / "live-preview").glob("*/preview.txt"))
            if len(previews) > 1:
                result["preview"] = "Multiple preview histories — selection unknown"
                result["events"].append(
                    "Multiple local preview histories exist. The dashboard will not guess which is authoritative; inspect live-preview folders. Capture is independent."
                )
            if len(previews) == 1:
                path = previews[0]
                if not path.is_symlink() and path.stat().st_size <= 32 * 1024 * 1024:
                    result["text"] = path.read_text()
                else:
                    result["events"].append(
                        "Transcript preview too large or unsafe; open the retained preview.txt directly. No source text removed."
                    )
                try:
                    status = read_json(path.parent / "status.json")
                    result["preview"] = (
                        f"{status.get('state', 'unknown')} · {status.get('chunksTranscribed', 0)} chunks; provisional"
                    )
                    if status.get("error"):
                        result["events"].append(
                            "Live transcription failed. Check tui-preview.log; capture and backup run independently."
                        )
                except (OSError, ValueError):
                    result["events"].append(
                        "Live preview status unreadable. Capture is independent; check tui-preview.log."
                    )
            if self.preview and self.preview.poll() not in {None, 0}:
                result["preview"] = "Failed — local capture unaffected"
                result["events"].append(
                    "Live worker exited with an error. Check local model/tools and tui-preview.log; restart recording live for this folder."
                )
        if not running:
            complete = bool(result["recording"])
            result["capture"] = (
                "Saved and finalized"
                if complete
                else "Stopped without final manifest — recovery required"
            )
            if self.process.returncode:
                result["events"].append(
                    "Recorder reported an error. Preserve this folder; inspect controller.log/capture.log and run recording recover then audit."
                )
            result["unsynced"] = max(0, result["parts"] - result["synced"])
        return result


class RecordingApp(App):
    TITLE = "Panther · recording den"
    CSS = """
    Screen { background: #101914; color: #edf2e9; }
    #body { height: 1fr; padding: 0 1; }
    #identity { height: auto; padding: 1; color: #e9c96b; border: round #697e60; }
    #health { height: auto; padding: 0 1; border: round #697e60; }
    #transcript { min-height: 8; height: 14; border: round #e9c96b; }
    #events { height: 7; min-height: 4; border: round #e69b76; }
    Button { margin: 0 1 0 0; }
    #summary { height: auto; color: #e9c96b; }
    """
    BINDINGS = [
        Binding("ctrl+c", "stop", "Stop safely", priority=True),
        Binding("s", "stop", "Stop"),
        Binding("l", "live", "Return to live"),
        Binding("q", "quit", "Stop / exit"),
        Binding("h", "help", "Help"),
    ]

    def __init__(self, backend, *, reduced_motion=False):
        super().__init__()
        self.backend, self.reduced_motion = backend, reduced_motion
        self.latest, self.transcript = {}, ""
        self.seen_events = set()
        self.polling = False
        self.following = True
        self.tick = 0

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="body"):
            yield Static(id="identity", markup=False)
            yield Static("Starting independent recorder…", id="health", markup=False)
            yield RichLog(id="transcript", wrap=True, markup=False, auto_scroll=True)
            yield RichLog(id="events", wrap=True, markup=False, auto_scroll=True)
            yield Static(id="summary", markup=False)
        # The safety control stays outside the scrollable body at every size.
        yield Button("Stop & save", id="stop", variant="warning")
        yield Footer()

    def on_mount(self):
        self.query_one(
            "#transcript"
        ).border_title = "Live transcript · provisional · entire history"
        self.query_one("#events").border_title = "Persistent events & recovery"
        self.query_one("#identity", Static).update(
            Text(
                f" /\\_/\\  PANTHER · recording den\n( o.o )  {self.backend.game} / {self.backend.session}\n > ^ <   Microphone: {self.backend.device}"
            )
        )
        self.backend.start()
        self.set_interval(0.5, self.refresh_status)

    async def refresh_status(self):
        if self.polling:
            return
        self.polling = True
        try:
            snapshot = await asyncio.to_thread(self.backend.snapshot)
            self.draw(snapshot)
        except Exception as error:
            self.add_event(
                f"Dashboard status unavailable ({type(error).__name__}). Recorder is independent; inspect the private folder. Stop safely with S."
            )
        finally:
            self.polling = False

    def add_event(self, message):
        if message not in self.seen_events:
            self.seen_events.add(message)
            self.query_one("#events", RichLog).write(Text(message))

    def draw(self, status):
        self.latest = status
        self.tick += 1
        indicator = "●" if self.reduced_motion or self.tick % 2 else "○"
        minutes, seconds = divmod(int(status["elapsed"]), 60)
        peak = status.get("peak")
        level = (
            "Unavailable (not proof of silence)"
            if peak is None
            else f"{'▰' * round(peak * 16):▱<16} peak {20 * math.log10(max(peak, 1e-6)):.1f} dBFS"
        )
        recording = (
            f"{indicator} RECORDING"
            if status["running"]
            and not status["stopping"]
            and status["capture"] == "Capturing locally"
            else "FINALIZING"
            if status["running"] and status["stopping"]
            else "CAPTURE UNCONFIRMED"
            if status["running"]
            else "STOPPED"
        )
        self.query_one("#health", Static).update(
            Text(
                f"{recording} · {minutes:02}:{seconds:02}\nLocal: {status['capture']} · {status['parts']} FLAC chunks saved\n"
                f"Level: {level} (not a quality check)\nCloud: {status['backup']}\nTranscript: {status['preview']}"
            )
        )
        log = self.query_one("#transcript", RichLog)
        text = status.get("text")
        if text is not None and text != self.transcript:
            following = self.following and log.is_vertical_scroll_end
            offset = log.scroll_y
            anchor = log.lines[min(int(offset), len(log.lines) - 1)].text if log.lines else None
            log.auto_scroll = following
            # Backfill can insert earlier entries. Re-render the complete retained view,
            # preserving reading position instead of dropping the beginning.
            log.clear()
            for line in text.splitlines():
                log.write(Text(line), scroll_end=following)
            if not following:

                def restore_position():
                    matches = [i for i, line in enumerate(log.lines) if line.text == anchor]
                    log.scroll_to(
                        y=min(matches, key=lambda i: abs(i - offset)) if matches else offset,
                        animate=False,
                    )

                self.call_after_refresh(restore_position)
                self.following = False
            self.transcript = text
        for message in status["events"]:
            self.add_event(message)
        if not status["running"]:
            self.query_one("#stop", Button).disabled = True
            folder = status.get("folder") or self.backend.root
            unsynced = status.get("unsynced", status["parts"])
            self.query_one("#summary", Static).update(
                Text(
                    f"Local folder: {folder}\n{status['parts']} saved chunks · {unsynced} not yet confirmed in cloud. "
                    f"Cloud set finalized: {'yes' if status.get('sync', {}).get('complete') else 'no'}.\n"
                    f"Resume backup: panther recording sync '{folder}'\nPress Q to exit. Originals are never deleted."
                )
            )

    def action_stop(self):
        self.backend.stop()
        self.add_event(
            "Stop requested. Waiting for the recorder to close and verify its final audio; backup remains independent."
        )

    def action_quit(self):
        if self.latest.get("running", True):
            self.action_stop()
        else:
            self.exit()

    def action_live(self):
        self.following = True
        log = self.query_one("#transcript", RichLog)
        log.auto_scroll = True
        log.scroll_end(animate=False)

    def action_help(self):
        self.add_event(
            "S / Ctrl+C: stop and finalize; Q: stop first, then exit after finalization; L: return to live. Tab: change focus; arrows/PageUp/PageDown: read history. Recording, backup and provisional transcription are separate. No animation: --reduced-motion."
        )

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "stop":
            self.action_stop()


def launch(game, session, device, seconds, root, chunk_seconds, sync, live, reduced_motion):
    if sys.platform != "darwin" or not device or ":" in device or device.startswith("--"):
        raise click.ClickException("Choose an exact macOS microphone device.")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise click.ClickException("--tui needs an interactive terminal; omit it for scripts.")
    for name in ("ffmpeg", "ffprobe", "flac"):
        audio.executable(name)
    from panther_journal.native_capture import binary

    binary()
    backend = RecorderBackend(game, session, device, seconds, root, chunk_seconds, sync, live)
    try:
        RecordingApp(backend, reduced_motion=reduced_motion).run()
    finally:
        backend.close()
        click.echo(
            f"Recording files and controller log retained in: {backend.folder or backend.root}"
        )
