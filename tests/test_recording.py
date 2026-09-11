import json
from pathlib import Path
from unittest.mock import Mock, create_autospec

import click
import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from panther_journal import recording as audio
from panther_journal.cli import main


def recording_fixture(tmp_path):
    folder = tmp_path / ("recording-" + "a" * 32)
    folder.mkdir()
    file = folder / "part-0000.flac"
    file.write_bytes(b"synthetic audio bytes")
    record = audio.Recording(
        id=folder.name,
        gameId="test-game",
        sessionId="test-session",
        startedAt="2026-01-01T00:00:00Z",
        device="test device",
        status="complete",
        parts=[
            audio.Part(
                file=file.name,
                start=0.0,
                duration=12.0,
                size=file.stat().st_size,
                sha256=audio.digest(file),
                sampleRate=48000,
                channels=1,
                bitsPerSample=24,
            )
        ],
    )
    audio.write_new(folder / "recording.json", record.model_dump())
    return folder, record


def test_recording_integrity_and_no_overwrite(tmp_path):
    folder, record = recording_fixture(tmp_path)
    assert audio.verified(folder) == record
    with pytest.raises(FileExistsError):
        audio.write_new(folder / "recording.json", {})
    (folder / "part-0000.flac").write_bytes(b"modified")
    with pytest.raises(click.ClickException, match="changed"):
        audio.verified(folder)


def test_capture_targets_exact_device_and_lossless_chunks(tmp_path, monkeypatch):
    from panther_journal import native_capture

    monkeypatch.setattr(native_capture, "binary", lambda: "/synthetic/capture")
    command = audio.capture_command("Test USB Microphone", tmp_path, 180)
    assert command == ["/synthetic/capture", "Test USB Microphone", str(tmp_path), "180", "30"]
    assert "avfoundation" not in command


def test_audio_stays_outside_repositories(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(click.ClickException, match="outside Git"):
        audio.private_folder(tmp_path / "private", "test-game", "test-session")


def test_manifest_rejects_traversal_and_discontinuous_parts(tmp_path):
    _, record = recording_fixture(tmp_path)
    body = record.model_dump()
    body["parts"][0]["file"] = "../private.flac"
    with pytest.raises(ValidationError):
        audio.Recording.model_validate(body)
    body = record.model_dump()
    body["parts"][0]["start"] = 5.0
    with pytest.raises(ValidationError):
        audio.Recording.model_validate(body)


def test_transcript_uses_person_and_keeps_table_chatter(tmp_path):
    _, record = recording_fixture(tmp_path)
    lines = audio.transcript_lines(
        {
            "transcription": [
                {"offsets": {"from": 1000, "to": 4000}, "text": " Hey, did anybody bring pizza? "}
            ]
        },
        record.parts[0],
        "test-person",
    )
    assert lines[0]["playerId"] == "test-person"
    assert lines[0]["speechContext"] == "unclassified"
    assert "pizza" in lines[0]["text"]
    assert lines[0]["start"] == 1.0
    assert (
        audio.transcript_lines(
            {"transcription": [{"offsets": {"from": 0, "to": 1000}, "text": "Hello"}]},
            record.parts[0],
            None,
        )[0]["playerId"]
        is None
    )
    with pytest.raises(click.ClickException, match="timestamps"):
        audio.transcript_lines(
            {"transcription": [{"offsets": {"from": 12500, "to": 13000}, "text": "bad"}]},
            record.parts[0],
            None,
        )


def test_upload_uses_existing_panther_contract_and_refuses_conflicts(tmp_path, monkeypatch):
    folder, record = recording_fixture(tmp_path)
    callback = create_autospec(audio.cloud.upload.callback)
    monkeypatch.setattr(audio.cloud.upload, "callback", callback)
    monkeypatch.setattr(
        audio.cloud, "api", Mock(side_effect=click.ClickException("Object not found"))
    )
    key = audio.upload_one({}, folder / "part-0000.flac", record, "recording")
    assert key.startswith(f"games/test-game/assets/{record.id}/original/")
    assert callback.call_args.kwargs["as_json"] is True
    monkeypatch.setattr(audio.cloud, "api", Mock(return_value={"size": 999}))
    with pytest.raises(click.ClickException, match="overwrite"):
        audio.upload_one({}, folder / "part-0000.flac", record, "recording")


def test_rerunning_transcription_keeps_versions_and_rejects_character_identity(
    tmp_path, monkeypatch
):
    folder, record = recording_fixture(tmp_path)
    model = tmp_path / "model.bin"
    model.write_bytes(b"synthetic model")
    roster = tmp_path / "roster.json"
    roster.write_text(
        json.dumps(
            {"game": {"id": "test-game"}, "players": [{"id": "test-person", "name": "Person"}]}
        )
    )
    monkeypatch.setattr(audio, "executable", lambda name: name)

    def run(command, **kwargs):
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"synthetic joined WAV")
            return
        base = Path(command[command.index("-of") + 1])
        base.with_suffix(".json").write_text(
            json.dumps({"transcription": [{"offsets": {"from": 0, "to": 2000}, "text": "Hello"}]})
        )

    monkeypatch.setattr(audio.subprocess, "run", run)
    args = [
        "recording",
        "transcribe",
        str(folder),
        "--model",
        str(model),
        "--roster",
        str(roster),
        "--local-only",
        "--sole-player",
        "test-person",
    ]
    for _ in range(2):
        result = CliRunner().invoke(main, args)
        assert result.exit_code == 0, result.output
    assert len(list(folder.glob("transcript-*"))) == 2
    args[-1] = "fictional-character"
    result = CliRunner().invoke(main, args)
    assert result.exit_code != 0
    assert "must be in" in result.output
    assert audio.verified(folder) == record


def test_raw_commit_happens_only_after_all_uploads_and_keeps_local_on_failure(
    tmp_path, monkeypatch
):
    folder, record = recording_fixture(tmp_path)
    version = folder / "transcript-test"
    version.mkdir()
    raw = {"recordingId": record.id, "sourceParts": [p.model_dump() for p in record.parts]}
    (version / "transcript-test.json").write_text(json.dumps(raw))
    (version / "transcript-test.md").write_text("Synthetic transcript")
    events = []
    monkeypatch.setattr(audio.cloud, "configuration", lambda: {})

    def upload(config, file, record, kind):
        events.append(file.name)
        return file.name

    def api(config, method, route, **kwargs):
        if route == "/recording-sets/complete":
            assert events == ["part-0000.flac", "recording.json"]
            assert kwargs["json"]["status"] == "COMPLETE"
            return {"status": "SUBMITTED"}
        if method == "POST":
            assert events == [
                "part-0000.flac",
                "recording.json",
                "transcript-test.json",
                "transcript-test.md",
            ]
            assert kwargs["json"]["rawKey"] == "transcript-test.json"
            raise click.ClickException("Simulated network outage")
        return {}

    monkeypatch.setattr(audio, "upload_one", upload)
    monkeypatch.setattr(audio.cloud, "api", api)
    with pytest.raises(click.ClickException, match="outage"):
        audio.upload_recording.callback(folder=folder, transcript=version, editorial=True)
    assert json.loads((version / "transcript-test.json").read_text()) == raw


def test_attribution_preserves_text_and_rejects_mixed_or_insufficient_speech():
    lines = [{"start": 0.0, "end": 2.0, "text": "Pizza?", "playerId": None}]
    turn = audio.SpeakerTurn(start=0.0, end=2.0, speaker="SPEAKER_00")
    mapping = {"SPEAKER_00": "test-person"}
    result = audio.attributed_lines(lines, [turn], mapping)
    assert result[0]["playerId"] == "test-person"
    assert result[0]["text"] == "Pizza?"
    assert lines[0]["playerId"] is None
    overlap = audio.SpeakerTurn(start=1.0, end=2.0, speaker="SPEAKER_01")
    assert audio.attributed_lines(lines, [turn, overlap], mapping)[0]["playerId"] is None
    short = audio.SpeakerTurn(start=0.0, end=0.5, speaker="SPEAKER_00")
    assert audio.attributed_lines(lines, [short, short], mapping)[0]["playerId"] is None
    assert audio.attributed_lines(lines, [turn], {})[0]["playerId"] is None
    with pytest.raises(ValidationError):
        audio.SpeakerTurn(start=2.0, end=1.0, speaker="SPEAKER_00")


@pytest.mark.parametrize('word_level', [False, True])
def test_attribution_creates_version_and_requires_matching_source_and_players(tmp_path, word_level):
    folder, record = recording_fixture(tmp_path)
    original = folder / ("transcript-" + "b" * 32)
    original.mkdir()
    document = {
        "id": original.name,
        "recordingId": record.id,
        "sourceParts": [p.model_dump() for p in record.parts],
        "players": [{"id": "test-person", "name": "Person"}],
        "segments": [{"start": 0.0, "end": 2.0, "text": "Hello", "playerId": None}],
    }
    audio.save_transcript(original, document)
    speaker_file = folder / "diarization.json"
    body = {
        "recordingId": record.id,
        "sourceParts": document["sourceParts"],
        "turns": [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"}],
    }
    audio.write_new(speaker_file, body)
    mapping = folder / "mapping.json"
    audio.write_new(mapping, {"SPEAKER_00": "test-person"})
    args = [
        "recording",
        "attribute",
        str(original),
        "--diarization",
        str(speaker_file),
        "--mapping",
        str(mapping),
    ]
    if word_level:
        (original / 'asr-output').mkdir()
        audio.write_new(original / 'asr-output/transcription.json', {
            'transcription': [{'text': ' Hello', 'offsets': {'from': 0, 'to': 2000},
                               'tokens': [{'id': 1, 'text': ' Hello',
                                           'offsets': {'from': 0, 'to': 2000}}]}]})
        args.append('--word-level')
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    versions = [p for p in folder.glob("transcript-*") if p != original]
    assert len(versions) == 1
    new = json.loads((versions[0] / f"{versions[0].name}.json").read_text())
    assert new["segments"][0]["playerId"] == "test-person"
    assert new["sourceTranscriptId"] == original.name
    if word_level:
        progress = json.loads((versions[0] / 'progress.json').read_text())
        assert progress['status'] == 'completed'
        assert progress['processingPercent'] == 100
        assert new['speakerAttributionPolicy']['timingEvidenceSha256'] == audio.digest(
            original / 'asr-output/transcription.json')
    assert json.loads((original / f"{original.name}.json").read_text()) == document
    mapping.write_text(json.dumps({"SPEAKER_00": "fictional-character"}))
    assert CliRunner().invoke(main, args).exit_code != 0
    body["recordingId"] = "different-recording"
    speaker_file.write_text(json.dumps(body))
    assert "exact recording" in CliRunner().invoke(main, args).output


def test_diarization_runs_offline_without_inherited_credentials(tmp_path, monkeypatch):
    folder, _ = recording_fixture(tmp_path)
    model = tmp_path / "local-model"
    model.mkdir()
    runtime = tmp_path / "python"
    underlying_python = tmp_path / "base-python"
    underlying_python.touch()
    runtime.symlink_to(underlying_python)
    monkeypatch.setenv("HF_TOKEN", "synthetic-do-not-forward")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-do-not-forward")
    calls = []
    monkeypatch.setattr(
        audio.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs))
    )
    result = CliRunner().invoke(
        main,
        [
            "recording",
            "diarize",
            str(folder),
            "--runtime",
            str(runtime),
            "--model",
            str(model),
            "--speakers",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output
    env = calls[0][1]["env"]
    assert env["HF_HUB_OFFLINE"] == "1" and env["PYANNOTE_METRICS_ENABLED"] == "0"
    assert "HF_TOKEN" not in env and "AWS_SECRET_ACCESS_KEY" not in env
    assert calls[0][0][-2:] == ["--speakers", "2"]
    assert calls[0][0][0] == str(runtime), "Resolving the executable symlink bypasses its venv"
