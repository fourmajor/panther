import importlib
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
    monkeypatch.setenv("CATALOG_EDITORS", "stu,other_stu")
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
        "players": [{"id": "person-a", "name": "Person A"}, {"id": "person-b", "name": "Person B"}],
        "characters": [{"id": "hero", "name": "Hero"}],
        "memberships": [
            {"playerId": "person-a", "role": "player", "characterIds": ["hero"]},
            {"playerId": "person-b", "role": "dungeon-master", "characterIds": []},
        ],
    }


def request(m, route, body=None, username="stu", game="test-game"):
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
    for route in ("GET /games", "GET /game", "GET /players", "POST /games"):
        assert request(catalog, route, setup(), username="outsider")["statusCode"] == 403


def test_legacy_assets_remain_discoverable_without_migration(catalog):
    catalog.media.s3.put_object(
        Bucket="test-assets", Key="games/older-game/assets/map/original/map.txt", Body=b"test"
    )
    result = json.loads(request(catalog, "GET /games")["body"])
    assert result["games"][0]["id"] == "older-game"
    assert result["games"][0]["legacy"] is True
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
