"""Private, revisioned story/book organization; manuscripts remain immutable evidence."""

import base64
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

import asset_library
import asset_metadata
import browse_index
from access_policy import authorized


def partition(game, kind):
    return f"novel-library#{kind}#{game}"


def decode(item):
    return json.loads(item["payload"]) if item else None


def text(value, maximum, *, empty=False):
    if not isinstance(value, str) or not (0 if empty else 1) <= len(value.strip()) <= maximum:
        raise ValueError("Invalid narrative text field")
    if any(ord(c) < 32 and c != "\n" for c in value):
        raise ValueError("Invalid control characters")
    return value.strip()


def slug(media, value):
    if not media._valid_slug(value) or len(value) > 96:
        raise ValueError("Invalid narrative identity")
    return value


def indexed(game, keys):
    """Bounded exact metadata reads, not source scans or a partial result."""
    if not keys:
        return {}
    db = browse_index.table()
    pending = {
        db.name: {
            "Keys": [{"pk": browse_index.partition(game, "all"), "sk": k} for k in keys],
            "ConsistentRead": True,
        }
    }
    found = {}
    for _ in range(20):
        result = boto3.resource("dynamodb").batch_get_item(RequestItems=pending)
        found.update({item["sk"]: item for item in result.get("Responses", {}).get(db.name, [])})
        pending = result.get("UnprocessedKeys", {})
        if not pending:
            break
    if pending or sum(len(i["payload"].encode()) for i in found.values()) > 4 * 1024**2:
        raise RuntimeError("Narrative source catalog read is incomplete or oversized; retry")
    return found


def save(media, body, claims, kind):
    common = {"gameId", "id", "title", "synopsis", "expectedRevision", "operationId", "reason"}
    additional = (
        {
            "storyId",
            "authorCredit",
            "coverAssetKey",
            "classification",
            "status",
            "order",
            "volumes",
            "relatedAssetKeys",
        }
        if kind == "book"
        else {"chapterKey", "status", "illustrations"}
        if kind == "illustration"
        else set()
    )
    if not isinstance(body, dict) or set(body) != common | additional:
        raise ValueError("Expected a complete guarded narrative envelope")
    game, identity = slug(media, body["gameId"]), slug(media, body["id"])
    catalog = boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"])
    if not catalog.get_item(Key={"pk": "GAMES", "sk": game}, ConsistentRead=True).get("Item"):
        raise ValueError("Register the game before organizing narratives")
    expected, operation = body["expectedRevision"], body["operationId"]
    if (
        not isinstance(operation, str)
        or not re.fullmatch(r"[a-f0-9]{32}", operation)
        or (
            expected is not None
            and (not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{32}", expected))
        )
    ):
        raise ValueError("Invalid revision or operation identity")
    record = {
        "schemaVersion": 1,
        "entityType": {
            "book": "NarrativeBook",
            "story": "NarrativeStory",
            "illustration": "ChapterIllustrations",
        }[kind],
        "gameId": game,
        "id": identity,
        "title": text(body["title"], 160),
        "synopsis": text(body["synopsis"], 3000, empty=True),
    }
    reason = text(body["reason"], 500)
    db = browse_index.table()
    pointer = {"pk": partition(game, kind), "sk": identity}
    opkey = {"pk": f"novel-library-ops#{kind}#{game}#{identity}", "sk": operation}
    fingerprint = hashlib.sha256(
        json.dumps(body, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    previous = db.get_item(Key=opkey, ConsistentRead=True).get("Item")
    if previous:
        if previous["fingerprint"] != fingerprint:
            return media._response(
                409, {"error": "Operation identity reused with different arguments"}
            )
        return media._response(
            200,
            {
                "record": decode(db.get_item(Key=pointer, ConsistentRead=True).get("Item")),
                "operationRevision": previous["revision"],
                "replayed": True,
            },
        )
    serializer = TypeSerializer()

    def encode(value):
        return {k: serializer.serialize(v) for k, v in value.items()}

    guards = []
    if kind == "illustration":
        chapter_key = body["chapterKey"]
        entries = body["illustrations"]
        if (
            body["status"] not in {"draft", "approved"}
            or not isinstance(entries, list)
            or len(entries) > 12
        ):
            raise ValueError("Invalid illustration selection")
        normalized = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "assetKey",
                "placement",
                "altText",
                "caption",
            }:
                raise ValueError("Expected explicit illustration descriptions and placement")
            if entry["placement"] not in {"before-chapter", "after-chapter"}:
                raise ValueError("Illustrations belong outside the unchanged manuscript")
            normalized.append(
                {
                    "assetKey": entry["assetKey"],
                    "placement": entry["placement"],
                    "altText": text(entry["altText"], 1000),
                    "caption": text(entry["caption"], 1000, empty=True),
                }
            )
        keys = [chapter_key, *[entry["assetKey"] for entry in normalized]]
        if any(
            not isinstance(k, str)
            or not asset_library.valid_key(media, game, k)
            or not k.startswith(f"games/{game}/")
            for k in keys
        ) or len(set(keys)) != len(keys):
            raise ValueError("Choose distinct same-game assets")
        sources = indexed(game, keys)
        assets = {k: json.loads(v["payload"]) for k, v in sources.items()}
        if any(k not in assets or assets[k].get("key") != k for k in keys):
            raise ValueError("Illustration sources must exist in the catalog")
        summary = assets[chapter_key].get("novel", {})
        if (
            summary.get("state") != "available"
            or summary.get("id") != identity
            or summary.get("assetKey") != chapter_key
        ):
            raise ValueError("Pin the exact completed chapter edition")
        import novel

        if summary.get("authorship") == "human":
            import manual_chapters

            authored = manual_chapters.record(game, identity)
            if not authored or authored["assetKey"] != chapter_key:
                raise ValueError("Authored chapter is not committed")
            guards.append(
                {
                    "ConditionCheck": {
                        "TableName": db.name,
                        "Key": encode(manual_chapters.key(game, identity)),
                        "ConditionExpression": "#s = :done AND payload = :p",
                        "ExpressionAttributeNames": {"#s": "status"},
                        "ExpressionAttributeValues": encode(
                            {":done": "DONE", ":p": json.dumps(authored)}
                        ),
                    }
                }
            )
        else:
            committed = novel.committed_records([summary])
            task_key = {"pk": "TASKS", "sk": identity + ":novel-chapter"}
            task = committed.get(("TASKS", task_key["sk"]))
            job = committed.get(("RUNS", identity))
            if (
                not task
                or task.get("status") != "DONE"
                or task.get("output", {}).get("key") != chapter_key
                or not job
                or job.get("gameId") != game
                or job.get("sessionId") != summary.get("sessionId")
            ):
                raise ValueError("An unfinished or foreign chapter cannot be illustrated")
            guards.append(
                {
                    "ConditionCheck": {
                        "TableName": novel.jobs.table.name,
                        "Key": encode(task_key),
                        "ConditionExpression": "#s = :done AND #o = :output",
                        "ExpressionAttributeNames": {"#s": "status", "#o": "output"},
                        "ExpressionAttributeValues": encode(
                            {":done": "DONE", ":output": task["output"]}
                        ),
                    }
                }
            )
        for entry in normalized:
            asset = assets[entry["assetKey"]]
            if (
                asset.get("contentType")
                not in {"image/png", "image/jpeg", "image/webp", "image/avif"}
                or not 0 < asset.get("size", 0) <= 8 * 1024**2
                or asset_metadata.internal(asset["kind"])
                or asset.get("lineageWarning")
                or asset.get("metadata", {}).get("extra", {}).get("relationshipRole") != "finished"
            ):
                raise ValueError(
                    "Choose a finished browser-compatible image, not a workflow internal"
                )
        for key, source in sources.items():
            guards.append(
                {
                    "ConditionCheck": {
                        "TableName": db.name,
                        "Key": encode({"pk": browse_index.partition(game, "all"), "sk": key}),
                        "ConditionExpression": "observed = :observed",
                        "ExpressionAttributeValues": encode({":observed": source["observed"]}),
                    }
                }
            )
        record.update(chapterKey=chapter_key, status=body["status"], illustrations=normalized)
    if kind == "book":
        story_id = slug(media, body["storyId"])
        story_key = {"pk": partition(game, "story"), "sk": story_id}
        story = db.get_item(Key=story_key, ConsistentRead=True).get("Item")
        if not story:
            raise ValueError("Choose an existing same-game story")
        if body["classification"] not in {
            "grounded-adaptation",
            "creative-reimagining",
            "playful-derivative",
            "unclassified",
        }:
            raise ValueError("Invalid creative classification")
        if body["status"] not in {"draft", "approved"}:
            raise ValueError("Invalid private approval status")
        if type(body["order"]) is not int or not 0 <= body["order"] <= 10000:
            raise ValueError("Invalid book order")
        author = body["authorCredit"]
        if author is not None:
            author = text(author, 240)
        volumes = body["volumes"]
        if not isinstance(volumes, list) or not 1 <= len(volumes) <= 10:
            raise ValueError("Choose 1–10 explicitly ordered volumes")
        normalized, chapter_keys, ids = [], [], set()
        for volume in volumes:
            if not isinstance(volume, dict) or set(volume) != {"id", "title", "chapterKeys"}:
                raise ValueError("Invalid volume")
            volume_id = slug(media, volume["id"])
            if volume_id in ids:
                raise ValueError("Duplicate volume identity")
            ids.add(volume_id)
            keys = volume["chapterKeys"]
            if not isinstance(keys, list) or not keys:
                raise ValueError("Each volume needs explicitly selected immutable chapters")
            chapter_keys.extend(keys)
            normalized.append(
                {"id": volume_id, "title": text(volume["title"], 160), "chapterKeys": keys}
            )
        related = body["relatedAssetKeys"]
        if not isinstance(related, list) or len(related) > 10:
            raise ValueError("Choose at most ten related finished assets")
        cover = body["coverAssetKey"]
        all_keys = chapter_keys + related + ([cover] if cover is not None else [])
        if (
            not 1 <= len(chapter_keys) <= 40
            or len(set(chapter_keys)) != len(chapter_keys)
            or (
                not all(
                    isinstance(k, str) and asset_library.valid_key(media, game, k) for k in all_keys
                )
            )
            or len(set(related)) != len(related)
        ):
            raise ValueError("Choose at most forty distinct same-game chapter keys")
        sources = indexed(game, list(dict.fromkeys(all_keys)))
        assets = {key: decode(item) for key, item in sources.items()}
        if any(key not in assets or assets[key].get("key") != key for key in all_keys):
            raise ValueError("Every reference must exist in the current catalog")
        for key in related:
            asset = assets[key]
            if (
                asset_metadata.internal(asset["kind"])
                or asset.get("lineageWarning")
                or (
                    asset.get("metadata", {}).get("extra", {}).get("relationshipRole") != "finished"
                )
            ):
                raise ValueError("Related assets must be finished same-game media")
        if cover is not None and (
            assets[cover]["contentType"]
            not in {"image/png", "image/jpeg", "image/webp", "image/avif"}
            or not 0 < assets[cover]["size"] <= 8 * 1024**2
        ):
            raise ValueError("Choose an indexed browser-compatible cover image")
        summaries = [assets[k].get("novel", {}) for k in chapter_keys]
        if any(
            s.get("state") != "available" or s.get("assetKey") != k
            for s, k in zip(summaries, chapter_keys)
        ):
            raise ValueError("Every chapter needs a valid indexed manuscript")
        import novel

        completed = novel.committed_records(summaries)
        for summary, key in zip(summaries, chapter_keys):
            if summary.get("authorship") == "human":
                import manual_chapters

                authored = manual_chapters.record(game, summary["id"])
                if not authored or authored["assetKey"] != key:
                    raise ValueError("Authored chapter is not committed")
                guards.append(
                    {
                        "ConditionCheck": {
                            "TableName": db.name,
                            "Key": encode(manual_chapters.key(game, summary["id"])),
                            "ConditionExpression": "#s = :done AND payload = :p",
                            "ExpressionAttributeNames": {"#s": "status"},
                            "ExpressionAttributeValues": encode(
                                {":done": "DONE", ":p": json.dumps(authored)}
                            ),
                        }
                    }
                )
                continue
            task_key = {"pk": "TASKS", "sk": summary["id"] + ":novel-chapter"}
            task = completed.get((task_key["pk"], task_key["sk"]))
            job = completed.get(("RUNS", summary["id"]))
            if (
                not task
                or task.get("status") != "DONE"
                or task.get("output", {}).get("key") != key
                or (
                    not job
                    or job.get("gameId") != game
                    or job.get("sessionId") != summary["sessionId"]
                )
            ):
                raise ValueError("An unfinished or foreign chapter cannot be selected")
            guards.append(
                {
                    "ConditionCheck": {
                        "TableName": novel.jobs.table.name,
                        "Key": encode(task_key),
                        "ConditionExpression": "#s = :done AND #o = :output",
                        "ExpressionAttributeNames": {"#s": "status", "#o": "output"},
                        "ExpressionAttributeValues": encode(
                            {":done": "DONE", ":output": task["output"]}
                        ),
                    }
                }
            )
        for key, source in sources.items():
            guards.append(
                {
                    "ConditionCheck": {
                        "TableName": db.name,
                        "Key": encode({"pk": browse_index.partition(game, "all"), "sk": key}),
                        "ConditionExpression": "observed = :observed",
                        "ExpressionAttributeValues": encode({":observed": source["observed"]}),
                    }
                }
            )
        guards.append(
            {
                "ConditionCheck": {
                    "TableName": db.name,
                    "Key": encode(story_key),
                    "ConditionExpression": "revision = :r",
                    "ExpressionAttributeValues": encode({":r": story["revision"]}),
                }
            }
        )
        record.update(
            storyId=story_id,
            authorCredit=author,
            coverAssetKey=cover,
            classification=body["classification"],
            status=body["status"],
            order=body["order"],
            volumes=normalized,
            relatedAssetKeys=related,
        )
    record.update(
        revision=uuid.uuid4().hex,
        previousRevision=expected,
        updatedAt=datetime.now(timezone.utc).isoformat(),
        updatedBy=claims["sub"],
        reason=reason,
    )
    payload = json.dumps(record, separators=(",", ":"), allow_nan=False)
    if len(payload.encode()) > 50_000:
        raise ValueError("Narrative organization exceeds the metadata limit")
    put = {
        "TableName": db.name,
        "Item": encode({**pointer, "revision": record["revision"], "payload": payload}),
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
                        "pk": f"novel-library-history#{kind}#{game}#{identity}",
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
                    {**opkey, "fingerprint": fingerprint, "revision": record["revision"]}
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


def handler(event, _context):
    import index as media

    return handle(event, media)


def handle(event, media):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "MODEL_PUBLISHERS"):
        return media._response(403, {"error": "Novel library sign-in required"})
    kind = {
        "/novel-stories": "story",
        "/novel-books": "book",
        "/novel-illustrations": "illustration",
    }.get(event["routeKey"].split()[-1])
    if kind is None:
        return media._response(404, {"error": "Narrative route not found"})
    try:
        if event["routeKey"].startswith("POST "):
            return save(media, json.loads(event.get("body") or "{}"), claims, kind)
        q = event.get("queryStringParameters") or {}
        game = slug(media, q.get("gameId"))
        identity, revision = q.get("id"), q.get("revision")
        if identity:
            slug(media, identity)
            if revision and not re.fullmatch(r"[a-f0-9]{32}", revision):
                raise ValueError("Invalid revision")
            key = {
                "pk": f"novel-library-history#{kind}#{game}#{identity}"
                if revision
                else partition(game, kind),
                "sk": revision or identity,
            }
            record = decode(browse_index.table().get_item(Key=key, ConsistentRead=True).get("Item"))
            return (
                media._response(200, {"record": record})
                if record
                else media._response(404, {"error": "Narrative not found"})
            )
        if revision:
            raise ValueError("Revision needs an identity")
        pk = partition(game, kind)
        args = {"KeyConditionExpression": Key("pk").eq(pk), "ConsistentRead": True, "Limit": 100}
        if q.get("cursor"):
            key = json.loads(base64.urlsafe_b64decode(q["cursor"]))
            if (
                not isinstance(key, dict)
                or set(key) != {"pk", "sk"}
                or key["pk"] != pk
                or not isinstance(key["sk"], str)
            ):
                raise ValueError("Invalid narrative cursor")
            args["ExclusiveStartKey"] = key
        result = browse_index.table().query(**args)
        cursor = result.get("LastEvaluatedKey")
        return media._response(
            200,
            {
                "records": [decode(i) for i in result.get("Items", [])],
                "cursor": base64.urlsafe_b64encode(json.dumps(cursor).encode()).decode()
                if cursor
                else None,
            },
        )
    except RuntimeError as error:
        return media._response(503, {"error": str(error)})
    except (ValueError, TypeError, KeyError, AttributeError):
        return media._response(
            400,
            {
                "error": "Invalid narrative envelope or source; check explicit same-game references and revision"
            },
        )
    except ClientError:
        return media._response(
            503, {"error": "Novel library is temporarily unavailable; retry the exact operation"}
        )
