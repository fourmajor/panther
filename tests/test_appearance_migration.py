import base64
import importlib
import json
import uuid

import pytest

from test_character_appearances import looks  # noqa: F401
from test_novel_library import library  # noqa: F401
from test_novel import novel  # noqa: F401
from test_editorial import editorial  # noqa: F401
from test_model_jobs import broker  # noqa: F401


def source(looks):  # noqa: F811
    looks[0].browse_index.table().delete_item(
        Key={"pk": "character-looks-migration#test-game#example-character", "sk": "complete"}
    )
    profile = {
        "schemaVersion": 1,
        "gameId": "test-game",
        "id": "example-character",
        "name": "Example Character",
        "summary": "Synthetic character only.",
        "appearanceId": "original",
        "model": {"posterKey": looks[2][0], "webKey": looks[2][1]},
    }
    raw = json.dumps(profile, indent=2).encode()
    key = "games/test-game/characters/example-character/profile.json"
    looks[1].raw_s3.put_object(
        Bucket=looks[1].BUCKET_NAME, Key=key, Body=raw, ContentType="application/json"
    )
    return key, raw


def test_exact_sources_imported_idempotently_without_activation_and_duplicate_bytes_retained(looks):  # noqa: F811
    module = importlib.import_module("appearance_migration")
    key, raw = source(looks)
    plan, observed, _ = module.prepare(looks[1], "test-game", "example-character", key)
    assert raw == observed and plan["isCurrent"]
    assert module.apply(looks[1], plan, "fictional-owner")["status"] == "imported"
    assert module.apply(looks[1], plan, "fictional-owner")["status"] == "already-imported"
    historical = key.replace("profile.json", f"history/{plan['sourceSha256']}.json")
    looks[1].raw_s3.put_object(
        Bucket=looks[1].BUCKET_NAME, Key=historical, Body=raw, ContentType="application/json"
    )
    second, _, _ = module.prepare(looks[1], "test-game", "example-character", historical)
    assert module.apply(looks[1], second, "fictional-owner")["status"] == "imported"
    assert module.inventory(looks[1], "test-game", "example-character") == sorted([key, historical])
    db = looks[0].browse_index.table()
    from boto3.dynamodb.conditions import Key

    receipts = db.query(
        KeyConditionExpression=Key("pk").eq("character-looks-migration#test-game#example-character")
    )["Items"]
    assert len(receipts) == 2 and all(
        base64.b64decode(r["sourceRawBase64"]) == raw for r in receipts
    )
    assert not db.get_item(
        Key=looks[0].records.pointer(
            looks[0].PREFIX, "test-game", "activation#example-character", "current"
        )
    ).get("Item")
    _, appearance, selected, _ = looks[0].resolve(
        "test-game", "example-character", "original", plan["selectionId"]
    )
    assert appearance["state"] == "unknown" and all(v is None for v in appearance["story"].values())
    assert selected["portraitKey"] == looks[2][0]


def test_changed_source_foreign_identity_and_missing_selected_asset_are_blockers(looks):  # noqa: F811
    module = importlib.import_module("appearance_migration")
    key, raw = source(looks)
    plan, _, _ = module.prepare(looks[1], "test-game", "example-character", key)
    looks[1].raw_s3.put_object(
        Bucket=looks[1].BUCKET_NAME, Key=key, Body=raw + b" ", ContentType="application/json"
    )
    with pytest.raises(ValueError, match="changed"):
        module.apply(looks[1], plan, "fictional-owner")
    with pytest.raises(ValueError, match="exact legacy"):
        module.prepare(looks[1], "another-game", "example-character", key)
    db = looks[0].browse_index.table()
    db.delete_item(
        Key={"pk": looks[0].browse_index.partition("test-game", "all"), "sk": looks[2][1]}
    )
    with pytest.raises(ValueError, match="unavailable"):
        module.prepare(looks[1], "test-game", "example-character", key)


def test_activation_requires_every_source_and_seal_preserves_later_selections(looks):  # noqa: F811
    module = importlib.import_module("appearance_migration")
    key, raw = source(looks)
    plan, _, _ = module.prepare(looks[1], "test-game", "example-character", key)
    with pytest.raises(ValueError, match="Every retained"):
        module.verification(looks[1], "test-game", "example-character")
    module.apply(looks[1], plan, "fictional-owner")
    proof = module.verification(looks[1], "test-game", "example-character")
    claims = {"sub": "fictional-owner", "cognito:username": "example-operator"}
    result = module.finalize(looks[1], proof, uuid.uuid4().hex, claims)
    assert result["statusCode"] == 200
    _, _, selected, active = looks[0].resolve("test-game", "example-character")
    assert (
        selected["id"] == plan["selectionId"]
        and active["migrationInventoryHash"] == proof["inventoryHash"]
    )
    assert (
        json.loads(module.finalize(looks[1], proof, uuid.uuid4().hex, claims)["body"])["status"]
        == "already-complete"
    )
    looks[1].raw_s3.put_object(
        Bucket=looks[1].BUCKET_NAME, Key=key, Body=raw + b" ", ContentType="application/json"
    )
    with pytest.raises(ValueError, match="changed after import"):
        module.verification(looks[1], "test-game", "example-character")


def test_roster_only_character_migration_does_not_invent_artwork(looks):  # noqa: F811
    looks[0].browse_index.table().delete_item(
        Key={"pk": "character-looks-migration#test-game#example-character", "sk": "complete"}
    )
    module = importlib.import_module("appearance_migration")
    proof = module.verification(looks[1], "test-game", "example-character")
    assert proof["sourceCount"] == 0 and proof["currentSelection"] is None
    result = module.finalize(looks[1], proof, uuid.uuid4().hex, {"sub": "fictional-owner"})
    assert json.loads(result["body"])["status"] == "complete-without-artwork"
