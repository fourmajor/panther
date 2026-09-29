import copy
import hashlib
import runpy
from pathlib import Path

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


@pytest.mark.parametrize(
    "change",
    [
        {"schemaVersion": True},
        {"schemaVersion": 1.0},
        {"number": 10001},
        {"number": True},
        {"seriesId": "Not Valid"},
        {"seriesId": "a" * 97},
        {"previousKey": "games/test-game/assets/b/original/b.png"},
        {"number": 2, "previousKey": []},
        {"number": 2, "previousKey": "games/foreign/assets/a/original/a.png"},
        {"number": 2, "previousKey": "not-an-asset"},
    ],
)
def test_planner_matches_server_version_shape_rejections(change):
    key = "games/test-game/assets/a/original/a.png"
    item = record(key)
    version = {"schemaVersion": 1, "seriesId": "known-family", "number": 1, **change}
    item["metadata"]["extra"]["version"] = version
    validator = runpy.run_path(
        str(Path(__file__).parents[1] / "infra/lambda/media-api/asset_metadata.py")
    )["validate_version"]
    with pytest.raises(ValueError):
        validator(version, key)
    with pytest.raises(ClickException, match="Invalid explicit asset version"):
        version_plan([item], {})


def test_first_version_explicit_null_predecessor_is_preserved_like_server():
    key = "games/test-game/assets/a/original/a.png"
    item = record(key)
    version = {"schemaVersion": 1, "seriesId": "known-family", "number": 1, "previousKey": None}
    item["metadata"]["extra"]["version"] = version
    validator = runpy.run_path(
        str(Path(__file__).parents[1] / "infra/lambda/media-api/asset_metadata.py")
    )["validate_version"]
    assert validator(version, key) == version
    assert version_plan([item], {})["migrations"] == []
    assert item["metadata"]["extra"]["version"] == version


def test_malformed_extra_is_an_explicit_blocker_not_an_unhandled_crash():
    key = "games/test-game/assets/a/original/a.png"
    item = record(key)
    item["metadata"]["extra"] = []
    with pytest.raises(ClickException, match="Invalid explicit asset metadata"):
        version_plan([item], {})
