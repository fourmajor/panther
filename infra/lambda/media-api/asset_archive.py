"""Versioned logical archives and transactional current-reference guards.

Archive bytes and historical documents remain readable. Every current selection and new
processing pin bumps the shared epoch in its own commit, preventing phantom references.
"""

import base64
import hashlib
import json
import logging
import os
import re
import time

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError
from access_policy import authorized

TERMINAL = {
    "DONE",
    "PUBLISHED",
    "FAILED",
    "CANCELLED",
    "COMPLETE",
    "NOVEL_READY",
    "VIDEO_READY",
    "READY_FOR_VIDEO_DISCUSSION",
    "EXPIRED",
    "SUPERSEDED",
    "CONFLICT",
}
LOGGER = logging.getLogger(__name__)
VERSION = 1


def encode(value):
    serializer = TypeSerializer()
    return {key: serializer.serialize(item) for key, item in value.items()}


def db():
    return boto3.resource("dynamodb").Table(os.environ["ASSET_BROWSE_TABLE"])


def archive_key(game, key):
    return {"pk": f"asset-archives-v1#{game}", "sk": key}


def epoch_key(game):
    return {"pk": f"asset-reference-epoch-v1#{game}", "sk": "current"}


def archived(game, key):
    return bool(db().get_item(Key=archive_key(game, key), ConsistentRead=True).get("Item"))


def reference_writes(game, owner, keys, active=None):
    """Compose with the owning entity/job transaction, never as a separate write."""
    table = db()
    values = [key for key in keys if key is not None]
    if any(
        not isinstance(key, str) or not key.startswith(f"games/{game}/assets/") for key in values
    ):
        raise ValueError("Current asset reference must belong to the same game")
    keys = sorted(set(values))
    if len(keys) > 90:
        raise ValueError("Too many current asset references")
    item = {
        "pk": f"asset-references-v1#{game}",
        "sk": owner,
        "keys": keys,
        "schemaVersion": VERSION,
    }
    if active:
        item["active"] = active
    operations = [
        {
            "Update": {
                "TableName": table.name,
                "Key": encode(epoch_key(game)),
                "UpdateExpression": "ADD revision :one",
                "ExpressionAttributeValues": encode({":one": 1}),
            }
        },
        {"Put": {"TableName": table.name, "Item": encode(item)}},
    ]
    operations += [
        {
            "ConditionCheck": {
                "TableName": table.name,
                "Key": encode(archive_key(game, key)),
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        }
        for key in keys
    ]
    return operations


def current_references(game, key):
    """Bounded same-game projection; current pointers only, never historical lineage."""
    table = db()
    items = []
    cursor = None
    for _ in range(10):
        args = {
            "KeyConditionExpression": Key("pk").eq(f"asset-references-v1#{game}"),
            "ConsistentRead": True,
            "Limit": 100,
        }
        if cursor:
            args["ExclusiveStartKey"] = cursor
        result = table.query(**args)
        items.extend(result.get("Items", []))
        cursor = result.get("LastEvaluatedKey")
        if not cursor:
            break
    if cursor:
        raise RuntimeError("Current asset references exceed bounded archive verification")
    for item in items:
        if key not in item.get("keys", []):
            continue
        active = item.get("active")
        if active:
            job = (
                boto3.resource("dynamodb")
                .Table(active["table"])
                .get_item(Key={"pk": active["pk"], "sk": active["sk"]}, ConsistentRead=True)
                .get("Item")
            )
            if job and job.get("status") in TERMINAL:
                continue
        return True
    return False


def archive(body, actor, media):
    if not isinstance(body, dict) or set(body) != {"gameId", "key", "sha256", "operationId"}:
        raise ValueError("Expected game, asset, checksum and operation identity")
    game, key, operation = body.get("gameId"), body.get("key"), body.get("operationId")
    if (
        not media._valid_slug(game)
        or len(game) > 96
        or not isinstance(key, str)
        or not key.startswith(f"games/{game}/assets/")
        or not media._valid_key(key)
        or not re.fullmatch(r"[a-f0-9]{32}", operation or "")
    ):
        raise ValueError("Invalid archive request")
    try:
        expected = base64.b64decode(body.get("sha256", ""), validate=True)
    except (ValueError, TypeError):
        raise ValueError("Invalid asset checksum") from None
    if len(expected) != 32:
        raise ValueError("Invalid asset checksum")
    table = db()
    ready = table.get_item(
        Key={"pk": "asset-archives-v1#catalog", "sk": "ready"}, ConsistentRead=True
    ).get("Item")
    if not ready:
        raise RuntimeError("Asset archive migration must be verified before deletion is enabled")
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    audit_key = {"pk": f"asset-archive-ops-v1#{game}", "sk": operation}
    previous = table.get_item(Key=audit_key, ConsistentRead=True).get("Item")
    if previous:
        if previous["fingerprint"] != fingerprint:
            raise ValueError("Operation identity reused with different arguments")
        return {"deleted": True, "key": key, "replayed": True}
    epoch = (
        table.get_item(Key=epoch_key(game), ConsistentRead=True).get("Item", {}).get("revision", 0)
    )
    if current_references(game, key):
        raise LookupError(
            "This asset is selected or is being processed. Remove that selection before deleting it."
        )
    head = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=key, ChecksumMode="ENABLED")
    kind = head.get("Metadata", {}).get("kind", "")
    content_type = head.get("ContentType", "")
    if (
        content_type.startswith("audio/")
        or key.lower().endswith((".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".aac"))
        or "recording" in kind
        or "transcri" in kind
        or kind in {"transcript", "raw-transcript", "corrected-transcript", "edited-transcript"}
    ):
        raise LookupError(
            "Recording and transcript deletion is not available yet. Their processing inputs must remain in the current library."
        )
    if key.lower().endswith(".json") or content_type in {"application/json", "text/json"}:
        if head.get("ContentLength", 0) > 2 * 1024**2:
            raise LookupError("This JSON file is too large to safely classify for deletion.")
        response = media.s3.get_object(
            Bucket=media.BUCKET_NAME,
            Key=key,
            Range="bytes=0-2097152",
            **({"VersionId": head["VersionId"]} if head.get("VersionId") else {}),
        )
        with response["Body"] as stream:
            raw = stream.read(2 * 1024**2 + 1)
        if len(raw) > 2 * 1024**2:
            raise LookupError("This JSON file is too large to safely classify for deletion.")
        try:
            document = json.loads(raw)
        except (ValueError, UnicodeError):
            raise LookupError(
                "This JSON file could not be classified. Correct its metadata before deleting it."
            ) from None
        if isinstance(document, dict):
            transcript = (
                document.get("payload", {}).get("transcript")
                if isinstance(document.get("payload"), dict)
                else None
            )
            if (
                document.get("entityType")
                in {
                    "Recording",
                    "BrowserRecording",
                    "RecordingChunkSet",
                    "RecordingPlayback",
                    "PlayerTranscript",
                }
                or document.get("stage")
                in {"raw-transcript", "corrected-transcript", "edited-transcript"}
                or isinstance(transcript, dict)
                and transcript.get("entityType") == "PlayerTranscript"
            ):
                raise LookupError(
                    "Recording and transcript deletion is not available yet. Their processing inputs must remain in the current library."
                )
    observed = head.get("ChecksumSHA256") or head.get("Metadata", {}).get("sha256")
    if observed != body["sha256"]:
        raise LookupError("The asset changed. Review it before deleting.")
    record = {
        **archive_key(game, key),
        "schemaVersion": VERSION,
        "key": key,
        "sha256": body["sha256"],
        "actor": actor,
        "archivedAt": int(time.time()),
        "operationId": operation,
    }
    update = {
        "TableName": table.name,
        "Key": encode(epoch_key(game)),
        "UpdateExpression": "SET revision = :next",
        "ConditionExpression": "revision = :old" if epoch else "attribute_not_exists(revision)",
        "ExpressionAttributeValues": encode(
            {":next": epoch + 1, **({":old": epoch} if epoch else {})}
        ),
    }
    operations = [
        {"Update": update},
        {
            "Put": {
                "TableName": table.name,
                "Item": encode(record),
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
        {
            "Put": {
                "TableName": table.name,
                "Item": encode({**audit_key, "fingerprint": fingerprint, "record": record}),
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
    ]
    import browse_index

    operations += [
        {
            "Delete": {
                "TableName": table.name,
                "Key": encode({"pk": browse_index.partition(game, section), "sk": key}),
            }
        }
        for section in browse_index.SECTIONS
    ]
    boto3.client("dynamodb").transact_write_items(TransactItems=operations)
    return {"deleted": True, "key": key}


def handler(event, _context):
    import index as media

    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "MODEL_PUBLISHERS"):
        return media._response(403, {"error": "Game editing access required"})
    try:
        return media._response(
            200, archive(json.loads(event.get("body") or "{}"), claims["sub"], media)
        )
    except ValueError as error:
        return media._response(400, {"error": str(error)})
    except LookupError as error:
        return media._response(409, {"error": str(error)})
    except RuntimeError:
        LOGGER.exception("Asset archive is unavailable")
        return media._response(503, {"error": "Asset deletion is temporarily unavailable."})
    except ClientError:
        return media._response(
            409, {"error": "The asset or its selections changed. Review before retrying."}
        )
