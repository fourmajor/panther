import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import click
import pytest

from panther_journal import session_worker as worker, speaker_profiles
from panther_journal.audio_storage import write_json


def test_queue_is_paginated_and_only_explicitly_complete(monkeypatch):
    api = Mock(side_effect=[{"jobs": [{"setStatus": "INCOMPLETE"}, {"setStatus": "COMPLETE", "jobId": "one"}], "cursor": "next"},
                            {"jobs": [{"setStatus": "COMPLETE", "jobId": "two"}], "cursor": None}])
    monkeypatch.setattr(worker.cloud, "api", api)
    assert [j["jobId"] for j in worker.completed_sets({})] == ["one", "two"]
    assert api.call_args_list[1].kwargs["params"] == {"cursor": "next"}


def test_private_config_requires_activation_boundary_and_no_users(tmp_path):
    path = tmp_path / "configuration.json"
    options = {name: str(tmp_path / name) for name in ["whisperModel", "speakerProfiles", "speakerModel", "speakerRuntime", "recordingsRoot"]}
    write_json(path, {"schemaVersion": 1, "games": {"synthetic-game": options}})
    with pytest.raises(click.ClickException):
        worker.settings(path)
    options["completedAfter"] = 10
    interpreter = tmp_path / "system-python"
    interpreter.write_text("synthetic executable")
    Path(options["speakerRuntime"]).symlink_to(interpreter)
    write_json(path, {"schemaVersion": 1, "games": {"synthetic-game": options}}, replace=True)
    assert worker.settings(path)["games"]["synthetic-game"]["completedAfter"] == 10
    options["speakerProfiles"] = "relative.json"
    write_json(path, {"schemaVersion": 1, "games": {"synthetic-game": options}}, replace=True)
    with pytest.raises(click.ClickException):
        worker.settings(path)


@pytest.mark.parametrize("version,extension", [(1, "flac"), (2, "wav")])
def test_download_pins_and_resume_header(tmp_path, monkeypatch, version, extension):
    identity = "recording-" + "a" * 32
    prefix = f"games/synthetic-game/assets/{identity}/original/"
    job = {"gameId": "synthetic-game", "chunkSetId": identity, "workflowVersion": version,
           "recording": {"key": prefix + "recording.json"}, "chunks": [{"key": prefix + f"part-0000.{extension}"}]}
    source = tmp_path / "captures"
    source.mkdir()
    root = tmp_path / "work"
    root.mkdir()
    record = SimpleNamespace(id=identity, gameId="synthetic-game", sessionId="synthetic-session", startedAt="2026-01-01", device="synthetic")
    monkeypatch.setattr(worker.cloud, "configuration", lambda: {})
    monkeypatch.setattr(worker, "verified", lambda _: record)
    download = Mock()
    monkeypatch.setattr(worker, "download", download)
    folder = worker.local_recording(job, {"recordingsRoot": str(source)}, root)
    assert worker.local_recording(job, {"recordingsRoot": str(source)}, root) == folder
    assert download.call_count == 4
    job["chunks"][0]["key"] = "games/other-game/assets/wrong/original/part-0000.flac"
    with pytest.raises(click.ClickException, match="input path"):
        worker.local_recording(job, {"recordingsRoot": str(source)}, root)


def test_transcript_reuses_raw_and_checkpoint_without_repeating_inference(tmp_path, monkeypatch):
    folder = tmp_path / ("recording-" + "a" * 32)
    folder.mkdir()
    model = tmp_path / "weights.bin"
    model.write_bytes(b"synthetic weights")
    profiles = tmp_path / "profiles.json"
    profiles.write_text("{}")
    part = SimpleNamespace(file="part-0000.flac", start=0, duration=30, model_dump=lambda: {"file": "part-0000.flac", "sha256": "pinned"})
    record = SimpleNamespace(id=folder.name, gameId="synthetic-game", sessionId="synthetic-session", parts=[part], entityType="Recording")
    monkeypatch.setattr(worker, "verified", lambda _: record)
    monkeypatch.setattr(worker, "audit", lambda _: {"warnings": ["capture warning"]})
    monkeypatch.setattr(worker.cloud, "configuration", lambda: {})
    monkeypatch.setattr(worker.cloud, "api", lambda *a, **k: {"players": [{"id": "example-player", "name": "Example Player"}]})
    monkeypatch.setattr(speaker_profiles, "load_profiles", lambda *a: {"profiles": [{"playerId": "example-player"}], "modelFiles": {"weights": "synthetic"}})
    monkeypatch.setattr(speaker_profiles, "model_pin", lambda *a: {"weights": "synthetic"})
    monkeypatch.setattr(speaker_profiles, "label_lines", lambda lines, *a: [{**s, "playerId": "example-player", "attribution": "provisional-enrolled-voice"} for s in lines])
    preview = folder / "live-preview/v1-test"
    preview.mkdir(parents=True)
    write_json(preview / "preview.json", {"settings": {"modelSha256": worker.audio.digest(model)}})
    write_json(preview / "part-0000.json", {})
    saved = {"segments": [{"start": 1, "end": 2, "text": "A synthetic utterance.", "playerId": None}], "recognizerSha256": "pin"}
    reuse = Mock(return_value=saved)
    monkeypatch.setattr(worker.live, "process_part", reuse)
    rerun = Mock(side_effect=AssertionError("Do not rerun saved recognition"))
    monkeypatch.setattr(worker.live, "transcribe_part", rerun)
    monkeypatch.setattr(worker.audio, "executable", lambda name: name)
    monkeypatch.setattr(worker.live, "run_process", lambda cmd, *_: Path(cmd[-1]).write_bytes(b"synthetic wav"))
    class Analyzer:
        calls = 0
        def __init__(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def analyze(self, wav, attempt):
            Analyzer.calls += 1
            write_json(attempt / "speaker-result.json", {"turns": [], "embeddings": {}})
            return {"turns": [], "embeddings": {}}
    monkeypatch.setattr(speaker_profiles, "SpeakerWorker", Analyzer)
    options = {"whisperModel": str(model), "speakerProfiles": str(profiles), "speakerModel": str(tmp_path), "speakerRuntime": str(tmp_path / "python")}
    job = {"jobId": "b" * 64, "chunkSetId": folder.name, "gameId": record.gameId}
    from unittest.mock import MagicMock
    report = MagicMock()
    _, paths = worker.transcript(folder, job, options, tmp_path / "recognition", report)
    worker.transcript(folder, job, options, tmp_path / "recognition", report)
    assert reuse.call_count == 1 and Analyzer.calls == 1 and rerun.call_count == 0
    raw, attributed = [json.loads((p / (p.name + ".json")).read_text()) for p in paths]
    assert raw["segments"][0]["playerId"] is None
    assert attributed["segments"][0]["playerId"] == "example-player"
    assert attributed["sourceTranscriptId"] == raw["id"]
    assert raw["captureIntegrity"]["warnings"] == ["capture warning"]
    checkpoint = tmp_path / "recognition/part-0000.json"
    checkpoint.write_text(checkpoint.read_text().replace("utterance", "tampered"))
    with pytest.raises(click.ClickException, match="checkpoint changed"):
        worker.transcript(folder, job, options, tmp_path / "recognition", report)


def test_successful_handoff_is_not_repeated_or_paid(tmp_path, monkeypatch):
    report = Mock()
    monkeypatch.setattr(worker, "Reporter", lambda *a, **k: report)
    job = {"jobId": "c" * 64, "gameId": "synthetic-game", "sessionId": "synthetic-session", "recording": {"key": "source"}}
    monkeypatch.setattr(worker, "local_recording", lambda *a: tmp_path)
    monkeypatch.setattr(worker, "transcript", lambda *a: (SimpleNamespace(), [tmp_path / "raw", tmp_path / "annotated"]))
    monkeypatch.setattr(worker.audio, "upload_one", lambda *a, **k: str(a[1]))
    monkeypatch.setattr(worker.cloud, "configuration", lambda: {})
    api = Mock(return_value={"jobId": "d" * 64})
    monkeypatch.setattr(worker.cloud, "api", api)
    worker.process(job, {}, tmp_path)
    worker.process(job, {}, tmp_path)
    assert api.call_count == 1
    assert api.call_args.args[2] == "/editorial-jobs"
    assert report.close.call_args.args == ("done",)


def test_reading_projection_preserves_speech_and_evidence_source():
    from panther_journal.editorial import reading_transcript
    raw = {"segments": [{"text": "Don't change 13.", "start": 2, "end": 5, "playerId": "example-player", "wordAttribution": {"detail": "large"}, "sourceKey": "exact-raw"}], "captureIntegrity": {"warnings": ["missing capture"]}}
    result = reading_transcript(raw)
    assert "wordAttribution" not in result["segments"][0]
    assert result["segments"][0] == {k: v for k, v in raw["segments"][0].items() if k != "wordAttribution"}
    assert result["captureIntegrity"] == raw["captureIntegrity"]
    assert "wordAttribution" in raw["segments"][0]
    from panther_journal.editorial import prompt_projection
    original = {**raw, "entityType": "PlayerTranscript"}
    projected = prompt_projection(original)
    rows = [dict(zip(projected["segmentFields"], row, strict=True)) for row in projected["segments"]]
    assert rows == result["segments"]
    assert original["segments"] == raw["segments"]


def test_partial_transcript_pair_resumes_without_overwrite(tmp_path):
    document = {"players": [], "segments": [{"start": 0, "end": 1, "playerId": None, "text": "Synthetic."}]}
    write_json(tmp_path / (tmp_path.name + ".json"), document)
    worker.save_transcript(tmp_path, document)
    assert (tmp_path / (tmp_path.name + ".md")).is_file()
    worker.save_transcript(tmp_path, document)
    with pytest.raises(click.ClickException, match="changed"):
        worker.save_transcript(tmp_path, {**document, "segments": []})


def test_short_confirmed_enrollment_is_explicit_and_never_accepts_multiple_speakers(tmp_path, monkeypatch):
    from click.testing import CliRunner
    sample = tmp_path / "confirmed.wav"
    sample.write_bytes(b"synthetic source")
    runtime = tmp_path / "python"
    runtime.write_text("synthetic runtime")
    model = tmp_path / "model"
    model.mkdir()
    manifest = tmp_path / "enrollment.json"
    write_json(manifest, {"gameId": "synthetic-game", "samples": [{"playerId": "example-player", "file": str(sample), "sha256": worker.audio.digest(sample), "confirmedSingleSpeaker": True, "identityEvidence": "Synthetic confirmed introduction"}]})
    monkeypatch.setattr(worker.cloud, "configuration", lambda: {})
    monkeypatch.setattr(worker.cloud, "api", lambda *a, **k: {"players": [{"id": "example-player"}]})
    monkeypatch.setattr(speaker_profiles, "model_pin", lambda *a: {"weights": "synthetic"})
    def analyze(wav, model, runtime, attempt):
        result = {"embeddings": {"speaker": [1.0] * 16}, "turns": [{"start": 0, "end": 5}]}
        write_json(attempt / "speaker-result.json", result)
        return result
    monkeypatch.setattr(speaker_profiles, "analyze", analyze)
    command = [str(manifest), "--output", str(tmp_path / "profiles.json"), "--runtime", str(runtime), "--model", str(model)]
    result = CliRunner().invoke(speaker_profiles.enroll, command)
    assert result.exit_code != 0 and "10 seconds" in result.output
    result = CliRunner().invoke(speaker_profiles.enroll, [*command, "--minimum-speech-seconds", "3"])
    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / "profiles.json").read_text())
    assert saved["profiles"][0]["sampleQuality"] == "short-confirmed-reference"
    assert saved["profiles"][0]["detectedSpeechSeconds"] == 5
    monkeypatch.setattr(speaker_profiles, "analyze", lambda *a: {"embeddings": {"one": [1.0] * 16, "two": [1.0] * 16}, "turns": [{"start": 0, "end": 20}]})
    command[2] = str(tmp_path / "invalid-profiles.json")
    result = CliRunner().invoke(speaker_profiles.enroll, [*command, "--minimum-speech-seconds", "3"])
    assert result.exit_code != 0 and "single-speaker" in result.output
