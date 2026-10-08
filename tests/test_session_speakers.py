import copy

import click
import pytest

from panther_journal.session_speakers import reconcile


def fixture():
    vector = [1.0] + [0.0] * 15
    document = dict(
        recordingId="synthetic-recording",
        gameId="synthetic-game",
        sourceParts=[{"duration": 30}],
        players=[{"id": "example-player"}],
        segments=[dict(start=0.0, end=10.0, text="Keep every word.", playerId=None)],
    )
    profiles = dict(
        gameId="synthetic-game",
        modelFiles={"pin": "synthetic"},
        profiles=[dict(playerId="example-player", embedding=vector)],
    )
    evidence = dict(
        recordingId=document["recordingId"],
        sourceParts=document["sourceParts"],
        modelFiles=profiles["modelFiles"],
        embeddings={"SPEAKER_00": vector},
        turns=[dict(start=0.0, end=7.0, speaker="SPEAKER_00")],
    )
    return document, evidence, profiles


def test_session_matching_retains_text_and_source():
    document, evidence, profiles = fixture()
    original = copy.deepcopy(document)
    result = reconcile(document, evidence, profiles)
    assert result["segments"][0]["playerId"] == "example-player"
    assert result["segments"][0]["text"] == document["segments"][0]["text"]
    assert result["segments"][0]["sessionAttributionEvidence"]["exclusiveCoverage"] == 0.7
    assert document == original
    assert result["speakerAttributionSummary"]["assignedSegments"] == 1
    assert result["segments"][0]["previousAttribution"]["playerId"] is None


@pytest.mark.parametrize("fault", ["recording", "parts", "model", "game", "roster", "missing"])
def test_foreign_or_missing_evidence_fails_closed(fault):
    document, evidence, profiles = fixture()
    if fault == "recording":
        evidence["recordingId"] = "foreign"
    if fault == "parts":
        evidence["sourceParts"] = []
    if fault == "model":
        evidence["modelFiles"] = {}
    if fault == "game":
        profiles["gameId"] = "foreign"
    if fault == "roster":
        document["players"] = []
    if fault == "missing":
        del evidence["embeddings"]
    with pytest.raises(click.ClickException):
        reconcile(document, evidence, profiles)


@pytest.mark.parametrize("reason", ["empty", "weak", "overlap", "uncertain-timing"])
def test_uncertain_speech_never_forces_identity(reason):
    document, evidence, profiles = fixture()
    if reason == "empty":
        evidence["embeddings"]["SPEAKER_00"] = [0.0] * 16
    if reason == "weak":
        evidence["embeddings"]["SPEAKER_00"] = [0.0, 1.0] + [0.0] * 14
    if reason == "overlap":
        evidence["turns"].append(dict(start=0.0, end=7.0, speaker="SPEAKER_01"))
        evidence["embeddings"]["SPEAKER_01"] = evidence["embeddings"]["SPEAKER_00"]
    if reason == "uncertain-timing":
        document["segments"][0]["timingMethod"] = "verified-chunk-boundaries"
    result = reconcile(document, evidence, profiles)
    assert result["segments"][0]["playerId"] is None
    assert result["segments"][0]["text"] == "Keep every word."


def test_competing_identity_profiles_remain_unknown():
    document, evidence, profiles = fixture()
    document["players"].append({"id": "other-example-player"})
    profiles["profiles"].append(
        {"playerId": "other-example-player", "embedding": profiles["profiles"][0]["embedding"]}
    )
    assert reconcile(document, evidence, profiles)["segments"][0]["playerId"] is None


def test_out_of_recording_turn_is_rejected():
    document, evidence, profiles = fixture()
    evidence["turns"][0]["end"] = 32.0
    with pytest.raises(click.ClickException, match="exceed audio"):
        reconcile(document, evidence, profiles)
