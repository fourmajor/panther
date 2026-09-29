"""Explicit canonical-reading selections, separate from immutable transcript evidence."""

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from access_policy import authorized
import asset_library
import browse_index


def body_record(item):
    return json.loads(item["payload"]) if item else None


def selection_key(game, session):
    return {"pk": f"transcript-selection#{game}", "sk": session}


def current(game, session):
    return body_record(browse_index.table().get_item(Key=selection_key(game, session), ConsistentRead=True).get("Item"))


def asset_record(media, game, session, key):
    if not isinstance(key, str) or not asset_library.valid_key(media, game, key):
        raise ValueError("Choose a same-game immutable transcript asset")
    item = browse_index.table().get_item(Key={"pk": browse_index.partition(game, "transcripts"),
        "sk": key}, ConsistentRead=True).get("Item")
    asset = body_record(item)
    if not asset or asset.get("kind") not in asset_library.TRANSCRIPT_KINDS or asset.get("metadata", {}).get("sessionId") != session:
        raise ValueError("Transcript is unavailable or belongs to another session")
    version = asset.get("metadata", {}).get("extra", {}).get("version")
    import asset_metadata
    asset_metadata.validate_version(version, key)
    if asset.get("transcript", {}).get("state") != "available":
        raise ValueError("A readable structured transcript is required for canonical selection")
    return asset


def select(media, body, claims):
    required = {"gameId", "sessionId", "key", "expectedRevision", "reason", "operationId"}
    if not isinstance(body, dict) or set(body) != required:
        raise ValueError("Expected gameId, sessionId, key, expectedRevision, reason and operationId")
    game, session = body["gameId"], body["sessionId"]
    for value in (game, session):
        if not media._valid_slug(value) or len(value) > 96:
            raise ValueError("Invalid game or session")
    reason, operation = body["reason"], body["operationId"]
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500 or any(ord(c) < 32 for c in reason):
        raise ValueError("Supply a short selection reason")
    if not isinstance(operation, str) or not re.fullmatch(r"[a-f0-9]{32}", operation):
        raise ValueError("Invalid operation identity")
    expected = body["expectedRevision"]
    if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{32}", expected)):
        raise ValueError("Invalid expected revision")
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    db = browse_index.table()
    operation_key = {"pk": f"transcript-selection-ops#{game}#{session}", "sk": operation}
    previous_operation = db.get_item(Key=operation_key, ConsistentRead=True).get("Item")
    if previous_operation:
        if previous_operation["fingerprint"] != fingerprint:
            return media._response(409, {"error": "Operation identity already used for another selection"})
        return media._response(200, {"selection": current(game, session),
                                    "operation": body_record(previous_operation), "replayed": True})
    asset = asset_record(media, game, session, body["key"])
    record = {"schemaVersion": 1, "entityType": "SessionTranscriptSelection", "gameId": game,
              "sessionId": session, "key": body["key"], "version": asset["metadata"]["extra"]["version"],
              "revision": uuid.uuid4().hex, "previousRevision": expected,
              "selectedAt": datetime.now(timezone.utc).isoformat(), "selectedBy": claims["sub"],
              "reason": reason.strip(), "operationId": operation,
              "notice": "Canonical reading selection is not human verification or a correction to source evidence."}
    payload = json.dumps(record, separators=(",", ":"))
    encode = TypeSerializer().serialize
    def attributes(value):
        return {k: encode(v) for k, v in value.items()}
    put = {"TableName": db.name, "Item": attributes({**selection_key(game, session),
            "payload": payload, "revision": record["revision"]}),
           "ConditionExpression": "revision = :expected" if expected else "attribute_not_exists(pk)"}
    if expected:
        put["ExpressionAttributeValues"] = attributes({":expected": expected})
    writes = [{"Put": put}, {"Put": {"TableName": db.name,
        "Item": attributes({"pk": f"transcript-selection-history#{game}#{session}",
                            "sk": record["revision"], "payload": payload}),
        "ConditionExpression": "attribute_not_exists(pk)"}}, {"Put": {"TableName": db.name,
        "Item": attributes({**operation_key, "fingerprint": fingerprint, "payload": payload}),
        "ConditionExpression": "attribute_not_exists(pk)"}}]
    # Protect the indexed session/kind/content revision read as well as the pointer.
    indexed = db.get_item(Key={"pk": browse_index.partition(game, "transcripts"), "sk": body["key"]}, ConsistentRead=True).get("Item")
    if not indexed or body_record(indexed) != asset:
        return media._response(409, {"error": "Transcript catalog changed; inspect before retrying"})
    writes.append({"ConditionCheck": {"TableName": db.name,
        "Key": attributes({"pk": browse_index.partition(game, "transcripts"), "sk": body["key"]}),
        "ConditionExpression": "observed = :observed", "ExpressionAttributeValues": attributes({":observed": indexed["observed"]})}})
    try:
        boto3.client("dynamodb").transact_write_items(TransactItems=writes)
    except ClientError as error:
        if error.response["Error"]["Code"] == "TransactionCanceledException":
            return media._response(409, {"error": "Selection or source changed; reload before retrying"})
        raise
    return media._response(200, {"selection": record})


def handle(event, media):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "MODEL_PUBLISHERS"):
        return media._response(403, {"error": "Transcript publisher sign-in required"})
    try:
        if event["routeKey"] == "POST /transcript-selection":
            return select(media, json.loads(event.get("body") or "{}"), claims)
        game, session = media._query(event, "gameId"), media._query(event, "sessionId")
        if not all(media._valid_slug(v) and len(v) <= 96 for v in (game, session)):
            raise ValueError("Invalid game or session")
        record = current(game, session)
        warning = None
        if record:
            try:
                asset_record(media, game, session, record["key"])
            except ValueError:
                warning = "Selected transcript is unavailable or its session metadata changed. No fallback has been selected."
        return media._response(200, {"selection": record, "warning": warning})
    except (ValueError, TypeError, KeyError):
        return media._response(400, {"error": "Invalid transcript selection or source. Reload the transcript and check the session/revision."})
