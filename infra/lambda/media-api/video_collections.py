"""Ordered, private video collections; asset identities and review states stay unchanged."""

import base64
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from access_policy import authorized
import asset_library
import browse_index


def partition(game):
    return f"video-collections#{game}"


def decode(item):
    return json.loads(item["payload"]) if item else None


def is_video(asset):
    return asset.get("contentType", "").startswith("video/") or bool(
        re.search(r"\.(mp4|webm|mov|m4v|ogv)$", asset.get("name", ""), re.I)
    )


def members(media, game, keys):
    """At most fifty exact index reads; no source files or storage scans."""
    records, warnings = [], []
    db = browse_index.table()
    pending = {
        db.name: {
            "Keys": [{"pk": browse_index.partition(game, "all"), "sk": key} for key in keys],
            "ConsistentRead": True,
        }
    }
    found = {}
    resource = boto3.resource("dynamodb")
    for _ in range(4):
        result = resource.batch_get_item(RequestItems=pending)
        found.update({item["sk"]: item for item in result.get("Responses", {}).get(db.name, [])})
        pending = result.get("UnprocessedKeys", {})
        if not pending:
            break
    if pending:
        raise RuntimeError("Collection catalog reads are incomplete; please retry")
    for key in keys:
        item = found.get(key)
        asset = decode(item)
        if (
            not asset
            or asset.get("key") != key
            or not asset_library.valid_key(media, game, key)
            or not is_video(asset)
        ):
            warnings.append({"key": key, "reason": "Video unavailable in the current catalog"})
        else:
            records.append((asset, item["observed"]))
    return records, warnings


def save(media, body, claims):
    if not isinstance(body, dict) or set(body) != {
        "gameId",
        "id",
        "name",
        "description",
        "assetKeys",
        "expectedRevision",
        "operationId",
    }:
        raise ValueError(
            "Expected gameId, id, name, description, ordered assetKeys, expectedRevision and operationId"
        )
    game, identity = body["gameId"], body["id"]
    if not all(media._valid_slug(v) and len(v) <= 96 for v in (game, identity)):
        raise ValueError("Invalid game or collection identity")
    for field, maximum, minimum in (("name", 120, 1), ("description", 1000, 0)):
        value = body[field]
        if (
            not isinstance(value, str)
            or not minimum <= len(value.strip()) <= maximum
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError(f"Invalid collection {field}")
    keys = body["assetKeys"]
    if (
        not isinstance(keys, list)
        or not 1 <= len(keys) <= 50
        or not all(isinstance(k, str) and asset_library.valid_key(media, game, k) for k in keys)
        or len(set(keys)) != len(keys)
    ):
        raise ValueError("Choose 1–50 distinct same-game immutable video keys")
    operation, expected = body["operationId"], body["expectedRevision"]
    if (
        not isinstance(operation, str)
        or not re.fullmatch(r"[a-f0-9]{32}", operation)
        or expected is not None
        and (not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{32}", expected))
    ):
        raise ValueError("Invalid operation or expected revision")
    db = browse_index.table()
    pointer = {"pk": partition(game), "sk": identity}
    opkey = {"pk": f"video-collection-ops#{game}#{identity}", "sk": operation}
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    previous = db.get_item(Key=opkey, ConsistentRead=True).get("Item")
    if previous:
        if previous["fingerprint"] != fingerprint:
            return media._response(
                409, {"error": "Operation identity was used with different arguments"}
            )
        return media._response(
            200,
            {
                "collection": decode(db.get_item(Key=pointer, ConsistentRead=True).get("Item")),
                "operation": decode(previous),
                "replayed": True,
            },
        )
    assets, warnings = members(media, game, keys)
    if warnings:
        raise ValueError(
            "Every collection member must be an indexed video; unavailable files cannot be guessed"
        )
    record = {
        "schemaVersion": 1,
        "entityType": "VideoCollection",
        "gameId": game,
        "id": identity,
        "name": body["name"].strip(),
        "description": body["description"].strip(),
        "assetKeys": keys,
        "revision": uuid.uuid4().hex,
        "previousRevision": expected,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "updatedBy": claims["sub"],
    }
    payload = json.dumps(record, separators=(",", ":"))
    serializer = TypeSerializer()

    def encode(value):
        return {k: serializer.serialize(v) for k, v in value.items()}

    put = {
        "TableName": db.name,
        "Item": encode({**pointer, "revision": record["revision"], "payload": payload}),
        "ConditionExpression": "revision = :expected" if expected else "attribute_not_exists(pk)",
    }
    if expected:
        put["ExpressionAttributeValues"] = encode({":expected": expected})
    operations = [
        {"Put": put},
        {
            "Put": {
                "TableName": db.name,
                "Item": encode(
                    {
                        "pk": f"video-collection-history#{game}#{identity}",
                        "sk": record["revision"],
                        "payload": payload,
                    }
                ),
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
        {
            "Put": {
                "TableName": db.name,
                "Item": encode({**opkey, "fingerprint": fingerprint, "payload": payload}),
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
    ]
    for asset, observed in assets:
        operations.append(
            {
                "ConditionCheck": {
                    "TableName": db.name,
                    "Key": encode({"pk": browse_index.partition(game, "all"), "sk": asset["key"]}),
                    "ConditionExpression": "observed = :observed",
                    "ExpressionAttributeValues": encode({":observed": observed}),
                }
            }
        )
    try:
        boto3.client("dynamodb").transact_write_items(TransactItems=operations)
    except ClientError as error:
        if error.response["Error"]["Code"] == "TransactionCanceledException":
            return media._response(
                409, {"error": "Collection or source changed; reload before retrying"}
            )
        raise
    return media._response(200, {"collection": record})


def handle(event, media):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "MODEL_PUBLISHERS"):
        return media._response(403, {"error": "Video library sign-in required"})
    try:
        if event["routeKey"] == "POST /video-collections":
            return save(media, json.loads(event.get("body") or "{}"), claims)
        game = media._query(event, "gameId")
        if not media._valid_slug(game) or len(game) > 96:
            raise ValueError("Invalid game")
        identity = media._query(event, "id")
        if identity:
            if not media._valid_slug(identity) or len(identity) > 96:
                raise ValueError("Invalid collection identity")
            record = decode(
                browse_index.table()
                .get_item(Key={"pk": partition(game), "sk": identity}, ConsistentRead=True)
                .get("Item")
            )
            if not record:
                return media._response(404, {"error": "Collection not found"})
            metadata_only = media._query(event, "metadataOnly")
            if metadata_only not in (None, "true"):
                raise ValueError("Invalid metadata projection option")
            if metadata_only == "true":
                return media._response(200, {"collection": record})
            assets, warnings = members(media, game, record["assetKeys"])
            return media._response(
                200, {"collection": record, "assets": [a for a, _ in assets], "warnings": warnings}
            )
        args = {
            "KeyConditionExpression": Key("pk").eq(partition(game)),
            "Limit": 100,
            "ConsistentRead": True,
        }
        cursor = media._query(event, "cursor")
        if cursor:
            key = json.loads(base64.urlsafe_b64decode(cursor))
            if (
                not isinstance(key, dict)
                or set(key) != {"pk", "sk"}
                or key["pk"] != partition(game)
                or not isinstance(key["sk"], str)
            ):
                raise ValueError("Invalid collection cursor")
            args["ExclusiveStartKey"] = key
        result = browse_index.table().query(**args)
        following = result.get("LastEvaluatedKey")
        return media._response(
            200,
            {
                "collections": [decode(item) for item in result.get("Items", [])],
                "cursor": base64.urlsafe_b64encode(json.dumps(following).encode()).decode()
                if following
                else None,
            },
        )
    except (ValueError, KeyError, TypeError):
        return media._response(
            400,
            {
                "error": "Invalid collection or source. Check the game, immutable members and expected revision."
            },
        )
