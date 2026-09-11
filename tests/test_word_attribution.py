import json

import pytest

from panther_journal.recording import SpeakerTurn
from panther_journal.word_attribution import Progress, attribute, decision


def fixture():
    line = dict(start=0.0, end=4.0, text="Hello there. Your turn!", playerId=None)
    tokens = [
        dict(id=i, text=text, offsets={"from": a, "to": b})
        for i, (text, a, b) in enumerate(
            [
                (" Hello", 0, 1000),
                (" there.", 1000, 2000),
                (" Your", 2000, 3000),
                (" turn!", 3000, 4000),
            ]
        )
    ]
    raw = {
        "transcription": [
            dict(text=" " + line["text"], tokens=tokens, offsets={"from": 0, "to": 4000})
        ]
    }
    turns = [
        SpeakerTurn(start=0, end=2, speaker="SPEAKER_01"),
        SpeakerTurn(start=2, end=4, speaker="SPEAKER_02"),
    ]
    return line, raw, turns, {"SPEAKER_01": "alex", "SPEAKER_02": "river"}


def test_sequential_speakers_split_without_text_or_time_loss():
    line, raw, turns, mapping = fixture()
    output, report = attribute([line], raw, turns, mapping)
    assert [s["playerId"] for s in output] == ["alex", "river"]
    assert "".join(s["text"] for s in output) == line["text"]
    assert [(s["start"], s["end"]) for s in output] == [(0, 2), (2, 4)]
    assert report["assignedDurationPercent"] == 100
    assert report["coverageIsNotAccuracy"]
    assert line["playerId"] is None


def test_overlap_remains_unknown_and_duplicate_turns_do_not_inflate():
    line, raw, turns, mapping = fixture()
    turns.append(SpeakerTurn(start=0, end=2, speaker="SPEAKER_02"))
    output, _ = attribute([line], raw, turns * 2, mapping)
    assert output[0]["playerId"] is None
    assert output[-1]["playerId"] == "river"


def test_unmapped_label_and_strictness():
    _, _, turns, mapping = fixture()
    assert decision(0, 2, turns, {}, 0.65, 0.25)[1] is None
    short = [SpeakerTurn(start=0, end=1.4, speaker="SPEAKER_01")]
    assert decision(0, 2, short, mapping, 0.65, 0.25)[1] == "alex"
    assert decision(0, 2, short, mapping, 0.8, 0.25)[1] is None


def test_bad_timings_fall_back_without_guessing_word_positions():
    line, raw, turns, mapping = fixture()
    raw["transcription"][0]["tokens"][0]["offsets"]["to"] = -1
    output, report = attribute([line], raw, turns, mapping)
    assert output[0]["text"] == line["text"]
    assert output[0]["playerId"] is None
    assert report["timingFallbackSegments"] == 1


def test_wrong_source_rejected():
    line, raw, turns, mapping = fixture()
    raw["transcription"][0]["text"] = "Other text"
    with pytest.raises(ValueError, match="source text"):
        attribute([line], raw, turns, mapping)


def test_progress_measured_eta_and_terminal_state(tmp_path):
    path = tmp_path / "progress.json"
    progress = Progress(path, 10)
    assert json.loads(path.read_text())["estimatedCompletionAt"] is None
    progress.write(5)
    state = json.loads(path.read_text())
    assert state["processingPercent"] == 50
    assert state["estimatedRemainingSeconds"] >= 0
    progress.write(10, "completed")
    assert json.loads(path.read_text())["status"] == "completed"
