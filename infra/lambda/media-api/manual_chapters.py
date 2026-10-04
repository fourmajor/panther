"""Human-authored, immutable chapters. Never impersonate an editorial workflow."""

import base64
import hashlib
import json
import os
import re
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

import asset_library
import asset_metadata
import browse_index
from access_policy import authorized
from novel_library import indexed, text


def key(game, identity):
    return {"pk": f"novel-library#chapter#{game}", "sk": identity}


def record(game, identity):
    item = browse_index.table().get_item(Key=key(game, identity), ConsistentRead=True).get("Item")
    return json.loads(item["payload"]) if item and item.get("status") == "DONE" else None


def validate_document(doc, game):
    if (
        not isinstance(doc, dict)
        or type(doc.get("schemaVersion")) is not int
        or doc.get("schemaVersion") != 1
        or doc.get("entityType") != "UserChapter"
        or doc.get("gameId") != game
        or not re.fullmatch(r"[a-f0-9]{64}", doc.get("chapterId", ""))
        or not re.fullmatch(r"[a-f0-9]{64}", doc.get("seriesId", ""))
    ):
        raise ValueError("Invalid authored chapter")
    text(doc["title"], 160)
    text(doc["markdown"], 100000)
    if type(doc.get("version")) is not int or not 1 <= doc["version"] <= 10000:
        raise ValueError("Invalid chapter version")
    if not isinstance(doc.get("sourceKeys"), list) or len(doc["sourceKeys"]) > 20:
        raise ValueError("Invalid chapter references")


def summary(doc, asset):
    validate_document(doc, asset["key"].split("/")[1])
    return {
        "schemaVersion": 1,
        "state": "available",
        "authorship": "human",
        "id": doc["chapterId"],
        "sessionId": "chapter-" + doc["seriesId"][:24],
        "title": doc["title"],
        "publicationStatus": "human-authored",
        "reviewStatus": "not-reviewed",
        "assetKey": asset["key"],
        "publishedAt": asset["lastModified"],
        "category": "authored-chapter",
    }


def read(game, identity, media):
    saved = record(game, identity)
    if not saved:
        return None
    reply = media.s3.get_object(Bucket=media.BUCKET_NAME, Key=saved["assetKey"])
    raw = reply["Body"].read(130001)
    if len(raw) > 130000 or hashlib.sha256(raw).hexdigest() != saved["sha256"]:
        raise ValueError("Chapter does not match its immutable reference")
    doc = json.loads(raw)
    validate_document(doc, game)
    if doc["chapterId"] != identity:
        raise ValueError("Chapter identity mismatch")
    return {
        "id": identity,
        "gameId": game,
        "sessionId": "chapter-" + doc["seriesId"][:24],
        "title": doc["title"],
        "markdown": doc["markdown"],
        "createdAt": saved["createdAt"],
        "publishedAt": saved["createdAt"],
        "publicationStatus": "human-authored",
        "reviewStatus": "not-reviewed",
        "notice": "",
        "readerReferences": None,
        "details": {
            "review": {},
            "revisionHistory": [],
            "sourceKeys": doc["sourceKeys"],
            "artifact": {"key": saved["assetKey"], "sha256": saved["sha256"], "size": len(raw)},
            "previousChapterId": doc.get("previousChapterId"),
            "authorship": "human",
        },
    }


def save(media, body, actor):
    fields = {"gameId", "title", "markdown", "sourceKeys", "operationId", "previousChapterId"}
    if not isinstance(body, dict) or set(body) != fields:
        raise ValueError("Expected complete chapter envelope")
    game, operation = body["gameId"], body["operationId"]
    if (
        not media._valid_slug(game)
        or not isinstance(operation, str)
        or not re.fullmatch(r"[a-f0-9]{32}", operation)
    ):
        raise ValueError("Invalid game or operation")
    title, manuscript = text(body["title"], 160), text(body["markdown"], 100000)
    catalog = boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"])
    if not catalog.get_item(Key={"pk": "GAMES", "sk": game}, ConsistentRead=True).get("Item"):
        raise ValueError("Game not found")
    sources = body["sourceKeys"]
    if (
        not isinstance(sources, list)
        or len(sources) > 20
        or len(set(sources)) != len(sources)
        or any(
            not isinstance(s, str) or not asset_library.valid_key(media, game, s) for s in sources
        )
    ):
        raise ValueError("Choose distinct same-game references")
    observed = indexed(game, sources)
    if any(s not in observed for s in sources):
        raise ValueError("Every source must exist in the catalog")
    for source in observed.values():
        asset = json.loads(source["payload"])
        if (
            asset_metadata.internal(asset["kind"])
            or asset.get("lineageWarning")
            or asset.get("metadata", {}).get("extra", {}).get("relationshipRole") != "finished"
        ):
            raise ValueError("Choose finished sources")
    previous_id = body["previousChapterId"]
    previous = None
    if previous_id is not None:
        if not isinstance(previous_id, str) or not re.fullmatch(r"[a-f0-9]{64}", previous_id):
            raise ValueError("Invalid earlier chapter")
        previous = record(game, previous_id)
        if previous is None:
            import novel

            job = novel.jobs.read("RUNS", previous_id)
            generated = novel.chapter(job) if job and job.get("gameId") == game else None
            if not generated:
                raise ValueError("Earlier chapter not found")
            # A generated edition is an exact input, not evidence of a prior human
            # version family. Start a new authored family and retain its real lineage.
            previous = {"assetKey": generated["details"]["artifact"]["key"], "generated": True}
    derived_sources = list(sources)
    if previous and previous["assetKey"] not in derived_sources:
        derived_sources.append(previous["assetKey"])
    if len(derived_sources) > 20:
        raise ValueError("Too many chapter references")
    identity = hashlib.sha256((game + ":" + operation).encode()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    pointer = key(game, identity)
    db = browse_index.table()
    item = db.get_item(Key=pointer, ConsistentRead=True).get("Item")
    if item and item["fingerprint"] != fingerprint:
        return media._response(409, {"error": "Operation identity reused with different chapter"})
    if not item:
        now = datetime.now(timezone.utc)
        doc = {
            "schemaVersion": 1,
            "entityType": "UserChapter",
            "chapterId": identity,
            "gameId": game,
            "title": title,
            "markdown": manuscript,
            "sourceKeys": derived_sources,
            "seriesId": previous["seriesId"]
            if previous and not previous.get("generated")
            else identity,
            "version": previous["version"] + 1 if previous and not previous.get("generated") else 1,
            "previousChapterId": previous_id,
        }
        validate_document(doc, game)
        ref = f"games/{game}/assets/authored-chapter-{identity}/original/chapter.json"
        raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
        if len(raw) > 130000:
            raise ValueError("Chapter exceeds 130 KiB")
        saved = {
            "assetKey": ref,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "createdAt": int(now.timestamp()),
            "createdAtIso": now.isoformat(),
            "seriesId": doc["seriesId"],
            "version": doc["version"],
        }
        item = {
            **pointer,
            "fingerprint": fingerprint,
            "status": "PENDING",
            "document": raw.decode(),
            "payload": json.dumps(saved),
            "actor": actor,
        }
        try:
            db.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            return save(media, body, actor)
    saved = json.loads(item["payload"])
    if item["status"] != "DONE":
        doc = json.loads(item["document"])
        raw = item["document"].encode()
        version = {"schemaVersion": 1, "seriesId": doc["seriesId"], "number": doc["version"]}
        if previous and not previous.get("generated"):
            version["previousKey"] = previous["assetKey"]
        metadata = asset_metadata.defaults(
            "novel-chapter",
            {
                "title": title,
                "sourceKeys": doc["sourceKeys"],
                "category": "authored-chapter",
                "extra": {
                    "generation": {
                        "schemaVersion": 1,
                        "method": "human",
                        "inference": "not-applicable",
                        "cost": {"status": "not-applicable"},
                    },
                    "version": version,
                },
            },
            "chapter.json",
            "application/json",
            saved["assetKey"],
        )
        if len(base64.b64encode(json.dumps({"schemaVersion": 1, **metadata}).encode())) > 1800:
            raise ValueError("Chapter source metadata is too large")
        physical = media.s3.reserve(
            saved["assetKey"],
            "novel-chapter",
            metadata,
            saved["sha256"],
            len(raw),
            saved["createdAtIso"],
        )
        try:
            media.s3.raw.put_object(
                Bucket=media.BUCKET_NAME,
                Key=physical,
                Body=raw,
                ContentType="application/json",
                IfNoneMatch="*",
                Metadata={
                    "kind": "novel-chapter",
                    "uploaded-by": item["actor"],
                    "asset-created-at": saved["createdAtIso"],
                    "panther": base64.b64encode(
                        json.dumps({"schemaVersion": 1, **metadata}).encode()
                    ).decode(),
                },
            )
        except ClientError as error:
            if error.response["Error"]["Code"] not in {
                "PreconditionFailed",
                "ConditionalRequestConflict",
            }:
                raise
            existing = media.s3.get_object(Bucket=media.BUCKET_NAME, Key=saved["assetKey"])[
                "Body"
            ].read(130001)
            if existing != raw:
                raise ValueError("Immutable chapter collision")
        db.put_item(
            Item={**item, "status": "DONE"},
            ConditionExpression="fingerprint = :f",
            ExpressionAttributeValues={":f": fingerprint},
        )
    return media._response(200, {"chapterId": identity, "assetKey": saved["assetKey"]})


def handler(event, _context):
    import index as media

    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "MODEL_PUBLISHERS"):
        return media._response(403, {"error": "Chapter editing is unavailable for this account"})
    try:
        raw = event.get("body") or "{}"
        if len(raw.encode()) > 140000:
            raise ValueError("Chapter is too large")
        return save(media, json.loads(raw), claims["sub"])
    except (ValueError, TypeError, KeyError):
        return media._response(400, {"error": "Invalid chapter or source references"})
    except ClientError:
        return media._response(503, {"error": "Chapter save interrupted; retry the same operation"})
