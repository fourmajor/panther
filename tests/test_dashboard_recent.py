# ruff: noqa: F811
# Imported pytest fixtures intentionally share names with test parameters.
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from test_game_catalog import catalog, request, setup  # noqa: F401


def test_session_identity_resolves_shared_deep_lineage_without_recursive_expansion(catalog):
    import dashboard_recent
    root = {"key": "root", "kind": "raw-transcript", "metadata": {"sessionId": "known-session"}}
    assets, previous = [root], ["root"]
    for level in range(1200):
        layer = [{"key": f"level-{level}-{side}", "kind": "corrected-transcript", "sourceKeys": previous}
                 for side in range(2)]
        assets.extend(layer)
        previous = [item["key"] for item in layer]
    assert len(dashboard_recent.session_entries(assets)) == 1


def test_cyclic_session_lineage_fails_explicitly_instead_of_inventing_group(catalog):
    import dashboard_recent
    assets = [{"key": "first", "kind": "raw-transcript", "sourceKeys": ["second"]},
              {"key": "second", "kind": "corrected-transcript", "sourceKeys": ["first"]}]
    with pytest.raises(RuntimeError, match="lineage contains a cycle"):
        dashboard_recent.session_entries(assets)


def prepare(catalog):
    assert request(catalog, "POST /games", setup())["statusCode"] == 200
    import browse_index

    db = browse_index.table()
    db.put_item(Item={"pk": f"v{browse_index.VERSION}#catalog", "sk": "ready"})
    return db, browse_index


def put_asset(
    db, index, number, *, kind="raw-transcript", game="test-game", suffix="json", novel=False
):
    key = f"games/{game}/assets/source-{number:04d}/original/asset.{suffix}"
    item = {
        "key": key,
        "name": f"asset.{suffix}",
        "kind": kind,
        "contentType": "video/mp4" if suffix == "mp4" else "application/json",
        "lastModified": (
            datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=number)
        ).isoformat(),
        "metadata": {"title": f"Source {number}"},
    }
    if novel:
        item["novel"] = {
            "state": "available",
            "id": f"chapter-{number}",
            "title": f"Chapter {number}",
        }
    db.put_item(Item={"pk": index.partition(game, "all"), "sk": key, "payload": json.dumps(item)})
    return key


def test_recent_is_complete_beyond_first_page_without_reading_asset_bodies(catalog):
    db, index = prepare(catalog)
    for number in range(125):
        put_asset(db, index, number)
    put_asset(db, index, 124, suffix="md")
    for number in range(6):
        put_asset(db, index, 200 + number, kind="video", suffix="mp4")
    for number in range(6):
        put_asset(db, index, 300 + number, kind="novel-chapter", novel=True)
    put_asset(db, index, 999, game="other-game")
    catalog.media.s3 = Mock()
    result = request(catalog, "GET /dashboard-recent", username="example-member")
    assert result["statusCode"] == 200, result
    value = json.loads(result["body"])
    assert value["complete"] is True
    assert value["counts"] == {
        "characters": 1,
        "transcripts": 125,
        "videos": 6,
        "chapters": 6,
        "assets": 137,
        "sessions": 125,
        "episodes": 0,
    }
    assert [item["title"] for item in value["groups"]["transcripts"]] == [
        f"Source {n}" for n in range(124, 119, -1)
    ]
    assert value["groups"]["chapters"][0]["title"] == "Chapter 305"
    assert value["groups"]["videos"][0]["title"] == "Source 205"
    assert value["groups"]["characters"][0]["updatedAt"] is None
    assert not catalog.media.s3.mock_calls
    assert request(catalog, "GET /dashboard-recent", username="outsider")["statusCode"] == 403


def test_character_recency_uses_actual_revision_history_and_preserves_unknown(catalog):
    prepare(catalog)
    catalog.table.put_item(
        Item={
            "pk": "GAME#test-game",
            "sk": "CHARACTER#recent",
            "entityType": "Character",
            "id": "recent",
            "gameId": "test-game",
            "name": "Recent",
            "detailsRevision": "b" * 32,
        }
    )
    catalog.table.put_item(
        Item={
            "pk": "CHARACTER_DETAILS_HISTORY#test-game#recent",
            "sk": "b" * 32,
            "recordedAt": "2026-09-30T12:00:00+00:00",
            "actor": "PRIVATE-ACTOR-EXCLUDED",
        }
    )
    value = json.loads(request(catalog, "GET /dashboard-recent", username="example-member")["body"])
    assert value["groups"]["characters"][0]["id"] == "recent"
    assert value["groups"]["characters"][0]["updatedAt"] == "2026-09-30T12:00:00+00:00"
    assert value["groups"]["characters"][1]["updatedAt"] is None
    assert "PRIVATE-ACTOR-EXCLUDED" not in json.dumps(value)


def test_dashboard_fails_closed_when_index_not_ready_or_complete_bound_exceeded(
    catalog, monkeypatch
):
    assert request(catalog, "POST /games", setup())["statusCode"] == 200
    assert request(catalog, "GET /dashboard-recent", username="example-member")["statusCode"] == 503
    db, index = prepare(catalog)
    import dashboard_recent

    monkeypatch.setattr(dashboard_recent, "MAX_ASSETS", 2)
    for number in range(3):
        put_asset(db, index, number)
    result = request(catalog, "GET /dashboard-recent", username="example-member")
    assert result["statusCode"] == 503
    assert "groups" not in json.loads(result["body"])


def test_dashboard_assets_are_finished_images_from_catalog_metadata(catalog):
    db, index = prepare(catalog)
    for number, kind, extra in [
        (1, "map", {}),
        (2, "unknown-image", {}),
        (3, "generation-provenance", {}),
        (4, "image", {"relationshipRole": "intermediate"}),
        (5, "image", {"browserPart": 1}),
        (6, "generation-plan", {}),
    ]:
        key = put_asset(db, index, number, kind=kind, suffix="png")
        row = db.get_item(Key={"pk": index.partition("test-game", "all"), "sk": key})["Item"]
        asset = json.loads(row["payload"])
        asset["contentType"] = "image/png"
        asset["metadata"]["extra"] = extra
        db.put_item(Item={**row, "payload": json.dumps(asset)})
    catalog.media.s3 = Mock()
    value = json.loads(request(catalog, "GET /dashboard-recent", username="example-member")["body"])
    assert value["counts"]["assets"] == 2
    assert [a["kind"] for a in value["groups"]["assets"]] == ["unknown-image", "map"]
    assert not catalog.media.s3.mock_calls


def test_dashboard_six_recent_assets_and_actual_session_episode_counts(catalog):
    db, index = prepare(catalog)
    for number in range(8):
        key = put_asset(db, index, number, kind="raw-transcript")
        row = db.get_item(Key={"pk": index.partition("test-game", "all"), "sk": key})["Item"]
        asset = json.loads(row["payload"])
        asset["metadata"]["sessionId"] = "shared-session"
        db.put_item(Item={**row, "payload": json.dumps(asset)})
    for number in range(2):
        db.put_item(Item={"pk": "episode-scenes-v1#episode#test-game", "sk": str(number),
            "payload": json.dumps({"id": f"episode-{number}", "name": f"Episode {number}", "updatedAt": "2026-09-30T12:00:00+00:00"})})
    value = json.loads(request(catalog, "GET /dashboard-recent", username="example-member")["body"])
    assert value["counts"]["sessions"] == 1
    assert value["counts"]["episodes"] == 2
    assert value["counts"]["assets"] == 8
    assert len(value["groups"]["assets"]) == 6
    assert value["groups"]["assets"][0]["title"] == "Source 7"


def test_session_counts_follow_exact_inputs_without_guessing_from_titles(catalog):
    import dashboard_recent

    raw = {"key": "raw", "kind": "raw-transcript", "metadata": {"sessionId": "session-one"}}
    corrected = {"key": "corrected", "kind": "corrected-transcript", "sourceKeys": ["raw"], "metadata": {}}
    audio = {"key": "audio", "kind": "recording-playback", "sourceKeys": ["raw"], "metadata": {}}
    unrelated = {"key": "other", "kind": "raw-transcript", "metadata": {"title": "Same name"}}
    narration = {"key": "narration", "kind": "narration", "contentType": "audio/mp3", "metadata": {}}
    entries = dashboard_recent.session_entries([raw, corrected, audio, unrelated, narration])
    assert {entry["key"] for entry in entries} == {"raw", "other"}
