"""Guarded game facts and optional, versioned description annotations."""

import hashlib
import json
import uuid
from datetime import datetime, timezone

import boto3


def description(catalog, game_id):
    record = catalog.read(f"GAME#{game_id}", "DESCRIPTION")
    return {
        "description": record["description"] if record else None,
        "descriptionRevision": record["revision"] if record else None,
    }


def save(catalog, body, actor):
    fields = {
        "gameId",
        "name",
        "ruleset",
        "description",
        "expectedName",
        "expectedRuleset",
        "expectedDescriptionRevision",
        "operationId",
    }
    if not isinstance(body, dict) or set(body) != fields:
        raise ValueError("Expected guarded game settings")
    game_id = catalog.identifier(body["gameId"])
    operation = catalog.identifier(body["operationId"])
    new_name = catalog.name(body["name"])
    ruleset = body["ruleset"]
    if ruleset is not None:
        catalog.name(ruleset)
    text = body["description"]
    if text is not None and (
        not isinstance(text, str)
        or not 1 <= len(text) <= 2000
        or text != text.strip()
        or any(ord(c) < 32 and c not in "\n\t" for c in text)
    ):
        raise ValueError("Description must be plain text, at most 2000 characters")
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    history_key = f"SETTINGS#{operation}"
    history = catalog.read(f"GAME#{game_id}", history_key)
    if history:
        if history["fingerprint"] != fingerprint:
            return catalog.media._response(
                409, {"error": "Save operation changed; refresh before saving"}
            )
        return catalog.detail(game_id, can_edit=True)
    game = catalog.read("GAMES", game_id)
    if not game:
        return catalog.media._response(
            404, {"error": "This game needs a structured game header before editing"}
        )
    before = description(catalog, game_id)
    if (
        game["name"] != body["expectedName"]
        or game.get("ruleset") != body["expectedRuleset"]
        or before["descriptionRevision"] != body["expectedDescriptionRevision"]
    ):
        return catalog.media._response(
            409, {"error": "Game settings changed. Refresh before saving."}
        )
    now = datetime.now(timezone.utc).isoformat()
    revision = uuid.uuid4().hex
    current = {
        "pk": f"GAME#{game_id}",
        "sk": "DESCRIPTION",
        "entityType": "GameDescription",
        "schemaVersion": 1,
        "gameId": game_id,
        "description": text,
        "revision": revision,
        "updatedAt": now,
        "updatedBy": actor,
    }
    history = {
        "pk": f"GAME#{game_id}",
        "sk": history_key,
        "entityType": "GameSettingsChange",
        "schemaVersion": 1,
        "gameId": game_id,
        "fingerprint": fingerprint,
        "previousSettings": {"name": game["name"], "ruleset": game.get("ruleset"), **before},
        "settings": {
            "name": new_name,
            "ruleset": ruleset,
            "description": text,
            "descriptionRevision": revision,
        },
        "changedAt": now,
        "changedBy": actor,
    }

    def encode(value):
        return {k: catalog.serializer.serialize(v) for k, v in value.items()}

    rule_condition = (
        "#r = :oldRule"
        if body["expectedRuleset"] is not None
        else "(#r = :oldRule OR attribute_not_exists(#r))"
    )
    description_condition = (
        "#v = :old" if before["descriptionRevision"] else "attribute_not_exists(pk)"
    )
    put = {
        "TableName": catalog.table.name,
        "Item": encode(current),
        "ConditionExpression": description_condition,
    }
    if before["descriptionRevision"]:
        put.update(
            ExpressionAttributeNames={"#v": "revision"},
            ExpressionAttributeValues=encode({":old": before["descriptionRevision"]}),
        )
    boto3.client("dynamodb").transact_write_items(
        TransactItems=[
            {
                "Update": {
                    "TableName": catalog.table.name,
                    "Key": encode({"pk": "GAMES", "sk": game_id}),
                    "UpdateExpression": "SET #n = :newName, #r = :newRule, updatedAt = :now, updatedBy = :actor",
                    "ConditionExpression": f"attribute_exists(pk) AND #n = :oldName AND {rule_condition}",
                    "ExpressionAttributeNames": {"#n": "name", "#r": "ruleset"},
                    "ExpressionAttributeValues": encode(
                        {
                            ":oldName": body["expectedName"],
                            ":oldRule": body["expectedRuleset"],
                            ":newName": new_name,
                            ":newRule": ruleset,
                            ":now": now,
                            ":actor": actor,
                        }
                    ),
                }
            },
            {"Put": put},
            {
                "Put": {
                    "TableName": catalog.table.name,
                    "Item": encode(history),
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            },
        ]
    )
    return catalog.detail(game_id, can_edit=True)
