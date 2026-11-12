import copy

import click
import pytest

from panther_journal.session_speakers import (
    assert_assignment_rate,
    reconcile,
    require_reusable_diarization,
)
from panther_journal.speaker_reference import EXCLUSIVE_TURN_SOURCE, REFERENCE_EMBEDDING_METHOD


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


def test_one_unavailable_embedding_keeps_the_matched_speaker():
    document, evidence, profiles = fixture()
    document["segments"].append(dict(start=12.0, end=20.0, text="Second voice.", playerId=None))
    evidence["turns"].append(dict(start=12.0, end=20.0, speaker="SPEAKER_01"))
    evidence["embeddings"]["SPEAKER_01"] = None
    evidence["unavailableEmbeddings"] = {
        "SPEAKER_01": {"reason": "non-finite-runtime-output", "values": ["nan"] * 16}
    }
    result = reconcile(document, evidence, profiles)
    assert result["segments"][0]["playerId"] == "example-player"
    assert result["segments"][1]["playerId"] is None
    assert result["segments"][1]["speakerLabel"] == "SPEAKER_01"
    assert result["segments"][1]["text"] == "Second voice."


def test_diarized_label_stays_visible_when_the_player_is_unknown():
    from panther_journal.recording import speaker_caption

    players = [{"id": "example-player", "name": "Example"}]
    assert speaker_caption({"playerId": "example-player"}, players) == "Example"
    assert speaker_caption({"playerId": None, "speakerLabel": "SPEAKER_01"}, players) == "SPEAKER_01"
    assert speaker_caption({"playerId": None, "speakerLabel": None}, players) == "Unassigned"


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


def test_overlapping_turns_leave_the_line_unassigned_and_the_floor_stops_handoff():
    document, evidence, profiles = fixture()
    document["segments"] = [
        dict(start=float(index), end=float(index) + 1, text="Keep every word.", playerId=None)
        for index in range(4)
    ]
    document["sourceParts"] = [{"duration": 4}]
    evidence["sourceParts"] = document["sourceParts"]
    evidence["turns"] = [
        dict(start=0.0, end=4.0, speaker="SPEAKER_00"),
        dict(start=0.0, end=4.0, speaker="SPEAKER_01"),
    ]
    evidence["embeddings"]["SPEAKER_01"] = [0.0, 1.0] + [0.0] * 14
    result = reconcile(document, evidence, profiles)
    assert all(line["playerId"] is None and line["speakerLabel"] is None for line in result["segments"])
    assert result["speakerAttributionSummary"]["assignedSegments"] == 0
    with pytest.raises(click.ClickException, match="Below the 25% floor"):
        assert_assignment_rate(result)


def test_exclusive_turns_and_a_reference_vector_assign_the_player():
    document, evidence, profiles = fixture()
    document["segments"] = [
        dict(start=float(index), end=float(index) + 1, text="Keep every word.", playerId=None)
        for index in range(4)
    ]
    document["sourceParts"] = [{"duration": 4}]
    evidence["sourceParts"] = document["sourceParts"]
    evidence["turns"] = [dict(start=0.0, end=4.0, speaker="SPEAKER_00")]
    evidence["turnSource"] = EXCLUSIVE_TURN_SOURCE
    evidence["embeddingMethod"] = REFERENCE_EMBEDDING_METHOD
    result = reconcile(document, evidence, profiles)
    assert all(line["playerId"] == "example-player" for line in result["segments"])
    assert result["speakerAttributionSummary"]["turnSource"] == EXCLUSIVE_TURN_SOURCE
    assert result["speakerAttributionSummary"]["speakerMatches"][0]["bestCosine"] == pytest.approx(1)
    assert_assignment_rate(result)


def test_weak_reference_match_is_reported_and_blocks_handoff():
    document, evidence, profiles = fixture()
    evidence["embeddings"]["SPEAKER_00"] = [0.0, 1.0] + [0.0] * 14
    result = reconcile(document, evidence, profiles)
    assert result["segments"][0]["speakerLabel"] == "SPEAKER_00"
    assert result["segments"][0]["playerId"] is None
    match = result["speakerAttributionSummary"]["speakerMatches"][0]
    assert match["playerId"] is None and match["bestCosine"] == 0
    with pytest.raises(click.ClickException, match="cosine 0.000"):
        assert_assignment_rate(result)


def test_saved_centroid_diarization_is_not_reused():
    with pytest.raises(click.ClickException, match="exclusive reference embeddings"):
        require_reusable_diarization({"embeddingMethod": "cluster-centroid", "turnSource": "speaker-diarization"})
    saved = require_reusable_diarization(
        {"embeddingMethod": REFERENCE_EMBEDDING_METHOD, "turnSource": EXCLUSIVE_TURN_SOURCE}
    )
    assert saved["turnSource"] == EXCLUSIVE_TURN_SOURCE


def test_four_speakers_clear_the_assignment_floor():
    speakers = [f"SPEAKER_0{index}" for index in range(4)]
    players = [f"player-{index}" for index in range(4)]

    def basis(index):
        vector = [0.0] * 16
        vector[index] = 1.0
        return vector

    segments, turns = [], []
    cursor = 0.0
    for index, speaker in enumerate(speakers):
        for _copy in range(2):
            segments.append(dict(start=cursor, end=cursor + 10, text=f"Line from {speaker}.", playerId=None))
            turns.append(dict(start=cursor, end=cursor + 8, speaker=speaker))
            cursor += 10
    segments.append(dict(start=cursor, end=cursor + 10, text="Everyone talked at once.", playerId=None))
    document = dict(
        recordingId="synthetic-recording",
        gameId="synthetic-game",
        sourceParts=[{"duration": cursor + 10}],
        players=[{"id": player} for player in players],
        segments=segments,
    )
    profiles = dict(
        gameId="synthetic-game",
        modelFiles={"pin": "synthetic"},
        profiles=[dict(playerId=player, embedding=basis(index)) for index, player in enumerate(players)],
    )
    evidence = dict(
        recordingId=document["recordingId"],
        sourceParts=document["sourceParts"],
        modelFiles=profiles["modelFiles"],
        embeddings={speaker: basis(index) for index, speaker in enumerate(speakers)},
        turns=turns,
        turnSource=EXCLUSIVE_TURN_SOURCE,
        embeddingMethod=REFERENCE_EMBEDDING_METHOD,
    )
    result = reconcile(document, evidence, profiles)
    summary = result["speakerAttributionSummary"]
    assert summary["assignedSegments"] >= 8
    assert summary["segments"] == 9
    assert 100 * summary["assignedSegments"] / summary["segments"] >= 25
    assert result["segments"][-1]["playerId"] is None
    assert_assignment_rate(result)


def test_out_of_recording_turn_is_rejected():
    document, evidence, profiles = fixture()
    evidence["turns"][0]["end"] = 32.0
    with pytest.raises(click.ClickException, match="exceed audio"):
        reconcile(document, evidence, profiles)
