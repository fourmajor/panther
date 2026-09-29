"""Revisioned metadata-only records with exact retry and immutable history contracts."""

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


def encode(value):
    serializer = TypeSerializer()
    return {k: serializer.serialize(v) for k, v in value.items()}


def decode(item):
    return json.loads(item["payload"]) if item else None


def revision(value, *, optional=False):
    if optional and value is None:
        return value
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Invalid revision or operation identity")
    return value


def pointer(prefix, game, kind, identity):
    return {"pk": f"{prefix}#{kind}#{game}", "sk": identity}


def replay(db, prefix, game, kind, identity, body, media):
    fingerprint = hashlib.sha256(
        json.dumps(body, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    previous = db.get_item(
        Key={"pk": f"{prefix}-ops#{kind}#{game}#{identity}", "sk": body["operationId"]},
        ConsistentRead=True,
    ).get("Item")
    if not previous:
        return fingerprint, None
    if previous["fingerprint"] != fingerprint:
        return fingerprint, media._response(
            409, {"error": "Operation identity reused with different arguments"}
        )
    current = decode(
        db.get_item(Key=pointer(prefix, game, kind, identity), ConsistentRead=True).get("Item")
    )
    return fingerprint, media._response(
        200, {"record": current, "operationRevision": previous["revision"], "replayed": True}
    )


def commit(db, prefix, kind, record, body, claims, fingerprint, guards, media):
    game, identity = record["gameId"], record["id"]
    expected = body["expectedRevision"]
    record.update(
        revision=uuid.uuid4().hex,
        previousRevision=expected,
        updatedAt=datetime.now(timezone.utc).isoformat(),
        updatedBy=claims["sub"],
        reason=body["reason"].strip(),
    )
    payload = json.dumps(record, separators=(",", ":"), allow_nan=False)
    if len(payload.encode()) > 64_000 or len(guards) > 97:
        raise ValueError("Organization exceeds the bounded record or transaction limit")
    put = {
        "TableName": db.name,
        "Item": encode(
            {
                **pointer(prefix, game, kind, identity),
                "revision": record["revision"],
                "payload": payload,
            }
        ),
        "ConditionExpression": "revision = :r" if expected else "attribute_not_exists(pk)",
    }
    if expected:
        put["ExpressionAttributeValues"] = encode({":r": expected})
    operations = [
        {"Put": put},
        {
            "Put": {
                "TableName": db.name,
                "Item": encode(
                    {
                        "pk": f"{prefix}-history#{kind}#{game}#{identity}",
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
                "Item": encode(
                    {
                        "pk": f"{prefix}-ops#{kind}#{game}#{identity}",
                        "sk": body["operationId"],
                        "fingerprint": fingerprint,
                        "revision": record["revision"],
                    }
                ),
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
        *guards,
    ]
    try:
        boto3.client("dynamodb").transact_write_items(TransactItems=operations)
    except ClientError as error:
        if error.response["Error"]["Code"] == "TransactionCanceledException":
            return media._response(
                409, {"error": "Organization or source changed; reload before retrying"}
            )
        raise
    return media._response(200, {"record": record})


def read(db, prefix, game, kind, q, media):
    identity, historical = q.get("id"), q.get("revision")
    if identity:
        if not media._valid_slug(identity) or len(identity) > 96:
            raise ValueError("Invalid organization identity")
        if historical:
            revision(historical)
        key = {
            "pk": f"{prefix}-history#{kind}#{game}#{identity}"
            if historical
            else f"{prefix}#{kind}#{game}",
            "sk": historical or identity,
        }
        record = decode(db.get_item(Key=key, ConsistentRead=True).get("Item"))
        return (
            media._response(200, {"record": record})
            if record
            else media._response(404, {"error": "Organization not found"})
        )
    if historical:
        raise ValueError("Revision requires an identity")
    pk = f"{prefix}#{kind}#{game}"
    args = {"KeyConditionExpression": Key("pk").eq(pk), "ConsistentRead": True, "Limit": 100}
    if q.get("cursor"):
        key = json.loads(base64.urlsafe_b64decode(q["cursor"]))
        if (
            not isinstance(key, dict)
            or set(key) != {"pk", "sk"}
            or key["pk"] != pk
            or not isinstance(key["sk"], str)
        ):
            raise ValueError("Invalid organization cursor")
        args["ExclusiveStartKey"] = key
    result = db.query(**args)
    following = result.get("LastEvaluatedKey")
    return media._response(
        200,
        {
            "records": [decode(i) for i in result.get("Items", [])],
            "cursor": base64.urlsafe_b64encode(json.dumps(following).encode()).decode()
            if following
            else None,
        },
    )
