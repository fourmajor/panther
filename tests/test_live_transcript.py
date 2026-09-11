"""No microphone or inference service is used by this suite."""

import json
import shutil
import subprocess
from types import SimpleNamespace

import click
from click.testing import CliRunner
import pytest

from panther_journal import live_transcript as live, recording as audio
from panther_journal.audio_storage import lock
from panther_journal.cli import main


@pytest.fixture
def capture(tmp_path, monkeypatch):
    folder = tmp_path / ("recording-" + "a" * 32)
    folder.mkdir()
    (folder / "checkpoints").mkdir()
    (folder / "capture.lock").touch()
    header = {
        "id": folder.name,
        "gameId": "test-game",
        "sessionId": "test-session",
        "device": "Synthetic input",
        "startedAt": "2026-09-10T00:00:00Z",
    }
    (folder / "capture.json").write_text(json.dumps(header))
    model = tmp_path / "weights.bin"
    model.write_bytes(b"x" * 1024**2)
    monkeypatch.setattr(
        live.audio.cloud,
        "api",
        lambda *a, **kw: pytest.fail("Live preview must not call Panther/cloud"),
    )
    return folder, header, model


def add_part(capture, index):
    folder, header, _ = capture
    file = folder / f"part-{index:04d}.flac"
    file.write_bytes(f"synthetic closed part {index}".encode())
    part = audio.Part(
        file=file.name,
        start=float(index * 30),
        duration=30.0,
        size=file.stat().st_size,
        sha256=audio.digest(file),
        sampleRate=48000,
        channels=1,
        bitsPerSample=24,
    )
    (folder / "checkpoints" / f"part-{index:04d}.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "entityType": "RecordingCheckpoint",
                "recordingId": header["id"],
                "gameId": header["gameId"],
                "sessionId": header["sessionId"],
                "part": part.model_dump(),
            }
        )
    )
    return part


def recognizer(folder, part, model, attempt):
    raw = {"transcription": [{"offsets": {"from": 1000, "to": 4000}, "text": "Synthetic preview"}]}
    (attempt / "recognizer.json").write_text(json.dumps(raw))
    return audio.transcript_lines(raw, part, None)


def test_only_completed_chunks_and_capture_is_untouched(capture):
    folder, header, model = capture
    add_part(capture, 0)
    second = add_part(capture, 1)
    (folder / "capture-pcm").mkdir()
    (folder / "capture-pcm" / "part-0002.wav").write_bytes(b"still being recorded")
    (folder / "part-0002.flac").write_bytes(b"uncheckpointed")
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    messages = []
    with lock(folder, "capture.lock"):
        root = live.follow(folder, model, once=True, transcriber=recognizer, emit=messages.append)
        assert live.capture_running(folder)
    value = live.read_json(root / "part-0001.json")
    assert value["sourcePart"] == second.model_dump()
    assert value["segments"][0]["start"] == 31
    assert value["segments"][0]["playerId"] is None
    assert value["extra"]["contextUse"] == "exclude"
    assert value["extra"]["generation"]["inference"] == "local"
    assert value["extra"]["generation"]["cost"] == {"status": "not-applicable"}
    assert "Earlier chunks omitted: 1" in (root / "preview.txt").read_text()
    assert not (root / "part-0002.json").exists()
    assert all(p.read_bytes() == data for p, data in before.items())
    assert not (folder / "recording.json").exists()
    assert not (folder / "sync-status.json").exists()
    assert any("provisional" in m for m in messages)


def test_resume_consumes_next_chunk_without_retranscribing(capture):
    folder, _, model = capture
    add_part(capture, 0)
    root = live.follow(
        folder, model, from_start=True, once=True, transcriber=recognizer, emit=lambda _: None
    )
    saved = (root / "part-0000.json").read_bytes()
    add_part(capture, 1)

    def only_next(folder, part, model, attempt):
        assert part.file == "part-0001.flac"
        return recognizer(folder, part, model, attempt)

    resumed = live.follow(
        folder, model, from_start=True, once=True, transcriber=only_next, emit=lambda _: None
    )
    assert root == resumed and (root / "part-0000.json").read_bytes() == saved
    assert "[00:00:31]" in (root / "preview.txt").read_text()
    assert live.read_json(root / "status.json")["chunksTranscribed"] == 2


def test_corruption_stops_preview_without_touching_capture(capture):
    folder, _, model = capture
    part = add_part(capture, 0)
    root = live.follow(folder, model, once=True, transcriber=recognizer, emit=lambda _: None)
    (folder / part.file).write_bytes(b"changed")
    with pytest.raises(click.ClickException, match="audio changed"):
        live.follow(folder, model, once=True, transcriber=recognizer, emit=lambda _: None)
    assert live.read_json(root / "status.json")["state"] == "preview-error"
    assert not (folder / "recording.json").exists()


def test_partial_attempt_is_retained_and_retry_resumes(capture):
    folder, _, model = capture
    add_part(capture, 0)

    def fail(folder, part, model, attempt):
        (attempt / "partial.txt").write_text("keep")
        raise click.ClickException("Synthetic failure")

    with pytest.raises(click.ClickException):
        live.follow(folder, model, once=True, transcriber=fail, emit=lambda _: None)
    root = live.follow(folder, model, once=True, transcriber=recognizer, emit=lambda _: None)
    assert len(list(root.glob("attempt-*/partial.txt"))) == 1
    assert (root / "part-0000.json").exists()


def test_latest_preview_and_from_start_are_distinct(capture):
    folder, _, model = capture
    add_part(capture, 0)
    add_part(capture, 1)
    latest = live.initialize(folder, model, False)
    beginning = live.initialize(folder, model, True)
    assert latest[3] != beginning[3]
    assert latest[4]["startIndex"] == 1 and beginning[4]["startIndex"] == 0


def test_terminal_controls_are_not_emitted():
    text = live.render_line({"start": 3661, "text": "hello\x1b[31m\nthere\x07"})
    assert "\x1b" not in text and "\x07" not in text and "\n" not in text
    assert text.startswith("[01:01:01]")


def test_checkpoint_identity_and_timeline_guard(capture):
    folder, header, model = capture
    add_part(capture, 0)
    path = folder / "checkpoints" / "part-0000.json"
    value = json.loads(path.read_text())
    value["gameId"] = "different-game"
    path.write_text(json.dumps(value))
    with pytest.raises(click.ClickException, match="identity/order"):
        live.completed_parts(folder, header)


def test_low_disk_and_ctrl_c_only_stop_preview(capture, monkeypatch):
    folder, _, model = capture
    add_part(capture, 0)
    monkeypatch.setattr(live.shutil, "disk_usage", lambda p: SimpleNamespace(free=10))
    with pytest.raises(click.ClickException, match="1 GiB"):
        live.follow(folder, model, once=True, transcriber=recognizer, emit=lambda _: None)
    monkeypatch.setattr(live.shutil, "disk_usage", lambda p: SimpleNamespace(free=10 * 1024**3))

    def interrupt(*args):
        raise KeyboardInterrupt()

    with lock(folder, "capture.lock"):
        root = live.follow(folder, model, transcriber=interrupt, emit=lambda _: None)
        assert live.capture_running(folder)
    assert live.read_json(root / "status.json")["state"] == "preview-stopped"


def test_real_decode_and_bounded_whisper_invocation(capture, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    folder, _, model = capture
    file = folder / "part-0000.flac"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-n",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=300:duration=1",
            str(file),
        ],
        check=True,
        capture_output=True,
    )
    part = audio.Part(
        file=file.name,
        start=0.0,
        size=file.stat().st_size,
        sha256=audio.digest(file),
        **audio.probe(file),
    )
    attempt = folder / "test-attempt"
    attempt.mkdir()
    original_run = live.run_process

    def run(command, directory, log_name, **kwargs):
        if log_name == "decode.log":
            return original_run(command, directory, log_name, **kwargs)
        assert "-ng" in command and command[command.index("-t") + 1] == "2"
        assert "--prompt" not in command and "-mc" in command
        assert str(file) not in command  # Whisper gets only a decoded audio-only WAV.
        assert (directory / "input.wav").exists()
        (directory / "recognizer.json").write_text(json.dumps({"transcription": []}))

    monkeypatch.setattr(live, "run_process", run)
    assert live.transcribe_part(folder, part, model, attempt) == []


def test_cli_help():
    result = CliRunner().invoke(main, ["recording", "live", "--help"])
    assert result.exit_code == 0
    assert "second terminal" in result.output and "--from-start" in result.output


def test_follows_new_checkpoint_and_finishes_without_finalizing(capture, monkeypatch):
    folder, _, model = capture
    add_part(capture, 0)
    running = [True]
    monkeypatch.setattr(live, "capture_running", lambda _: running[0])

    def next_checkpoint(_):
        add_part(capture, 1)
        running[0] = False

    monkeypatch.setattr(live.time, "sleep", next_checkpoint)
    root = live.follow(folder, model, transcriber=recognizer, emit=lambda _: None)
    assert live.read_json(root / "status.json")["chunksTranscribed"] == 2
    assert live.read_json(root / "status.json")["state"] == "stopped"
    assert not (folder / "recording.json").exists()


def test_timeout_terminates_only_preview_child_group(tmp_path, monkeypatch):
    killed, launched = [], []

    class Child:
        pid = 123456
        waits = 0

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("synthetic preview", timeout)
            return 0

        def poll(self):
            return None

    def launch(command, **kwargs):
        launched.append((command, kwargs))
        return Child()

    monkeypatch.setattr(live.subprocess, "Popen", launch)
    monkeypatch.setattr(live.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(click.ClickException, match="time limit"):
        live.run_process(["synthetic"], tmp_path, "log", timeout=1)
    assert killed == [(123456, live.signal.SIGTERM)]
    command, options = launched[0]
    assert command[1:3] == ["-n", "15"]
    assert options["start_new_session"] is True
    assert options["env"]["VECLIB_MAXIMUM_THREADS"] == "2"


def test_web_snapshot_contains_recent_text_not_audio_and_capture_health(capture, monkeypatch):
    from panther_journal.live_publish import snapshot

    folder, header, model = capture
    add_part(capture, 0)
    root = live.follow(folder, model, once=True, transcriber=recognizer, emit=lambda _: None)
    config = live.read_json(root / "preview.json")
    monkeypatch.setattr(live, "capture_running", lambda _: True)
    now = (folder / "capture.json").stat().st_mtime
    value = snapshot(folder, header, root, config, now)
    assert value["captureState"] == "recording"
    assert value["segments"] == [{"start": 1.0, "end": 4.0, "text": "Synthetic preview"}]
    assert snapshot(folder, header, root, config, now + 100)["captureState"] == "stalled"
    monkeypatch.setattr(live, "capture_running", lambda _: False)
    assert snapshot(folder, header, root, config, now + 100)["captureState"] == "stopped"
    assert not any(k in value for k in ("audio", "sourceKeys", "playerId", "modelPath"))
