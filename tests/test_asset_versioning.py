import copy
import hashlib

import pytest
from click import ClickException

from panther_journal.asset_migrations import version_plan


def record(key, kind="portrait"):
    return {"key": key, "versionId": "pinned", "kind": kind,
            "metadata": {"schemaVersion": 1, "title": "Fictional asset", "category": "reference",
                         "characterIds": [], "tags": [], "sourceKeys": [],
                         "extra": {"relationshipRole": "finished", "generation": {
                             "schemaVersion": 1, "method": "unknown", "cost": {"status": "unknown"}}}}}


def test_version_plan_groups_only_profile_backed_appearances_and_singletons():
    a = "games/test-game/assets/portrait-one/original/a.png"
    b = "games/test-game/assets/portrait-two/original/b.png"
    c = "games/test-game/assets/unrelated/original/c.png"
    before = [record(a), record(b), record(c)]
    untouched = copy.deepcopy(before)
    plan = version_plan(before, {("test-game", "fictional-character", "portrait"): [a, b]})
    assert before == untouched
    records = {item["key"]: item["metadata"]["extra"]["version"] for item in plan["migrations"]}
    assert records[a]["number"] == 1
    assert records[b]["number"] == 2 and records[b]["previousKey"] == a
    assert records[a]["seriesId"] == records[b]["seriesId"]
    assert records[c] == {"schemaVersion": 1, "seriesId": hashlib.sha256(c.encode()).hexdigest()[:24], "number": 1}
    again = version_plan([{**entry, "metadata": item["metadata"]} for entry, item in zip(before, plan["migrations"])],
                         {("test-game", "fictional-character", "portrait"): [a, b]})
    assert again["migrations"] == []


def test_version_plan_blocks_missing_or_conflicting_history():
    key = "games/test-game/assets/a/original/a.png"
    with pytest.raises(ClickException, match="missing"):
        version_plan([record(key)], {("test-game", "character", "portrait"): ["games/test-game/assets/no/original/b.png"]})
    with pytest.raises(ClickException, match="multiple"):
        version_plan([record(key)], {("test-game", "one", "portrait"): [key], ("test-game", "two", "portrait"): [key]})
