import importlib
import json
from unittest.mock import Mock

import boto3
import pytest
from click.testing import CliRunner

from test_model_jobs import broker  # noqa: F401


@pytest.fixture
def migration(broker, monkeypatch):  # noqa: F811
    module = importlib.import_module("episode_migration")
    monkeypatch.setenv("ASSET_MIGRATORS", "example-migrator")
    db = module.browse_index.table()
    catalog = boto3.resource("dynamodb").Table("test-job-catalog")
    for game in ("test-game", "other-game"):
        catalog.put_item(Item={"pk": "GAMES", "sk": game})
        record = {"schemaVersion": 1, "entityType": "TVEpisode", "gameId": game,
                  "id": "arrival", "title": "Arrival", "synopsis": "A ship arrives.",
                  "revision": "a" * 32, "number": 1, "cuts": [{"id": "alternate"}]}
        payload = json.dumps(record)
        db.put_item(Item={"pk": f"tv-library#episode#{game}", "sk": "arrival", "revision": "a" * 32, "payload": payload})
        db.put_item(Item={"pk": f"tv-library-history#episode#{game}#arrival", "sk": "a" * 32, "payload": payload})
    return module, broker.media, db


def test_complete_dry_run_apply_retry_preserves_sources_and_no_scenes(migration):
    module, media, db = migration
    body = {"schemaVersion": 1, "apply": False}
    preview = json.loads(module.migrate(media, body, {})["body"])
    assert len(preview["episodes"]) == 2
    assert "Item" not in db.get_item(Key=module.records.pointer(module.PREFIX, "test-game", "episode", "arrival"))
    body.update(apply=True, expectedInventoryHash=preview["inventoryHash"])
    response = module.migrate(media, body, {"sub": "fictional-migrator"})
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["appliedCount"] == 2
    assert json.loads(module.migrate(media, body, {"sub": "fictional-migrator"})["body"])["appliedCount"] == 0
    target = module.records.decode(db.get_item(Key=module.records.pointer(module.PREFIX, "test-game", "episode", "arrival"))["Item"])
    assert target["name"] == "Arrival" and target["description"] == "A ship arrives."
    assert "cuts" not in target and "scenes" not in target
    audit = db.get_item(Key={"pk": f"{module.AUDIT}#test-game", "sk": "arrival"})["Item"]
    snapshot = json.loads(audit["snapshot"])
    assert module.digest(snapshot) == audit["sourceHash"]
    assert snapshot["current"]["payload"] == snapshot["history"][0]["payload"]
    assert db.get_item(Key={"pk": "tv-library#episode#test-game", "sk": "arrival"})["Item"] == snapshot["current"]


def test_conflict_and_stale_inventory_fail_before_writes(migration):
    module, media, db = migration
    assert module.migrate(media, {"schemaVersion": 1, "apply": True, "expectedInventoryHash": "0" * 64}, {})["statusCode"] == 409
    db.put_item(Item={**module.records.pointer(module.PREFIX, "other-game", "episode", "arrival"), "payload": "{}"})
    preview = json.loads(module.migrate(media, {"schemaVersion": 1, "apply": False}, {})["body"])
    assert any(row["status"] == "conflict" for row in preview["episodes"])
    assert module.migrate(media, {"schemaVersion": 1, "apply": True, "expectedInventoryHash": preview["inventoryHash"]}, {})["statusCode"] == 409
    assert "Item" not in db.get_item(Key=module.records.pointer(module.PREFIX, "test-game", "episode", "arrival"))


def test_bounds_and_missing_history_block_complete_plan(migration, monkeypatch):
    module, media, db = migration
    monkeypatch.setattr(module, "MAX_ROWS", 2)
    with pytest.raises(ValueError, match="inventory"):
        module.inventory(media)
    monkeypatch.setattr(module, "MAX_ROWS", 1000)
    db.delete_item(Key={"pk": "tv-library-history#episode#test-game#arrival", "sk": "a" * 32})
    with pytest.raises(ValueError, match="exact retained history"):
        module.inventory(media)


def test_authorization_is_migrator_only(migration):
    module, _, _ = migration
    response = module.handler({"body": '{}', "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "fictional-owner", "cognito:username": "example-operator"}}}}}, None)
    assert response["statusCode"] == 403


def test_cli_requires_reviewed_hash_and_uses_panther_auth(monkeypatch):
    from panther_journal import video_library
    api = Mock(return_value={"inventoryHash": "a" * 64})
    monkeypatch.setattr(video_library.cloud, "api", api)
    monkeypatch.setattr(video_library.cloud, "configuration", lambda: {})
    runner = CliRunner()
    assert runner.invoke(video_library.videos, ["migrate-workspace", "--apply"]).exit_code != 0
    assert not api.called
    assert runner.invoke(video_library.videos, ["migrate-workspace"]).exit_code == 0
    assert api.call_args.kwargs["json"] == {"schemaVersion": 1, "apply": False}
    assert runner.invoke(video_library.videos, ["migrate-workspace", "--apply", "--inventory-hash", "a" * 64]).exit_code == 0
    assert api.call_args.args[2] == "/video-workspace/migrate"


def test_missing_destination_history_is_not_success_and_human_edits_survive(migration):
    module, media, db = migration
    preview = json.loads(module.migrate(media, {"schemaVersion": 1, "apply": False}, {})["body"])
    body = {"schemaVersion": 1, "apply": True, "expectedInventoryHash": preview["inventoryHash"]}
    assert module.migrate(media, body, {"sub": "fictional-migrator"})["statusCode"] == 200
    key = module.records.pointer(module.PREFIX, "test-game", "episode", "arrival")
    item = db.get_item(Key=key)["Item"]
    current = module.records.decode(item)
    imported_revision = current["revision"]
    current.update(name="Edited title", revision="b" * 32)
    current.pop("migration")
    db.put_item(Item={**key, "revision": current["revision"], "payload": json.dumps(current)})
    assert json.loads(module.migrate(media, body, {"sub": "fictional-migrator"})["body"])["appliedCount"] == 0
    assert module.records.decode(db.get_item(Key=key)["Item"])["name"] == "Edited title"
    db.delete_item(Key={"pk": f"{module.PREFIX}-history#episode#test-game#arrival", "sk": imported_revision})
    assert module.migrate(media, body, {"sub": "fictional-migrator"})["statusCode"] == 409


def test_zero_legacy_episodes_is_a_complete_noop(migration):
    module, media, db = migration
    for game in ("test-game", "other-game"):
        db.delete_item(Key={"pk": f"tv-library#episode#{game}", "sk": "arrival"})
    preview = json.loads(module.migrate(media, {"schemaVersion": 1, "apply": False}, {})["body"])
    assert preview["episodes"] == []
    applied = module.migrate(media, {"schemaVersion": 1, "apply": True, "expectedInventoryHash": preview["inventoryHash"]}, {"sub": "fictional-migrator"})
    assert json.loads(applied["body"])["episodeCount"] == 0


def test_conflicting_exact_source_guard_never_overwrites(migration, monkeypatch):
    module, media, db = migration
    original = module.inventory

    def inventory_then_change(media):
        result = original(media)
        item = db.get_item(Key={"pk": "tv-library#episode#other-game", "sk": "arrival"})["Item"]
        item["revision"] = "b" * 32
        db.put_item(Item=item)
        return result

    preview = json.loads(module.migrate(media, {"schemaVersion": 1, "apply": False}, {})["body"])
    monkeypatch.setattr(module, "inventory", inventory_then_change)
    response = module.migrate(media, {"schemaVersion": 1, "apply": True, "expectedInventoryHash": preview["inventoryHash"]}, {"sub": "fictional-migrator"})
    assert response["statusCode"] == 409
    assert "Item" not in db.get_item(Key=module.records.pointer(module.PREFIX, "other-game", "episode", "arrival"))
