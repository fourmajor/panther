import json
import shutil
import subprocess
import sys
import time

import click
import pytest
from click.testing import CliRunner

from panther_journal import audio_storage, blind_audio, recording as audio, recording_sync as sync
from panther_journal.cli import main


@pytest.fixture
def source(tmp_path):
    if not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe", "flac")):
        pytest.skip("Local codec integration test needs FFmpeg and FLAC")
    folder = audio.private_folder(tmp_path, "synthetic-game", "synthetic-session")
    header = audio.header(
        folder, "synthetic-game", "synthetic-session", "synthetic tone, no microphone"
    )
    audio.write_new(folder / "capture.json", header)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "0.6",
            "-c:a",
            "flac",
            str(folder / "part-0000.flac"),
        ],
        check=True,
    )
    return folder, header


def test_atomic_manifest_never_replaces_or_leaves_partial_destination(tmp_path):
    file = tmp_path / "manifest.json"
    audio.write_new(file, {"first": True})
    with pytest.raises(FileExistsError):
        audio.write_new(file, {"second": True})
    assert json.loads(file.read_text()) == {"first": True}
    with pytest.raises(ValueError):
        audio.write_new(tmp_path / "invalid.json", {"nan": float("nan")})
    assert not (tmp_path / "invalid.json").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_checkpoint_only_accepts_closed_csv_rows(source):
    folder, header = source
    (folder / "part-0001.flac").write_bytes(b"active unfinished file")
    (folder / "segments.csv").write_text("part-0000.flac,0,0.6\npart-0001.flac,0.6,")
    parts = sync.checkpoint(folder, header)
    assert [p.file for p in parts] == ["part-0000.flac"]
    assert not (folder / "checkpoints/part-0001.json").exists()
    assert sync.checkpoint(folder, header) == parts
    (folder / "segments.csv").write_text("../private.flac,0,1\n")
    with pytest.raises(click.ClickException, match="filename"):
        sync.checkpoint(folder, header)


def test_recovery_keeps_good_parts_and_preserves_corrupt_tail(source):
    folder, header = source
    (folder / "part-0001.flac").write_bytes(b"broken tail")
    record = audio.finish_capture(folder, header, "interrupted")
    assert len(record.parts) == 1 and record.status == "interrupted"
    assert (folder / "part-0001.flac").read_bytes() == b"broken tail"
    assert json.loads((folder / "incomplete-tail.json").read_text())["excludedFromManifest"]
    assert audio.verified(folder) == record


def test_recovery_rejects_active_recording_and_changed_checkpoint(source):
    folder, header = source
    with audio_storage.lock(folder, "capture.lock"):
        assert audio_storage.capture_active(folder)
        result = CliRunner().invoke(main, ["recording", "recover", str(folder)])
        assert result.exit_code != 0 and "another process" in result.output
    assert not audio_storage.capture_active(folder)
    (folder / "segments.csv").write_text("part-0000.flac,0,0.6\n")
    sync.checkpoint(folder, header)
    (folder / "part-0000.flac").write_bytes(b"changed")
    with pytest.raises(click.ClickException, match="changed"):
        audio.finish_capture(folder, header, "interrupted")


def test_recovery_preserves_broken_pcm_tail(source):
    folder, header = source
    pcm = folder / "capture-pcm"
    pcm.mkdir()
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(folder / "part-0000.flac"),
            "-c:a",
            "pcm_s24le",
            str(pcm / "part-0000.wav"),
        ],
        check=True,
    )
    # This fixture's initial FLAC is not a capture output; retain it under another name.
    (folder / "part-0000.flac").rename(folder / "fixture-source.flac")
    (pcm / "part-0001.wav").write_bytes(b"incomplete WAV header")
    record = audio.finish_capture(folder, header, "interrupted")
    assert len(record.parts) == 1
    assert (pcm / "part-0000.wav").exists()
    assert (pcm / "part-0001.wav").read_bytes() == b"incomplete WAV header"
    report = json.loads((folder / "incomplete-tail.json").read_text())
    assert report["file"] == "capture-pcm/part-0001.wav"


def test_sync_publishes_final_manifest_when_capture_stops_during_upload(tmp_path, monkeypatch):
    statuses = iter(
        [
            {"partsSynced": 1, "complete": False},
            {"partsSynced": 2, "complete": True},
        ]
    )
    monkeypatch.setattr(sync, "sync_once", lambda folder: next(statuses))
    monkeypatch.setattr(sync, "capture_active", lambda folder: False)
    result = CliRunner().invoke(main, ["recording", "sync", str(tmp_path), "--watch"])
    assert result.exit_code == 0, result.output
    assert json.loads((tmp_path / "sync-status.json").read_text())["complete"]


def test_blind_image_requires_reviewed_local_build(monkeypatch):
    monkeypatch.setattr(
        blind_audio.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "missing"),
    )
    with pytest.raises(click.ClickException, match="Build the blind transcriber"):
        blind_audio.image_id("docker")


def test_periodic_sync_retries_without_active_chunk_or_duplicate_uploads(source, monkeypatch):
    folder, header = source
    (folder / "segments.csv").write_text("part-0000.flac,0,0.6\n")
    sync.checkpoint(folder, header)
    (folder / "part-0001.flac").write_bytes(b"active")
    monkeypatch.setattr(sync.cloud, "configuration", lambda: {})
    commits = []
    def api(config, method, route, **kwargs):
        if route == "/recording-sets/complete":
            assert "recording.json" in sent and "part-0000.flac" in sent
            commits.append(kwargs["json"])
        return {}
    monkeypatch.setattr(sync.cloud, "api", api)
    sent = []
    fail = True

    def upload(config, file, record, kind, **kwargs):
        nonlocal fail
        if file.suffix == ".flac" and fail:
            fail = False
            raise click.ClickException("Synthetic network outage")
        sent.append(file.name)

    monkeypatch.setattr(audio, "upload_one", upload)
    with audio_storage.lock(folder, "capture.lock"):
        with pytest.raises(click.ClickException, match="outage"):
            sync.sync_once(folder)
        assert sync.sync_once(folder)["partsSynced"] == 1
        assert sync.sync_once(folder)["partsSynced"] == 1
    assert sent == ["capture.json", "part-0000.flac", "part-0000.json"]
    assert "part-0001.flac" not in sent and "recording.json" not in sent
    assert not commits
    # A stopped recording recovers its intact prefix before final manifest publication.
    assert sync.sync_once(folder)["complete"]
    assert "recording.json" in sent
    assert not any(name.startswith("playback-") for name in sent)
    assert commits[0]["status"] == "COMPLETE"
    assert (folder / "part-0001.flac").exists()


def test_real_segmented_capture_writes_before_exit_and_worker_stops_on_eof(tmp_path):
    if not all(shutil.which(tool) for tool in ("ffmpeg", "flac", "ffprobe")):
        pytest.skip("Local codec integration test")
    folder = audio.private_folder(tmp_path, "synthetic-game", "synthetic-session")
    header = audio.header(folder, "synthetic-game", "synthetic-session", "synthetic tone")
    audio.write_new(folder / "capture.json", header)
    (folder / "capture-pcm").mkdir()
    if sys.platform != "darwin" or not shutil.which("pkg-config"):
        pytest.skip("Native recorder integration test needs macOS and PortAudio")
    command = audio.capture_command("--synthetic", folder, None, chunk_seconds=0.5)
    with audio_storage.lock(folder, "capture.lock") as fd:
        child = subprocess.Popen(
            [sys.executable, "-m", "panther_journal.capture_worker", json.dumps(command), str(fd)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            pass_fds=(fd,),
        )
        try:
            deadline = time.monotonic() + 8
            parts = []
            while time.monotonic() < deadline and child.poll() is None and not parts:
                time.sleep(0.1)
                parts = sync.checkpoint(folder, header)
            assert parts, "Native writer must finalize chunks before capture exits"
            assert child.poll() is None
        finally:
            child.stdin.close()  # Simulate loss of the controller, not a graceful q command.
            child.wait(timeout=20)
        assert child.returncode == 0, child.stderr.read().decode()
    record = audio.finish_capture(folder, header, "interrupted")
    assert sum(p.duration for p in record.parts) > 0.5
    decoded = []
    for part in record.parts:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(folder / part.file), "-f", "s16le", "-"],
            check=True,
            capture_output=True,
        )
        decoded.append(result.stdout)
        assert len(result.stdout) == round(part.duration * part.sampleRate) * 2
    listing = folder / "join.txt"
    listing.write_text(
        "".join(f"file '{p.file}'\nduration {p.duration:.9f}\n" for p in record.parts)
    )
    joined = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(listing),
            "-f",
            "s16le",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    assert joined.stdout == b"".join(decoded), (
        "Joining parts must not drop or duplicate PCM samples"
    )


def test_start_cli_with_synthetic_input_never_opens_a_microphone(tmp_path, monkeypatch):
    if sys.platform != "darwin" or not all(shutil.which(t) for t in ("ffmpeg", "flac", "ffprobe")):
        pytest.skip("macOS capture-controller integration test")
    original_command = audio.capture_command

    def tone(device, folder, seconds, chunk_seconds):
        return original_command("--synthetic", folder, 1.2, 0.5)

    monkeypatch.setattr(audio, "capture_command", tone)
    result = CliRunner().invoke(
        main,
        [
            "recording",
            "start",
            "--game",
            "synthetic-game",
            "--session",
            "synthetic-session",
            "--device",
            "Synthetic, not microphone",
            "--output-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    folders = list(tmp_path.glob("recording-*"))
    assert len(folders) == 1
    record = audio.verified(folders[0])
    assert len(record.parts) >= 2
    assert abs(sum(p.duration for p in record.parts) - 1.2) < 0.01
    assert not audio_storage.capture_active(folders[0])


def test_blind_transcriber_mount_allowlist_and_no_reference_context(tmp_path):
    image = "sha256:" + "a" * 64
    wav, model, output = tmp_path / "audio.wav", tmp_path / "model.bin", tmp_path / "output"
    command = blind_audio.command("docker", image, wav, model, output)
    mounts = [command[i + 1] for i, value in enumerate(command) if value == "--mount"]
    assert len(mounts) == 3
    assert mounts[0].endswith("dst=/input.wav,readonly")
    assert mounts[1].endswith("dst=/model.bin,readonly")
    assert mounts[2].endswith("dst=/output")
    assert "--network=none" in command and "--read-only" in command and "--pull=never" in command
    assert "--prompt" not in command and "-p" not in command and "-e" not in command
    assert str(tmp_path) not in command  # No parent-directory mount as a standalone source.
    manifest = blind_audio.manifest(image, "audio-sha", "model-sha")
    assert manifest["inputs"] == ["audio", "model"]
    assert not manifest["referenceScript"] and not manifest["chatHistory"]
