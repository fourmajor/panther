import importlib
import json
import struct
import uuid

import boto3
import pytest

from test_novel_library import library  # noqa: F401
from test_novel import novel  # noqa: F401
from test_editorial import editorial  # noqa: F401
from test_model_jobs import broker, unpack  # noqa: F401


@pytest.fixture
def looks(library, monkeypatch):  # noqa: F811
    monkeypatch.setenv("APPEARANCE_WRITES_ENABLED", "true")
    module = importlib.import_module("character_appearances")
    module.browse_index.table().put_item(
        Item={
            "pk": "character-looks-migration#test-game#example-character",
            "sk": "complete",
            "inventoryHash": "0" * 64,
        }
    )
    boto3.resource("dynamodb").Table("narrative-games").put_item(
        Item={
            "pk": "GAME#test-game",
            "sk": "CHARACTER#example-character",
            "schemaVersion": 2,
            "entityType": "Character",
            "id": "example-character",
            "gameId": "test-game",
            "name": "Example Character",
            "detailsRevision": uuid.uuid4().hex,
        }
    )
    keys = []
    for name, content_type in [("portrait.png", "image/png"), ("model.glb", "model/gltf-binary")]:
        key = f"games/test-game/assets/example-character/original/{name}"
        keys.append(key)
        library[1].jobs.media.s3.put_object(
            Bucket=library[1].jobs.media.BUCKET_NAME,
            Key=key,
            Body=(struct.pack("<4sII", b"glTF", 2, 100) + b"\0" * 88)
            if name.endswith(".glb")
            else b"p" * 100,
            ContentType=content_type,
        )
        asset = {
            "key": key,
            "size": 100,
            "contentType": content_type,
            "metadata": {"characterIds": ["example-character"], "extra": {}},
        }
        module.browse_index.table().put_item(
            Item={
                "pk": module.browse_index.partition("test-game", "all"),
                "sk": key,
                "observed": 1,
                "payload": json.dumps(asset),
            }
        )
    return module, library[1].jobs.media, keys


def call(looks, name, body=None, **q):
    routes = {
        "appearance": "/character-appearances",
        "association": "/character-appearance-assets",
        "selection": "/character-selections",
        "activation": "/character-appearance-current",
    }
    return looks[0].handle(
        {
            "routeKey": ("POST " if body else "GET ") + routes[name],
            "body": json.dumps(body) if body else None,
            "queryStringParameters": {
                "gameId": "test-game",
                "characterId": "example-character",
                **q,
            },
            "requestContext": {
                "authorizer": {
                    "jwt": {
                        "claims": {"sub": "fictional-owner", "cognito:username": "example-operator"}
                    }
                }
            },
        },
        looks[1],
    )


def envelope(**changes):
    return {
        "gameId": "test-game",
        "characterId": "example-character",
        "id": "ordinary",
        "expectedRevision": None,
        "operationId": uuid.uuid4().hex,
        "reason": "Synthetic appearance selection",
        **changes,
    }


def timing():
    return {"sessionId": None, "eventId": None, "date": None}


def appearance(**changes):
    body = envelope(
        name="Ordinary appearance",
        description="Synthetic physical state",
        state="unknown",
        developedFrom=None,
        story=timing(),
    )
    return {**body, **changes}


def selection(looks, **changes):
    body = envelope(
        id="selection-one",
        appearanceId="ordinary",
        portraitKey=looks[2][0],
        modelKey=looks[2][1],
        sourceKey=None,
        provenanceKey=None,
    )
    return {**body, **changes}


def associate(looks, aid="ordinary"):
    for key in looks[2]:
        body = envelope(id=looks[0].association_id(key), appearanceId=aid, assetKey=key)
        assert call(looks, "association", body)["statusCode"] == 200


def test_named_state_selection_activation_restore_and_history(looks):
    call(looks, "appearance", appearance())
    associate(looks)
    chosen = unpack(call(looks, "selection", selection(looks)))["record"]
    activation = envelope(
        id="current", appearanceId="ordinary", selectionId=chosen["id"], story=timing()
    )
    first = unpack(call(looks, "activation", activation))["record"]
    assert unpack(call(looks, "activation", activation))["replayed"]
    call(looks, "appearance", appearance(id="stone", state="temporary", developedFrom="ordinary"))
    associate(looks, "stone")
    stone = unpack(
        call(
            looks,
            "selection",
            selection(looks, id="stone-selection", appearanceId="stone", modelKey=None),
        )
    )["record"]
    second = unpack(
        call(
            looks,
            "activation",
            envelope(
                id="current",
                appearanceId="stone",
                selectionId=stone["id"],
                story=timing(),
                expectedRevision=first["revision"],
            ),
        )
    )["record"]
    restored = unpack(
        call(
            looks,
            "activation",
            {**activation, "expectedRevision": second["revision"], "operationId": uuid.uuid4().hex},
        )
    )["record"]
    assert (
        restored["selectionId"] == first["selectionId"]
        and restored["previousRevision"] == second["revision"]
    )
    assert (
        unpack(call(looks, "activation", id="current", revision=second["revision"]))["record"][
            "appearanceId"
        ]
        == "stone"
    )
    assert unpack(call(looks, "selection", id=stone["id"]))["record"]["modelKey"] is None
    assert call(looks, "activation", activation)["statusCode"] == 200
    assert (
        call(looks, "activation", {**activation, "reason": "Different arguments"})["statusCode"]
        == 409
    )


def test_unassociated_assets_wrong_appearance_and_stale_activation_fail(looks):
    call(looks, "appearance", appearance())
    assert call(looks, "selection", selection(looks))["statusCode"] == 400
    associate(looks)
    call(looks, "selection", selection(looks))
    call(looks, "appearance", appearance(id="alternate", state="alternate"))
    assert (
        call(
            looks,
            "activation",
            envelope(
                id="current", appearanceId="alternate", selectionId="selection-one", story=timing()
            ),
        )["statusCode"]
        == 400
    )
    body = envelope(
        id="current", appearanceId="ordinary", selectionId="selection-one", story=timing()
    )
    assert call(looks, "activation", body)["statusCode"] == 200
    assert call(looks, "activation", {**body, "operationId": uuid.uuid4().hex})["statusCode"] == 409


def test_artwork_selections_immutable_and_physical_parent_cannot_cycle(looks):
    first = unpack(call(looks, "appearance", appearance()))["record"]
    call(looks, "appearance", appearance(id="stone", developedFrom="ordinary"))
    assert (
        call(
            looks,
            "appearance",
            appearance(developedFrom="stone", expectedRevision=first["revision"]),
        )["statusCode"]
        == 400
    )
    associate(looks)
    selected = unpack(call(looks, "selection", selection(looks)))["record"]
    assert (
        call(looks, "selection", selection(looks, expectedRevision=selected["revision"]))[
            "statusCode"
        ]
        == 400
    )


def test_exact_character_identity_required_and_authorization(looks, monkeypatch):
    call(looks, "appearance", appearance())
    key = looks[2][0]
    db = looks[0].browse_index.table()
    pk = looks[0].browse_index.partition("test-game", "all")
    item = db.get_item(Key={"pk": pk, "sk": key})["Item"]
    asset = json.loads(item["payload"])
    asset["metadata"]["characterIds"] = ["another-character"]
    db.put_item(Item={**item, "payload": json.dumps(asset)})
    assert (
        call(
            looks,
            "association",
            envelope(id=looks[0].association_id(key), appearanceId="ordinary", assetKey=key),
        )["statusCode"]
        == 400
    )
    monkeypatch.setenv("MODEL_PUBLISHERS", "")
    assert call(looks, "appearance", appearance(id="another"))["statusCode"] == 403
    assert call(looks, "appearance")["statusCode"] == 200


def test_selection_pins_descriptor_revision_and_missing_sources_block_promotion(looks):
    parent = unpack(call(looks, "appearance", appearance()))["record"]
    associate(looks)
    call(looks, "selection", selection(looks))
    call(
        looks,
        "appearance",
        {**appearance(), "name": "Revised description", "expectedRevision": parent["revision"]},
    )
    _, pinned, pair, _ = looks[0].resolve(
        "test-game", "example-character", "ordinary", "selection-one"
    )
    assert (
        pinned["name"] == "Ordinary appearance" and pair["appearanceRevision"] == parent["revision"]
    )
    key = looks[2][1]
    looks[0].browse_index.table().delete_item(
        Key={"pk": looks[0].browse_index.partition("test-game", "all"), "sk": key}
    )
    assert (
        call(
            looks,
            "activation",
            envelope(
                id="current", appearanceId="ordinary", selectionId="selection-one", story=timing()
            ),
        )["statusCode"]
        == 400
    )
    assert unpack(call(looks, "selection", id="selection-one"))["record"]["modelKey"] == key


def test_modern_publication_is_pairwise_idempotent_and_keeps_activation_kind_distinct(looks):
    call(looks, "appearance", appearance())
    associate(looks)
    call(looks, "selection", selection(looks))
    active = unpack(
        call(
            looks,
            "activation",
            envelope(
                id="current", appearanceId="ordinary", selectionId="selection-one", story=timing()
            ),
        )
    )["record"]
    claims = {"sub": "fictional-owner", "cognito:username": "example-operator"}
    body = {
        "gameId": "test-game",
        "characterId": "example-character",
        "expectedRevision": active["revision"],
        "portraitKey": looks[2][0],
        "reason": "Select a synthetic artistic revision",
    }
    event = {
        "body": json.dumps(body),
        "requestContext": {"authorizer": {"jwt": {"claims": claims}}},
    }
    first = unpack(looks[0].publish(looks[1], event, "portrait"))
    replay = unpack(looks[0].publish(looks[1], event, "portrait"))
    assert replay["replayed"] and replay["operationRevision"] == first["revision"]
    _, _, selected, current = looks[0].resolve("test-game", "example-character")
    assert selected["modelKey"] == looks[2][1] and current["activationKind"] == "artwork-selection"
    assert current["previousAppearanceId"] == "ordinary"
    assert (
        looks[0].publish(
            looks[1],
            {**event, "body": json.dumps({**body, "reason": "Changed request"})},
            "portrait",
        )["statusCode"]
        == 409
    )


def test_staging_flag_fails_closed_without_mutation(looks, monkeypatch):
    monkeypatch.delenv("APPEARANCE_WRITES_ENABLED")
    monkeypatch.setenv("ASSET_MIGRATORS", "example-operator")
    before = looks[0].browse_index.table().scan()["Items"]
    assert call(looks, "appearance", appearance())["statusCode"] == 503
    for operation in ("apply", "finalize"):
        result = looks[0].handle(
            {
                "routeKey": f"POST /character-appearance-migration/{operation}",
                "body": "{}",
                "requestContext": {
                    "authorizer": {
                        "jwt": {
                            "claims": {
                                "sub": "fictional-owner",
                                "cognito:username": "example-operator",
                            }
                        }
                    }
                },
            },
            looks[1],
        )
        assert result["statusCode"] == 503
    assert looks[0].browse_index.table().scan()["Items"] == before
    assert call(looks, "appearance")["statusCode"] == 200


def test_historical_view_signs_only_exact_selected_pair_and_no_source_history_scan(
    looks, monkeypatch
):
    from unittest.mock import Mock

    call(looks, "appearance", appearance())
    associate(looks)
    call(looks, "selection", selection(looks))
    call(looks, "selection", selection(looks, id="portrait-only", modelKey=None))
    signer = Mock(side_effect=lambda key: f"https://example.invalid/{key}")
    monkeypatch.setattr(looks[1], "_signed_asset", signer)
    monkeypatch.setattr(
        looks[1].raw_s3, "list_objects_v2", Mock(side_effect=AssertionError("No S3 browsing"))
    )
    result = looks[0].view(looks[1], "test-game", "example-character", "ordinary", "portrait-only")
    assert result["poster"]["key"] == looks[2][0] and result["model"] is None
    assert signer.call_count == 1
    signer.reset_mock()
    result = looks[0].view(looks[1], "test-game", "example-character", "ordinary", "selection-one")
    assert result["poster"]["key"] == looks[2][0] and result["model"]["key"] == looks[2][1]
    assert signer.call_count == 2
    looks[0].browse_index.table().delete_item(
        Key={"pk": looks[0].browse_index.partition("test-game", "all"), "sk": looks[2][0]}
    )
    result = looks[0].view(looks[1], "test-game", "example-character", "ordinary", "selection-one")
    assert result["poster"] is None and result["model"] is None and result["warnings"]


def test_selection_rejects_bad_glb_and_rechecks_conflicting_character_at_promotion(looks):
    call(looks, "appearance", appearance())
    associate(looks)
    call(looks, "selection", selection(looks))
    looks[1].s3.put_object(Bucket=looks[1].BUCKET_NAME, Key=looks[2][1], Body=b"invalid" * 15)
    assert call(looks, "selection", selection(looks, id="bad-glb"))["statusCode"] == 400
    db = looks[0].browse_index.table()
    key = {"pk": looks[0].browse_index.partition("test-game", "all"), "sk": looks[2][0]}
    item = db.get_item(Key=key)["Item"]
    asset = json.loads(item["payload"])
    asset["metadata"]["characterIds"] = ["another-character"]
    db.put_item(Item={**item, "observed": 2, "payload": json.dumps(asset)})
    assert (
        call(
            looks,
            "activation",
            envelope(
                id="current", appearanceId="ordinary", selectionId="selection-one", story=timing()
            ),
        )["statusCode"]
        == 400
    )
