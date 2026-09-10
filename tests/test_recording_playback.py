import hashlib
import json
import shutil
import subprocess

import click
import pytest

from panther_journal import recording as audio, recording_playback as playback
from panther_journal.audio_storage import lock
from test_recording_resilience import source  # noqa: F401


def completed(sample):
    folder, header = sample
    shutil.copyfile(folder / "part-0000.flac", folder / "part-0001.flac")
    record = audio.finish_capture(folder, header, "complete")
    return folder, record


def test_continuous_copy_uses_every_sample_once_and_preserves_sources(source, monkeypatch):  # noqa: F811
    folder, record = completed(source)
    original_hashes = [audio.digest(folder / p.file) for p in record.parts]
    target, manifest, doc = playback.build(folder)
    pcm = b"".join(subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(folder / p.file), "-f", "s32le", "-c:a", "pcm_s32le", "-",
    ], check=True, capture_output=True).stdout for p in record.parts)
    assert doc["inputSamples"] == len(pcm) // 4 == 57600
    assert doc["inputPcmSha256"] == hashlib.sha256(pcm).hexdigest()
    assert doc["durationSeconds"] == pytest.approx(1.2)
    assert [m["start"] for m in doc["partMarkers"]] == [0, 0.6]
    assert doc["lossless"] is False and doc["codec"] == "mp3"
    assert len(doc["sourceKeys"]) == 3
    assert "capture" in doc["captureWarning"]
    assert [audio.digest(folder / p.file) for p in record.parts] == original_hashes
    assert audio.verified(folder) == record
    # Full derivative decodes, has one timeline, and has an MP3 seek/duration header.
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(target), "-f", "null", "-"], check=True)
    body = target.read_bytes()
    assert b"Info" in body[:2048] or b"Xing" in body[:2048]
    monkeypatch.setattr(playback.subprocess, "Popen", lambda *a, **k: pytest.fail("must reuse verified existing copy"))
    assert playback.build(folder) == (target, manifest, doc)


def test_changed_and_incomplete_sources_fail_without_overwriting(source):  # noqa: F811
    folder, record = completed(source)
    with lock(folder, "capture.lock"), pytest.raises(click.ClickException, match="Finish"):
        playback.build(folder)
    target, manifest, doc = playback.build(folder)
    (folder / record.parts[0].file).write_bytes(b"corrupt source")
    with pytest.raises(click.ClickException, match="changed"):
        playback.build(folder)
    assert audio.digest(target) == doc["audioSha256"] and manifest.exists()


def test_sample_count_and_format_mismatches_do_not_publish(source):  # noqa: F811
    folder, record = completed(source)
    changed = record.model_dump()
    changed["parts"][0]["duration"] += 0.1
    changed["parts"][1]["start"] += 0.1
    (folder / "recording.json").write_text(json.dumps(changed))
    with pytest.raises(click.ClickException, match="sample count"):
        playback.build(folder)
    assert not list(folder.glob("playback-*.mp3"))
    assert not list(folder.glob(".playback-*.mp3"))
    changed = record.model_dump()
    changed["parts"][1]["sampleRate"] = 44100
    (folder / "recording.json").write_text(json.dumps(changed))
    with pytest.raises(click.ClickException, match="formats differ"):
        playback.build(folder)


def test_corrupt_derivative_and_orphan_are_retained_not_replaced(source):  # noqa: F811
    folder, _ = completed(source)
    target, manifest, _ = playback.build(folder)
    target.write_bytes(b"bad output")
    with pytest.raises(click.ClickException, match="Saved playback changed"):
        playback.build(folder)
    manifest.rename(manifest.with_suffix(".retained"))
    with pytest.raises(click.ClickException, match="without its manifest"):
        playback.build(folder)
    assert target.read_bytes() == b"bad output"


def test_publication_preserves_explicit_provenance(source, monkeypatch):  # noqa: F811
    folder, record = completed(source)
    sent = []
    def upload(config, file, record, kind, *, source_keys=None):
        key = f"games/{record.gameId}/assets/{record.id}/original/{file.name}"
        sent.append((kind, source_keys, key))
        return key
    monkeypatch.setattr(audio, "upload_one", upload)
    result = playback.publish(folder, {}, record)
    assert [s[0] for s in sent] == ["recording-playback-manifest", "recording-playback"]
    assert sent[1][1] == [result["manifestKey"]]
    assert sent[1][2] == result["audioKey"]
