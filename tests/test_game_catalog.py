import importlib
import base64
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws

from panther_journal.cli import main
from panther_journal.domain import GameSetup, Player


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("ASSET_BUCKET_NAME", "test-assets")
    monkeypatch.setenv("CATALOG_TABLE", "test-catalog")
    monkeypatch.setenv("CATALOG_EDITORS", "example-operator,example-editor")
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "infra/lambda/media-api"))
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="test-catalog",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
        )
        boto3.client("s3").create_bucket(
            Bucket="test-assets", CreateBucketConfiguration={"LocationConstraint": "us-west-2"}
        )
        for module in ("index", "catalog"):
            monkeypatch.delitem(sys.modules, module, raising=False)
        yield importlib.import_module("catalog")


def setup(game="test-game"):
    return {
        "id": game,
        "name": "Synthetic Game",
        "purpose": "test",
        "ruleset": "Synthetic System (First Edition)",
        "players": [{"id": "person-a", "name": "Person A"}, {"id": "person-b", "name": "Person B"}],
        "characters": [{"id": "hero", "name": "Hero"}],
        "memberships": [
            {"playerId": "person-a", "role": "player", "characterIds": ["hero"]},
            {"playerId": "person-b", "role": "dungeon-master", "characterIds": []},
        ],
    }


def test_visual_style_settings_and_history(catalog):
    assert request(catalog, "POST /games", setup())["statusCode"] == 200
    body = {"gameId": "test-game", "visualStyle": "anime", "expectedStyle": "photorealistic"}
    assert request(catalog, "POST /game/style", body, username="outsider")["statusCode"] == 403
    before = catalog.read("GAMES", "test-game")
    result = request(catalog, "POST /game/style", body)
    assert result["statusCode"] == 200
    detail = json.loads(result["body"])
    assert detail["game"]["visualStyle"] == "anime"
    assert len(detail["visualStyles"]) == 8
    assert detail["game"]["ruleset"] == before["ruleset"]
    assert len(detail["memberships"]) == 2
    assert request(catalog, "POST /game/style", body)["statusCode"] == 409
    assert (
        request(catalog, "POST /game/style", {**body, "visualStyle": "unknown"})["statusCode"]
        == 400
    )
    history = [r for r in catalog.query("GAME#test-game") if r["entityType"] == "GameStyleChange"]
    assert len(history) == 1
    assert history[0]["previousStyle"] == "photorealistic"


def test_visual_style_backfill_is_guarded(catalog):
    catalog.table.put_item(
        Item={
            "pk": "GAMES",
            "sk": "old-game",
            "id": "old-game",
            "entityType": "Game",
            "name": "Example",
            "purpose": "test",
        }
    )
    body = {"gameId": "old-game", "visualStyle": "photorealistic", "expectedStyle": None}
    assert request(catalog, "POST /game/style", body)["statusCode"] == 200
    assert request(catalog, "POST /game/style", body)["statusCode"] == 409


def test_initialize_character_profile_is_roster_bound_and_create_only(catalog, monkeypatch):
    assert request(catalog, "POST /games", setup())["statusCode"] == 200
    portrait = "games/test-game/assets/portrait/original/portrait.png"
    fake = Mock()
    fake.head_object.return_value = {
        "ContentLength": 10,
        "ContentType": "image/png",
        "Metadata": {
            "panther": base64.b64encode(json.dumps({"characterIds": ["hero"]}).encode()).decode()
        },
    }
    fake.put_object.return_value = {"ETag": '"initial"'}
    monkeypatch.setattr(catalog.media, "s3", fake)
    body = {
        "gameId": "test-game",
        "characterId": "hero",
        "title": "Swashbuckler",
        "summary": "A swashbuckler with a rapier.",
        "portraitKey": portrait,
    }
    result = request(catalog, "POST /character-profile", body)
    assert result["statusCode"] == 201
    profile = json.loads(result["body"])["profile"]
    assert profile["name"] == "Hero" and profile["model"] == {"posterKey": portrait}
    assert fake.put_object.call_args.kwargs["IfNoneMatch"] == "*"
    assert (
        request(catalog, "POST /character-profile", body, username="outsider")["statusCode"] == 403
    )
    assert (
        request(catalog, "POST /character-profile", {**body, "characterId": "unknown"})[
            "statusCode"
        ]
        == 404
    )
    assert (
        request(
            catalog,
            "POST /character-profile",
            {**body, "portraitKey": portrait.replace("test-game", "other-game")},
        )["statusCode"]
        == 400
    )
    fake.head_object.return_value["Metadata"] = {}
    assert request(catalog, "POST /character-profile", body)["statusCode"] == 422


def request(m, route, body=None, username="example-operator", game="test-game"):
    return m.handler(
        {
            "routeKey": route,
            "body": json.dumps(body),
            "queryStringParameters": {"gameId": game},
            "requestContext": {
                "authorizer": {
                    "jwt": {"claims": {"sub": "test-owner", "cognito:username": username}}
                }
            },
        },
        None,
    )


def test_structured_records_atomic_idempotent_and_reusable(catalog):
    body = GameSetup.model_validate(setup()).model_dump()
    assert isinstance(GameSetup.model_validate(body).players[0], Player)
    first = request(catalog, "POST /games", body)
    assert first["statusCode"] == 200, first
    data = json.loads(first["body"])
    assert data["game"]["purpose"] == "test"
    assert data["game"]["ruleset"] == body["ruleset"]
    assert {p["entityType"] for p in data["players"]} == {"Player"}
    assert data["memberships"][1]["characterIds"] == []
    assert request(catalog, "POST /games", body) == first
    assert request(catalog, "POST /games", setup("another-game"))["statusCode"] == 200
    assert len(catalog.query("PLAYERS")) == 2
    body["name"] = "Changed"
    assert request(catalog, "POST /games", body)["statusCode"] == 409
    assert catalog.read("GAMES", "test-game")["name"] == "Synthetic Game"


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b["memberships"][1].update(characterIds=["hero"]),
        lambda b: b["memberships"][0].update(characterIds=["missing"]),
        lambda b: b["players"].append(b["players"][0]),
        lambda b: b.update(id="../escape"),
        lambda b: b.update(purpose="anything"),
        lambda b: b.update(password="not-allowed"),
        lambda b: b.update(ruleset=""),
        lambda b: b.update(ruleset=" padded "),
        lambda b: b.update(ruleset="x" * 121),
        lambda b: b.update(ruleset="bad\nname"),
        lambda b: b.update(ruleset={"text": "not-a-name"}),
    ],
)
def test_invalid_roster_does_not_write(catalog, change):
    body = setup()
    change(body)
    assert request(catalog, "POST /games", body)["statusCode"] == 400
    assert catalog.query("GAMES") == []
    assert catalog.query("PLAYERS") == []


def test_player_conflict_never_partially_creates_game(catalog):
    request(catalog, "POST /games", setup())
    body = setup("new-game")
    body["players"][0]["name"] = "Somebody else"
    assert request(catalog, "POST /games", body)["statusCode"] == 409
    assert catalog.read("GAMES", "new-game") is None


def test_catalog_rejects_unapproved_account(catalog):
    for route in ("GET /games", "GET /game", "GET /players", "POST /games", "POST /game/ruleset"):
        assert request(catalog, route, setup(), username="outsider")["statusCode"] == 403


def put_indexed_fixture(catalog, key, body):
    import base64
    import hashlib

    storage = catalog.media.s3
    target = storage.reserve(
        key,
        "map",
        {"characterIds": [], "extra": {"relationshipRole": "finished"}},
        base64.b64encode(hashlib.sha256(body).digest()).decode(),
        len(body),
        "2020-01-01T00:00:00+00:00",
    )
    storage.raw.put_object(Bucket="test-assets", Key=target, Body=body)


def test_indexed_assets_are_discoverable_without_a_roster(catalog):
    put_indexed_fixture(catalog, "games/older-game/assets/map/original/map.txt", b"test")
    result = json.loads(request(catalog, "GET /games")["body"])
    assert result["games"][0]["id"] == "older-game"
    assert result["games"][0]["legacy"] is True
    assert result["games"][0]["ruleset"] is None
    assert json.loads(request(catalog, "GET /game", game="older-game")["body"])["players"] == []


def test_cli_creates_game_via_panther_not_aws(tmp_path, monkeypatch):
    from panther_journal import cloud

    manifest = tmp_path / "setup.json"
    manifest.write_text(json.dumps(setup()))
    api = Mock(return_value={"game": {"id": "test-game"}})
    monkeypatch.setattr(cloud, "configuration", lambda: {})
    monkeypatch.setattr(cloud, "api", api)
    result = CliRunner().invoke(main, ["game", "create", str(manifest)])
    assert result.exit_code == 0, result.output
    assert api.call_args.args[1:3] == ("POST", "/games")


def test_ruleset_changes_preserve_roster_and_refuse_stale_updates(catalog):
    original = setup()
    before = json.loads(request(catalog, "POST /games", original)["body"])
    body = {
        "gameId": "test-game",
        "ruleset": "Other Synthetic System",
        "expectedRuleset": original["ruleset"],
    }
    reply = request(catalog, "POST /game/ruleset", body)
    assert reply["statusCode"] == 200, reply
    after = json.loads(reply["body"])
    for field in ("players", "characters", "memberships"):
        assert after[field] == before[field]
    assert after["game"]["ruleset"] == body["ruleset"]
    assert request(catalog, "POST /game/ruleset", body)["statusCode"] == 409
    # An exact retry of original creation does not revert an updated ruleset.
    assert (
        json.loads(request(catalog, "POST /games", original)["body"])["game"]["ruleset"]
        == body["ruleset"]
    )


def test_ruleset_adopts_legacy_header_without_touching_assets(catalog):
    key = "games/older-game/assets/map/original/map.txt"
    put_indexed_fixture(catalog, key, b"unchanged")
    body = {"gameId": "older-game", "ruleset": "Synthetic Hack", "expectedRuleset": None}
    reply = request(catalog, "POST /game/ruleset", body)
    assert reply["statusCode"] == 200, reply
    data = json.loads(reply["body"])
    assert data["game"]["ruleset"] == "Synthetic Hack"
    assert data["players"] == data["memberships"] == data["characters"] == []
    assert catalog.media.s3.get_object(Bucket="test-assets", Key=key)["Body"].read() == b"unchanged"
    assert request(catalog, "POST /games", setup("older-game"))["statusCode"] == 409
    body["gameId"] = "nonexistent"
    assert request(catalog, "POST /game/ruleset", body)["statusCode"] == 404


def test_old_client_creation_and_old_records_remain_supported(catalog):
    body = setup()
    del body["ruleset"]
    first = request(catalog, "POST /games", body)
    assert first["statusCode"] == 200
    assert json.loads(first["body"])["game"]["ruleset"] is None
    assert request(catalog, "POST /games", body) == first
    old = catalog.read("GAMES", "test-game")
    del old["ruleset"]
    catalog.table.put_item(Item=old)
    reply = request(
        catalog,
        "POST /game/ruleset",
        {"gameId": "test-game", "ruleset": "Synthetic", "expectedRuleset": None},
    )
    assert reply["statusCode"] == 200, reply


def test_ruleset_update_condition_rejects_race(catalog, monkeypatch):
    request(catalog, "POST /games", setup())
    update = catalog.table.update_item

    def race(**kwargs):
        update(
            Key={"pk": "GAMES", "sk": "test-game"},
            UpdateExpression="SET ruleset = :r",
            ExpressionAttributeValues={":r": "Concurrent"},
        )
        return update(**kwargs)

    monkeypatch.setattr(catalog.table, "update_item", race)
    reply = request(
        catalog,
        "POST /game/ruleset",
        {"gameId": "test-game", "ruleset": "Stale", "expectedRuleset": setup()["ruleset"]},
    )
    assert reply["statusCode"] == 409
    assert catalog.read("GAMES", "test-game")["ruleset"] == "Concurrent"


def test_cli_ruleset_update_requires_explicit_precondition(monkeypatch):
    from panther_journal import cloud

    api = Mock(return_value={"game": {"id": "test-game", "ruleset": "Synthetic"}})
    monkeypatch.setattr(cloud, "configuration", lambda: {})
    monkeypatch.setattr(cloud, "api", api)
    args = ["game", "set-ruleset", "test-game", "--ruleset", "Synthetic"]
    assert CliRunner().invoke(main, args).exit_code != 0
    assert (
        CliRunner().invoke(main, args + ["--if-unset", "--expected-ruleset", "Old"]).exit_code != 0
    )
    assert not api.called
    result = CliRunner().invoke(main, args + ["--if-unset"])
    assert result.exit_code == 0, result.output
    assert api.call_args.args[1:3] == ("POST", "/game/ruleset")
    assert api.call_args.kwargs["json"]["expectedRuleset"] is None
