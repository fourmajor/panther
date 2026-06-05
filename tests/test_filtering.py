from panther_journal.contracts import ClassifiedLine, LineType, PantherConfig
from panther_journal.pipeline.filtering import filter_game_lines


def test_filter_keeps_uncertain_and_story_labels() -> None:
    config = PantherConfig.model_validate(
        {
            "campaign": {"name": "c", "session_id": "s", "session_title": "t"},
            "audio": {},
            "models": {},
            "speakers": [],
            "filtering": {
                "include_labels": ["GAME_CANON", "RULES_CHAT", "CHARACTER_DIALOGUE", "UNCERTAIN"],
                "exclude_labels": ["FOOD_DRINK"],
                "keep_uncertain": True,
            },
        }
    )
    base = {
        "session_id": "s",
        "speaker_id": "gm",
        "speaker_name": "GM",
        "channel": 0,
        "timestamp_start": 0,
        "timestamp_end": 1,
        "asr_confidence": 1,
        "classifier_confidence": 1,
        "rationale": "test",
    }
    lines = [
        ClassifiedLine(id="a", text="story", label=LineType.GAME_CANON, **base),
        ClassifiedLine(id="b", text="pizza", label=LineType.FOOD_DRINK, **base),
        ClassifiedLine(id="c", text="maybe clue", label=LineType.UNCERTAIN, **base),
    ]

    assert [line.id for line in filter_game_lines(lines, config)] == ["a", "c"]
