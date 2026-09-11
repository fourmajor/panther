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


def test_enrolled_live_labels_resume_and_finalize_without_inference(capture, tmp_path, monkeypatch):
    from panther_journal import speaker_profiles as speakers
    from panther_journal.live_finalize import checkpoint_lines
    from panther_journal.live_history import chunk_payload
    folder, header, model = capture
    part = add_part(capture, 0)
    speaker_model = tmp_path / 'speaker-model'
    speaker_model.mkdir()
    (speaker_model / 'weights.bin').write_bytes(b'synthetic')
    profile = tmp_path / 'profiles.json'
    embedding = [1] + [0]*15
    profile.write_text(json.dumps({'schemaVersion': 1, 'entityType': 'SpeakerRecognitionProfiles',
        'gameId': header['gameId'], 'modelFiles': speakers.model_pin(speaker_model),
        'profiles': [{'playerId': 'alex', 'identityEvidence': 'Synthetic confirmed clip', 'embedding': embedding}]}))

    def analyze(self, wav, attempt):
        result = {'turns': [{'start': 0, 'end': 5, 'speaker': 'SPEAKER_00'}],
                  'embeddings': {'SPEAKER_00': embedding}}
        (attempt / 'speaker-result.json').write_text(json.dumps(result))
        return result

    monkeypatch.setattr(speakers.SpeakerWorker, 'analyze', analyze)
    options = dict(once=True, from_start=True, transcriber=recognizer, emit=lambda _: None,
                   speaker_profiles=profile, speaker_model=speaker_model, speaker_runtime=model)
    root = live.follow(folder, model, **options)
    config = live.read_json(root / 'preview.json')
    value = live.read_json(root / 'part-0000.json')
    assert value['segments'][0]['playerId'] == 'alex'
    assert value['speakerEvidence']['speaker-result.json']
    assert chunk_payload(folder, header, root, config, part)['segments'][0]['playerId'] == 'alex'
    monkeypatch.setattr(speakers.SpeakerWorker, 'analyze', lambda *args: pytest.fail('Do not rerun saved speaker analysis'))
    assert live.follow(folder, model, **options) == root
    raw, attributed = checkpoint_lines(folder, root, config, [part])
    assert raw[0]['playerId'] is None and attributed[0]['playerId'] == 'alex'
    (root / value['attempt'] / 'speaker-result.json').write_text('{}')
    with pytest.raises(click.ClickException, match='speaker evidence changed'):
        checkpoint_lines(folder, root, config, [part])


def test_finalization_requires_every_chunk(capture):
    from panther_journal.live_finalize import checkpoint_lines
    folder, _, model = capture
    part = add_part(capture, 0)
    _, _, _, root, config = live.initialize(folder, model, True)
    with pytest.raises(click.ClickException, match='incomplete'):
        checkpoint_lines(folder, root, config, [part])


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
    assert "Joined at chunk 1" in (root / "preview.txt").read_text()
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
    add_part(capture, 2)
    named = live.initialize(folder, model, False, "web-live")
    assert named[3] != latest[3] and named[4]["startIndex"] == 2
    add_part(capture, 3)
    assert live.initialize(folder, model, False, "web-live")[4]["startIndex"] == 2


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
    (folder / "capture-settings.json").write_text(json.dumps({"chunkSeconds": 120}))
    assert snapshot(folder, header, root, config, now + 100)["captureState"] == "recording"
    monkeypatch.setattr(live, "capture_running", lambda _: False)
    assert snapshot(folder, header, root, config, now + 100)["captureState"] == "stopped"
    assert not any(k in value for k in ("audio", "sourceKeys", "playerId", "modelPath"))


def test_publisher_sends_final_capture_state_without_cloud_credentials(capture, monkeypatch):
    from panther_journal import live_publish

    folder, header, model = capture
    add_part(capture, 0)
    root = live.follow(folder, model, once=True, transcriber=recognizer, emit=lambda _: None)
    publisher = live_publish.Publisher(
        folder, header, root, live.read_json(root / "preview.json"), lambda _: None
    )
    running, sent = [True], []
    monkeypatch.setattr(live, "capture_running", lambda _: running[0])
    monkeypatch.setattr(live_publish.cloud, "configuration", lambda: {"synthetic": True})

    def post(config, method, route, **kwargs):
        assert config == {"synthetic": True} and method == "POST" and route == "/recordings/live"
        sent.append(kwargs["json"])
        running[0] = False
        publisher.stop_event.set()

    monkeypatch.setattr(live_publish.cloud, "api", post)
    publisher.run()
    assert [p["captureState"] for p in sent] == ["recording", "stopped"]
    assert live.read_json(root / "web-status.json")["state"] == "published"


def test_preview_clips_small_decoder_overrun_without_changing_raw(capture):
    part = add_part(capture, 0)
    raw = {
        "transcription": [
            {"offsets": {"from": 29040, "to": 31040}, "text": "Synthetic boundary speech"}
        ]
    }
    original = json.dumps(raw)
    lines = live.preview_lines(raw, part)
    assert lines[0]["start"] == 29.04 and lines[0]["end"] == 30
    assert lines[0]["timingNote"] and live.render_line(lines[0]).startswith("~[")
    assert json.dumps(raw) == original
    with pytest.raises(click.ClickException):
        audio.transcript_lines(raw, part, None)  # Final transcript remains strict.
    raw["transcription"][0]["offsets"]["to"] = 40000
    with pytest.raises(click.ClickException):
        live.preview_lines(raw, part)


@pytest.mark.parametrize("segment", [
    {"offsets": {"from": 28000, "to": 38160}, "text": "Synthetic overrun"},
    {"offsets": {"from": -1, "to": 1000}, "text": "Negative"},
    {"offsets": {"from": float("nan"), "to": 1000}, "text": "Nonfinite"},
    {"offsets": {"from": 2000, "to": 1000}, "text": "Reversed"},
    {"text": "Missing offsets"},
    {"offsets": {"from": 0, "to": 1000}, "text": None},
    None,
])
def test_invalid_recognition_is_preserved_gap_and_following_chunk_continues(capture, segment):
    from panther_journal.live_publish import snapshot

    folder, header, model = capture
    add_part(capture, 0)
    add_part(capture, 1)
    raw = json.dumps({"transcription": [segment]})
    messages = []

    def bad_then_good(folder, part, model, attempt):
        if part.start == 0:
            (attempt / "recognizer.json").write_text(raw)
            return live.preview_lines(json.loads(raw), part)
        return recognizer(folder, part, model, attempt)

    root = live.follow(folder, model, from_start=True, transcriber=bad_then_good, emit=messages.append)
    saved = live.read_json(root / "part-0000.json")
    assert saved["segments"] == [{"kind": "preview-gap", "start": 0.0, "end": 30.0,
                                 "text": live.GAP_NOTICE}]
    assert (root / saved["attempt"] / "recognizer.json").read_text() == raw
    assert live.read_json(root / "status.json")["chunksTranscribed"] == 2
    assert any(live.GAP_NOTICE in message for message in messages)
    assert "No speech recognized" not in (root / "preview.txt").read_text()
    config = live.read_json(root / "preview.json")
    web = snapshot(folder, header, root, config)
    assert web["segments"][0]["kind"] == "preview-gap"
    assert web["segments"][1]["text"] == "Synthetic preview"
    before = (root / "part-0000.json").read_bytes()
    live.follow(folder, model, from_start=True,
                transcriber=lambda *a: pytest.fail("Do not retry a saved gap"), emit=lambda _: None)
    assert (root / "part-0000.json").read_bytes() == before


@pytest.mark.parametrize("target", ["audio", "model"])
def test_invalid_recognition_never_bypasses_input_integrity(capture, target):
    folder, _, model = capture
    add_part(capture, 0)

    def corrupt(folder, part, model, attempt):
        (attempt / "recognizer.json").write_text("{}")
        (model if target == "model" else folder / part.file).write_bytes(b"changed")
        raise live.PreviewOutputError("Synthetic bad output")

    with pytest.raises(click.ClickException, match="changed"):
        live.follow(folder, model, once=True, transcriber=corrupt, emit=lambda _: None)
    assert not list((folder / "live-preview").glob("*/part-0000.json"))


def test_out_of_order_recognition_is_not_published(capture):
    part = add_part(capture, 0)
    with pytest.raises(live.PreviewOutputError):
        live.preview_lines({"transcription": [
            {"offsets": {"from": 5000, "to": 6000}, "text": "Later"},
            {"offsets": {"from": 1000, "to": 2000}, "text": "Earlier"},
        ]}, part)


def test_malformed_json_gap_retains_raw_and_detects_later_tampering(capture, monkeypatch):
    folder, _, model = capture
    add_part(capture, 0)

    def mock_process(command, attempt, log_name, **kwargs):
        if log_name == "recognizer.log":
            (attempt / "recognizer.json").write_text("{malformed")

    monkeypatch.setattr(live, "run_process", mock_process)
    monkeypatch.setattr(audio, "executable", lambda name: name)
    root = live.follow(folder, model, once=True, emit=lambda _: None)
    result = live.read_json(root / "part-0000.json")
    raw = root / result["attempt"] / "recognizer.json"
    assert raw.read_text() == "{malformed"
    assert result["segments"][0]["kind"] == "preview-gap"
    raw.write_text("{changed")
    with pytest.raises(click.ClickException, match="Preserved recognizer output changed"):
        live.follow(folder, model, once=True, emit=lambda _: None)


def test_backfill_starts_at_beginning_but_new_audio_has_priority(capture):
    folder, _, model = capture
    for index in range(3):
        add_part(capture, index)
    processed = []

    def record_order(folder, part, model, attempt):
        processed.append(int(part.file[5:9]))
        if part.start == 0:
            add_part(capture, 3)
        return recognizer(folder, part, model, attempt)

    root = live.follow(folder, model, transcriber=record_order, emit=lambda _: None)
    assert processed == [2, 0, 3, 1]
    assert live.read_json(root / "status.json")["backfillPendingChunks"] == 0
    text = (root / "preview.txt").read_text()
    assert text.index("[00:00:01]") < text.index("[00:00:31]") < text.index("[00:01:01]")
    before = {p: p.read_bytes() for p in root.glob("part-*.json")}
    live.follow(folder, model, transcriber=lambda *a: pytest.fail("No repeated inference"), emit=lambda _: None)
    assert all(p.read_bytes() == data for p, data in before.items())


def test_history_upload_is_complete_idempotent_and_includes_backfilled_chunks(capture, monkeypatch):
    from panther_journal import live_history

    folder, header, model = capture
    add_part(capture, 0)
    add_part(capture, 1)
    root = live.follow(folder, model, transcriber=recognizer, emit=lambda _: None)
    config = live.read_json(root / "preview.json")
    sent = []
    monkeypatch.setattr(live_history.cloud, "api", lambda c,m,r,**kw: sent.append((m,r,kw["json"])))
    assert live_history.publish_pending(folder, header, root, config, {}) == 2
    assert [body["partIndex"] for _,_,body in sent] == [1, 0]
    assert all(route == "/recordings/live/history" for _,route,_ in sent)
    assert all(body["modelSha256"] == config["settings"]["modelSha256"] for _,_,body in sent)
    assert live_history.publish_pending(folder, header, root, config, {}) == 0
    assert len(sent) == 2
