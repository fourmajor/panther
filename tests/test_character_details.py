import base64
import json
import uuid
from unittest.mock import Mock

import pytest

from test_game_catalog import catalog as catalog_fixture, request, setup


@pytest.fixture
def catalog(monkeypatch):
    yield from catalog_fixture.__wrapped__(monkeypatch)


def envelope(record, **changes):
    return {
        "gameId": "test-game",
        "characterId": "hero",
        "mode": "edit",
        "details": json.loads(record["detailsJson"]),
        "expectedRevision": record["detailsRevision"],
        "expectedSourceHash": None,
        "operationId": uuid.uuid4().hex,
        "reason": "Synthetic character update",
        "dryRun": False,
        **changes,
    }


def test_structured_profiles_preserve_roster_artwork_and_history_with_replay(catalog):
    request(catalog, "POST /games", setup())
    memberships = json.loads(request(catalog, "GET /game")["body"])["memberships"]
    before = catalog.read("GAME#test-game", "CHARACTER#hero")
    body = envelope(before)
    body["details"].update(
        aliases=["Lantern Bearer"],
        pronouns="they/them",
        role="Scout",
        status="Active",
        backstory="An explicitly supplied fictional background.",
        statistics=[
            {"group": "Abilities", "name": "Strength", "value": 14},
            {"group": "Skills", "name": "Stealth", "value": 3.5},
            {"group": None, "name": "Inspiration", "value": False},
            {"group": None, "name": "Unknown trait", "value": None},
        ],
        relationships=[{"entityType": "Player", "id": "person-a", "relation": "Played by"}],
    )
    result = request(catalog, "POST /character-details", body)
    assert result["statusCode"] == 200
    after = catalog.read("GAME#test-game", "CHARACTER#hero")
    assert (
        after["name"] == before["name"]
        and after["id"] == before["id"]
        and after["schemaVersion"] == 2
    )
    assert after["detailsRevision"] != before["detailsRevision"]
    history = catalog.query("CHARACTER_DETAILS_HISTORY#test-game#hero")
    assert len(history) == 1 and history[0]["previousDetailsJson"] == before["detailsJson"]
    newer = envelope(after)
    newer["details"]["status"] = "Resting"
    assert request(catalog, "POST /character-details", newer)["statusCode"] == 200
    replay = json.loads(request(catalog, "POST /character-details", body)["body"])
    assert replay["replayed"] and replay["character"]["details"]["status"] == "Resting"
    assert replay["operationRevision"] == after["detailsRevision"]
    assert (
        request(catalog, "POST /character-details", {**body, "reason": "Different"})["statusCode"]
        == 409
    )
    assert request(catalog, "POST /character-details", envelope(before))["statusCode"] == 409
    assert json.loads(request(catalog, "GET /game")["body"])["memberships"] == memberships


@pytest.mark.parametrize(
    "change",
    [
        {"aliases": ["A", "A"]},
        {"pronouns": 12},
        {"statistics": [{"group": None, "name": "X", "value": {"nested": "bad"}}]},
        {"statistics": [{"group": None, "name": "X", "value": float("nan")}]},
        {"relationships": [{"entityType": "Character", "id": "missing", "relation": "Knows"}]},
        {"relationships": [{"entityType": "Player", "id": "outsider", "relation": "Played by"}]},
        {
            "relationships": [
                {"entityType": "URL", "id": "https://evil.example", "relation": "Link"}
            ]
        },
        {"thumbnailAssetKey": "games/other/assets/x/original/image.png"},
        {
            "relationships": [
                {
                    "entityType": "Asset",
                    "id": "games/other/assets/x/original/image.png",
                    "relation": "Source",
                }
            ]
        },
    ],
)
def test_profiles_reject_invalid_facts_and_cross_game_relationships(catalog, change):
    request(catalog, "POST /games", setup())
    body = envelope(catalog.read("GAME#test-game", "CHARACTER#hero"))
    body["details"].update(change)
    assert request(catalog, "POST /character-details", body)["statusCode"] == 400
    assert catalog.query("CHARACTER_DETAILS_HISTORY#test-game#hero") == []


def test_migration_is_admin_only_dry_run_guarded_and_preserves_original_record(
    catalog, monkeypatch
):
    request(catalog, "POST /games", setup())
    old = catalog.read("GAME#test-game", "CHARACTER#hero")
    old.pop("detailsJson")
    old.pop("detailsRevision")
    old["schemaVersion"] = 1
    catalog.table.put_item(Item=old)
    monkeypatch.setattr(catalog.media, "_profile_record", lambda *_args: None)
    body = {
        "gameId": "test-game",
        "characterId": "hero",
        "mode": "migrate",
        "details": None,
        "expectedRevision": None,
        "expectedSourceHash": None,
        "operationId": uuid.uuid4().hex,
        "reason": "Versioned all-game migration",
        "dryRun": True,
    }
    assert (
        request(catalog, "POST /character-details/migrate", body, username="example-editor")[
            "statusCode"
        ]
        == 403
    )
    assert request(catalog, "POST /character-details", body)["statusCode"] == 400
    prepared = json.loads(request(catalog, "POST /character-details/migrate", body)["body"])
    assert prepared["status"] == "ready" and prepared["plan"]["details"]["pronouns"] is None
    assert catalog.read("GAME#test-game", "CHARACTER#hero") == old
    plan = prepared["plan"]
    assert (
        request(
            catalog, "POST /character-details/migrate", {**plan, "expectedSourceHash": "0" * 64}
        )["statusCode"]
        == 409
    )
    assert request(catalog, "POST /character-details/migrate", plan)["statusCode"] == 200
    result = json.loads(request(catalog, "POST /character-details/migrate", plan)["body"])
    assert result["replayed"]
    assert catalog.query("CHARACTER_DETAILS_HISTORY#test-game#hero")[0]["legacyRecord"] == old
    assert catalog.read("GAME#test-game", "CHARACTER#hero")["detailsRevision"]


def test_character_browsing_is_bounded_metadata_only_and_never_reads_s3(catalog, monkeypatch):
    request(catalog, "POST /games", setup())
    for number in range(65):
        request(
            catalog,
            "POST /game/characters",
            {"gameId": "test-game", "id": f"npc-{number}", "name": f"NPC {number}"},
        )

    def forbidden(*_args, **_kwargs):
        pytest.fail("Character browsing must not read/scan S3")

    monkeypatch.setattr(catalog.media.s3, "get_object", forbidden)
    monkeypatch.setattr(catalog.media.s3, "get_paginator", forbidden)
    first = json.loads(request(catalog, "GET /characters")["body"])
    assert len(first["characters"]) == 60 and first["cursor"]
    assert all("details" not in c and "detailsJson" not in c for c in first["characters"])
    event = {
        "routeKey": "GET /characters",
        "queryStringParameters": {"gameId": "test-game", "cursor": first["cursor"]},
        "requestContext": {
            "authorizer": {
                "jwt": {"claims": {"sub": "synthetic", "cognito:username": "example-operator"}}
            }
        },
    }
    following = json.loads(catalog.handler(event, None)["body"])
    assert len(following["characters"]) == 6 and following["cursor"] is None
    bad = base64.urlsafe_b64encode(
        json.dumps({"pk": "GAME#other", "sk": "CHARACTER#hero"}).encode()
    ).decode()
    event["queryStringParameters"]["cursor"] = bad
    assert catalog.handler(event, None)["statusCode"] == 400


def test_migration_pins_known_artwork_profile_and_reports_unmapped_stats(catalog, monkeypatch):
    request(catalog, "POST /games", setup())
    old = catalog.read("GAME#test-game", "CHARACTER#hero")
    old.pop("detailsJson")
    old.pop("detailsRevision")
    old["schemaVersion"] = 1
    catalog.table.put_item(Item=old)
    profile = {"summary": "Known source overview", "title": "Known source title", "model": {}}
    raw = json.dumps(profile).encode()
    monkeypatch.setattr(
        catalog.media,
        "_profile_record",
        lambda *_args: (
            "games/test-game/characters/hero/profile.json",
            raw,
            profile,
            "source-etag",
        ),
    )
    monkeypatch.setattr(
        catalog.media.s3, "head_object", Mock(return_value={"VersionId": "source-version"})
    )
    import character_details

    details, source, _ = character_details.legacy_projection(catalog, old)
    assert details["overview"] == profile["summary"] and details["subtitle"] == profile["title"]
    assert source["versionId"] == "source-version" and source["etag"] == "source-etag"
    profile["stats"] = {"unmapped": 12}
    with pytest.raises(ValueError, match="explicit mapping"):
        character_details.legacy_projection(catalog, old)


def test_inventory_is_migration_only_and_reports_orphans(catalog):
    request(catalog, "POST /games", setup())
    key = "games/test-game/characters/orphan/profile.json"
    catalog.media.s3.put_object(Bucket=catalog.media.BUCKET_NAME, Key=key, Body=b"{}")
    event = {
        "routeKey": "GET /character-details/inventory",
        "queryStringParameters": {"gameId": "test-game"},
        "requestContext": {
            "authorizer": {"jwt": {"claims": {"sub": "fictional", "cognito:username": "other"}}}
        },
    }
    assert catalog.handler(event, None)["statusCode"] == 403
    response = request(catalog, "GET /character-details/inventory")
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["profiles"] == [
        {"characterId": "orphan", "key": key, "registered": False}
    ]


def test_verification_rejects_corrupt_migration_history(catalog):
    request(catalog, "POST /games", setup())
    record = catalog.read("GAME#test-game", "CHARACTER#hero")
    event = {
        "routeKey": "GET /character-details/verify",
        "queryStringParameters": {"gameId": "test-game", "characterId": "hero"},
        "requestContext": {
            "authorizer": {
                "jwt": {"claims": {"sub": "synthetic", "cognito:username": "example-operator"}}
            }
        },
    }
    assert catalog.handler(event, None)["statusCode"] == 200
    record["detailsMigrationRevision"] = "a" * 32
    catalog.table.put_item(Item=record)
    assert catalog.handler(event, None)["statusCode"] == 400
