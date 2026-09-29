import copy
import hashlib

import pytest
from click import ClickException

from panther_journal.asset_migrations import version_plan


def record(key, kind="portrait"):
    return {
        "key": key,
        "versionId": "pinned",
        "kind": kind,
        "metadata": {
            "schemaVersion": 1,
            "title": "Fictional asset",
            "category": "reference",
            "characterIds": [],
            "tags": [],
            "sourceKeys": [],
            "extra": {
                "relationshipRole": "finished",
                "generation": {
                    "schemaVersion": 1,
                    "method": "unknown",
                    "cost": {"status": "unknown"},
                },
            },
        },
    }


def test_version_plan_does_not_infer_revision_families_from_appearance_membership():
    a = "games/test-game/assets/portrait-one/original/a.png"
    b = "games/test-game/assets/portrait-two/original/b.png"
    c = "games/test-game/assets/unrelated/original/c.png"
    before = [record(a), record(b), record(c)]
    untouched = copy.deepcopy(before)
    plan = version_plan(before, {("test-game", "fictional-character", "portrait"): [a, b]})
    assert before == untouched
    records = {item["key"]: item["metadata"]["extra"]["version"] for item in plan["migrations"]}
    assert records[a]["number"] == 1
    assert records[b]["number"] == 1 and "previousKey" not in records[b]
    assert records[a]["seriesId"] != records[b]["seriesId"]
    assert records[c] == {
        "schemaVersion": 1,
        "seriesId": hashlib.sha256(c.encode()).hexdigest()[:24],
        "number": 1,
    }
    again = version_plan(
        [
            {**entry, "metadata": item["metadata"]}
            for entry, item in zip(before, plan["migrations"])
        ],
        {("test-game", "fictional-character", "portrait"): [a, b]},
    )
    assert again["migrations"] == []


def test_version_plan_blocks_missing_history_and_unresolvable_explicit_versions():
    key = "games/test-game/assets/a/original/a.png"
    with pytest.raises(ClickException, match="missing"):
        version_plan(
            [record(key)],
            {("test-game", "character", "portrait"): ["games/test-game/assets/no/original/b.png"]},
        )
    explicit = record(key)
    explicit["metadata"]["extra"]["version"] = {
        "schemaVersion": 1,
        "seriesId": "known-family",
        "number": 2,
        "previousKey": "games/test-game/assets/no/original/b.png",
    }
    with pytest.raises(ClickException, match="predecessor"):
        version_plan([explicit], {})


def test_known_version_families_survive_new_physical_states_and_reordered_selections():
    a = "games/test-game/assets/a/original/a.png"
    b = "games/test-game/assets/b/original/b.png"
    first, second = record(a), record(b)
    first["metadata"]["extra"]["version"] = {
        "schemaVersion": 1,
        "seriesId": "known-family",
        "number": 1,
    }
    second["metadata"]["extra"]["version"] = {
        "schemaVersion": 1,
        "seriesId": "known-family",
        "number": 2,
        "previousKey": a,
    }
    assert (
        version_plan([first, second], {("test-game", "character", "portrait"): [b, a]})[
            "migrations"
        ]
        == []
    )
