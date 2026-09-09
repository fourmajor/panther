"""Native integration tests use generated integer ramps; never open a microphone."""

import json
import shutil
import subprocess
import sys
import time
import wave

import pytest

from panther_journal import recording as audio
from panther_journal.capture_audit import audit
from panther_journal.native_capture import binary


@pytest.fixture
def native():
    if sys.platform != "darwin" or not shutil.which("pkg-config"):
        pytest.skip("Native Core Audio build needs macOS/PortAudio")
    result = subprocess.run(["pkg-config", "--exists", "portaudio-2.0"])
    if result.returncode:
        pytest.skip("PortAudio not installed")
    return binary()


def folder_at(root):
    folder = audio.private_folder(root, "synthetic-game", "synthetic-session")
    (folder / "capture-pcm").mkdir()
    header = audio.header(folder, "synthetic-game", "synthetic-session", "Synthetic ramp")
    audio.write_new(folder / "capture.json", header)
    return folder, header


def run(native, folder, mode, seconds):
    # A live controller pipe is intentional: closed stdin requests an immediate stop.
    child = subprocess.Popen(
        [native, mode, str(folder), str(seconds), "0.5"],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    child.wait(timeout=15)
    child.stdin.close()
    return child.returncode, child.stderr.read().decode()


def pcm(folder):
    content = []
    for path in sorted((folder / "capture-pcm").glob("*.wav")):
        with wave.open(str(path)) as stream:
            assert stream.getsampwidth() == 3 and stream.getframerate() == 48000
            content.append(stream.readframes(stream.getnframes()))
    return b"".join(content)


def test_native_queue_and_chunk_boundaries_preserve_every_sample(native, tmp_path):
    folder, header = folder_at(tmp_path)
    code, log = run(native, folder, "--synthetic", 1.2)
    assert code == 0, log
    expected = b"".join(i.to_bytes(3, "little") for i in range(57600))
    assert pcm(folder) == expected
    assert len(list((folder / "capture-pcm").glob("*.wav"))) == 3
    record = audio.finish_capture(folder, header, "complete")
    assert sum(p.duration for p in record.parts) == 1.2
    decoded = b"".join(
        subprocess.check_output(
            ["ffmpeg", "-v", "error", "-i", str(folder / part.file), "-f", "s24le", "-"]
        )
        for part in record.parts
    )
    assert decoded == expected
    assert audit(folder)["status"] == "consistent"
    health = json.loads((folder / "capture-health.json").read_text())
    assert health["backend"] == "synthetic-native" and health["capturedFrames"] == 57600
    # Reopening the same folder must fail instead of overwriting captured data.
    assert run(native, folder, "--synthetic", 1)[0] != 0
    assert pcm(folder) == expected


@pytest.mark.parametrize(
    ("mode", "error"),
    [("--synthetic-gap", 2), ("--synthetic-overflow", 1), ("--synthetic-queue-full", 3)],
)
def test_native_capture_reports_loss_instead_of_synthesizing_samples(native, tmp_path, mode, error):
    folder, header = folder_at(tmp_path)
    code, log = run(native, folder, mode, 3)
    assert code != 0, log
    health = json.loads((folder / "capture-health.json").read_text())
    assert health["errorCode"] == error and not health["cleanStop"]
    audio.finish_capture(folder, header, "interrupted")
    assert audit(folder)["status"] == "warning"
    data = pcm(folder)
    assert data == b"".join(i.to_bytes(3, "little") for i in range(len(data) // 3))


def test_abrupt_native_exit_retains_valid_streamed_pcm(native, tmp_path):
    folder, header = folder_at(tmp_path)
    child = subprocess.Popen(
        [native, "--synthetic", str(folder), "0", "0.5"],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (folder / "capture-pcm/part-0001.wav").exists():
                break
            time.sleep(0.02)
        assert (folder / "capture-pcm/part-0001.wav").exists()
    finally:
        child.kill()
        child.wait(timeout=5)
        child.stdin.close()
    audio.write_new(folder / "capture-settings.json", {"backend": "portaudio-coreaudio"})
    result = audio.finish_capture(folder, header, "interrupted")
    assert sum(p.duration for p in result.parts) >= 0.5
    assert audit(folder)["status"] == "warning"
    assert (folder / "capture-pcm/part-0000.wav").exists()


def test_native_writer_fails_without_overwriting_existing_part(native, tmp_path):
    folder, _ = folder_at(tmp_path)
    path = folder / "capture-pcm/part-0000.wav"
    path.write_bytes(b"retained source")
    assert run(native, folder, "--synthetic", 1)[0] != 0
    assert path.read_bytes() == b"retained source"


def test_odd_length_pcm_has_a_riff_pad_byte_without_extra_sample(native, tmp_path):
    folder, header = folder_at(tmp_path)
    assert run(native, folder, "--synthetic", 48001 / 48000)[0] == 0
    data = pcm(folder)
    assert len(data) == 48001 * 3
    last = sorted((folder / "capture-pcm").glob("*.wav"))[-1].read_bytes()
    assert int.from_bytes(last[4:8], "little") + 8 == len(last)
    record = audio.finish_capture(folder, header, "complete")
    assert round(sum(p.duration * p.sampleRate for p in record.parts)) == 48001


def test_audit_separates_bounded_clock_skew_from_buffer_loss(tmp_path):
    health = {
        "backend": "portaudio-coreaudio",
        "sampleRate": 48000,
        "channels": 1,
        "acceptedFrames": 2880000,
        "capturedFrames": 2880000,
        "cleanStop": True,
        "errorCode": 0,
        "deviceElapsedSeconds": 59.9996,
        "maxTimestampGapSeconds": 0.00001,
    }
    (tmp_path / "recording.json").write_text(json.dumps({"parts": [{"duration": 60.0}]}))
    path = tmp_path / "capture-health.json"
    path.write_text(json.dumps(health))
    assert audit(tmp_path)["status"] == "consistent"
    for change in [
        {"errorCode": 1},
        {"acceptedFrames": 2880512},
        {"deviceElapsedSeconds": 61},
        {"maxTimestampGapSeconds": 0.01},
    ]:
        path.write_text(json.dumps({**health, **change}))
        assert audit(tmp_path)["status"] == "warning"
