import hashlib
import io
import json
import shutil
import wave

import click
import pytest
from pydantic import ValidationError

from panther_journal.browser_recording import BrowserRecording, verified
from panther_journal import recording_playback


def wav(seconds=0.1):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(32000)
        audio.writeframes(b"\0\0" * round(seconds * 32000))
    return output.getvalue()


def manifest():
    raw = wav()
    return {
        "schemaVersion": 1,
        "entityType": "BrowserRecording",
        "id": "recording-" + "a" * 32,
        "gameId": "test-game",
        "sessionId": "test-session",
        "sessionName": "Synthetic session",
        "startedAt": "2026-01-01T00:00:00Z",
        "device": "Synthetic microphone",
        "status": "complete",
        "sourceFormat": "wav",
        "captureWarnings": ["Hardware continuity is unverified."],
        "parts": [
            {
                "file": "part-0000.wav",
                "start": 0.0,
                "duration": 0.1,
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "sampleRate": 32000,
                "channels": 1,
                "bitsPerSample": 16,
            }
        ],
    }


def test_browser_contract_is_distinct_and_checks_immutable_originals(tmp_path):
    doc = manifest()
    (tmp_path / "recording.json").write_text(json.dumps(doc))
    (tmp_path / "part-0000.wav").write_bytes(wav())
    assert verified(tmp_path).sourceFormat == "wav"
    with pytest.raises(ValidationError):
        BrowserRecording.model_validate({**doc, "sourceFormat": "flac"})
    changed = json.loads(json.dumps(doc))
    changed["parts"][0]["start"] = 0.5
    with pytest.raises(ValidationError, match="contiguous"):
        BrowserRecording.model_validate(changed)
    (tmp_path / "part-0000.wav").write_bytes(b"changed")
    with pytest.raises(click.ClickException, match="changed"):
        verified(tmp_path)


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe")),
    reason="Laptop playback tools are not installed",
)
def test_laptop_playback_accepts_browser_pcm_without_changing_original(tmp_path):
    doc = manifest()
    (tmp_path / "recording.json").write_text(json.dumps(doc))
    (tmp_path / "part-0000.wav").write_bytes(wav())
    target, _, output = recording_playback.build(tmp_path)
    assert output["inputSamples"] == 3200
    assert output["durationSeconds"] == pytest.approx(0.1)
    assert target.exists()
    assert (
        hashlib.sha256((tmp_path / "part-0000.wav").read_bytes()).hexdigest()
        == doc["parts"][0]["sha256"]
    )
