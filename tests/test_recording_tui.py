"""Synthetic Textual interaction and recorder-adapter tests; never open microphones."""

import asyncio
import json
from pathlib import Path
import signal
from unittest.mock import Mock

from click.testing import CliRunner
import pytest
from textual.widgets import RichLog, Static

from panther_journal.cli import main
from panther_journal.recording_tui import RecorderBackend, RecordingApp


class FakeBackend:
    game, session, device = "test-game", "test-session", "Synthetic mic"
    root = Path("/private/tmp/synthetic-tui")

    def __init__(self):
        self.started = self.stopped = False
        self.status = dict(
            running=True,
            stopping=False,
            elapsed=12,
            parts=2,
            synced=1,
            capture="Capturing locally",
            backup="1 chunk confirmed",
            preview="catching-up · provisional",
            peak=0.3,
            text="\n".join(f"[{i}s] Alex: line {i}" for i in range(100)),
            events=["Cloud backup failed. Check Panther login/network."],
            folder=self.root,
            sync={},
        )

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        self.status["stopping"] = True

    def snapshot(self):
        return dict(self.status)


@pytest.mark.parametrize("size", [(100, 36), (60, 20), (40, 16)])
def test_tui_stop_resize_errors_history_and_finalization(size, tmp_path):
    async def exercise():
        backend = FakeBackend()
        app = RecordingApp(backend, reduced_motion=True)
        async with app.run_test(size=size) as pilot:
            await app.refresh_status()
            await pilot.pause()
            assert backend.started
            assert "RECORDING" in str(app.query_one("#health", Static).content)
            assert len(app.seen_events) == 1
            app.save_screenshot(f"recording-tui-active-{size[0]}.svg", path=str(tmp_path))
            await app.refresh_status()
            assert len(app.seen_events) == 1  # errors remain, not repeated every heartbeat
            log = app.query_one("#transcript", RichLog)
            log.scroll_home(animate=False)
            await pilot.pause()
            backend.status["text"] += "\n[101s] Alex: new speech"
            await app.refresh_status()
            await pilot.pause()
            assert log.scroll_y == 0 and not app.following
            assert "line 0" in app.transcript and "new speech" in app.transcript
            # Earlier backfill must keep the visible speech anchored, not just its
            # numerical offset within a now-longer transcript.
            backend.status["text"] = "Earlier backfilled speech\n" + backend.status["text"]
            await app.refresh_status()
            await pilot.pause()
            assert log.lines[int(log.scroll_y)].text.startswith("[0s] Alex")
            await pilot.press("l")
            await pilot.pause()
            assert app.following and log.is_vertical_scroll_end
            await pilot.resize_terminal(size[0] + 10, size[1] + 5)
            await pilot.press("ctrl+c")
            assert backend.stopped
            await app.refresh_status()
            assert "FINALIZING" in str(app.query_one("#health", Static).content)
            assert app.is_running  # stopping does not quit before finalization
            backend.status.update(running=False, capture="Saved and finalized", unsynced=1)
            await app.refresh_status()
            assert "1 not yet confirmed" in str(app.query_one("#summary", Static).content)
            # The smallest view can scroll the overall body to all controls.
            if size[1] < 24:
                assert app.query_one("#body").allow_vertical_scroll
            app.save_screenshot(f"recording-tui-{size[0]}.svg", path=str(tmp_path))
            await pilot.press("q")
            assert not app.is_running

    asyncio.run(exercise())


def test_tui_status_failure_does_not_stop_independent_capture():
    async def exercise():
        backend = FakeBackend()
        backend.snapshot = Mock(side_effect=OSError("synthetic disk error"))
        app = RecordingApp(backend)
        async with app.run_test() as pilot:
            await app.refresh_status()
            await pilot.pause()
            assert not backend.stopped
            assert any("Dashboard status unavailable" in e for e in app.seen_events)
            await pilot.press("s")
            assert backend.stopped

    asyncio.run(exercise())


def backend_at(tmp_path):
    backend = RecorderBackend(
        "test-game", "test-session", "Synthetic mic", None, tmp_path, 30, True, False
    )
    folder = backend.root / "recording-synthetic"
    folder.mkdir()
    (folder / "capture.json").write_text("{}")
    backend.process = Mock(returncode=None)
    backend.process.poll.return_value = None
    return backend, folder


def test_backend_reports_stale_meter_backup_errors_and_recovery(tmp_path):
    backend, folder = backend_at(tmp_path)
    backend.started -= 120
    (folder / "sync-status.json").write_text(json.dumps({"error": "AuthenticationError"}))
    status = backend.snapshot()
    assert status["peak"] is None and "unknown" in status["capture"]
    assert any("Capture meter unavailable/stale" in event for event in status["events"])
    assert any("Panther login/network" in event for event in status["events"])
    assert not backend.process.send_signal.called
    backend.stop()
    backend.stop()
    backend.process.send_signal.assert_called_once_with(signal.SIGINT)
    backend.process.poll.return_value = 1
    backend.process.returncode = 1
    status = backend.snapshot()
    assert "recovery required" in status["capture"]
    assert any("recording recover" in event for event in status["events"])


def test_backend_launcher_reuses_plain_cli_and_keeps_logs_private(tmp_path, monkeypatch):
    backend, _ = backend_at(tmp_path)
    popen = Mock()
    monkeypatch.setattr("panther_journal.recording_tui.subprocess.Popen", popen)
    backend.start()
    args = popen.call_args.args[0]
    assert args[2:5] == ["panther_journal.cli", "recording", "start"]
    assert "--tui" not in args and "--sync" in args
    assert popen.call_args.kwargs["start_new_session"] is True
    assert (backend.root / "controller.log").stat().st_mode & 0o077 == 0


def test_plain_cli_stays_noninteractive_and_tui_flags_are_explicit():
    result = CliRunner().invoke(main, ["recording", "start", "--help"])
    assert result.exit_code == 0 and "--tui" in result.output
    result = CliRunner().invoke(
        main,
        [
            "recording",
            "start",
            "--game",
            "test-game",
            "--session",
            "test-session",
            "--device",
            "Synthetic mic",
            "--live",
        ],
    )
    assert result.exit_code != 0 and "require --tui" in result.output
