"""Explicit, bounded all-game TVEpisode -> Episode migration; never a read fallback."""

import hashlib
import json
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from access_policy import authorized
import browse_index
import organization_records as records

VERSION = 1
PREFIX = "episode-scenes-v1"
AUDIT = "episode-scenes-migration-v1"
MAX_ROWS = 1000
MAX_BYTES = 16 * 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def complete(db, pk, budget):
    args = {"KeyConditionExpression": Key("pk").eq(pk), "ConsistentRead": True, "Limit": 100}
    result = []
    for _ in range(100):
        page = db.query(**args)
        rows = page.get("Items", [])
        budget[0] += len(rows)
        budget[1] += sum(len(str(row).encode()) for row in rows)
        if budget[0] > MAX_ROWS or budget[1] > MAX_BYTES:
            raise ValueError("Complete migration inventory exceeds its bound; nothing applied")
        result.extend(rows)
        if not page.get("LastEvaluatedKey"):
            return result
        args["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    raise ValueError("Complete migration inventory exceeds its page bound; nothing applied")


def inventory(media):
    db = browse_index.table()
    budget = [0, 0]
    games = complete(boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"]), "GAMES", budget)
    entries = []
    for game_item in games:
        game = game_item["sk"]
        if not media._valid_slug(game):
            raise ValueError("Invalid registered game identity")
        for source in complete(db, f"tv-library#episode#{game}", budget):
            record = records.decode(source)
            identity = source["sk"]
            if not record or record.get("schemaVersion") != 1 or record.get("entityType") != "TVEpisode" or record.get("gameId") != game or record.get("id") != identity or not media._valid_slug(identity):
                raise ValueError("Invalid legacy episode; migration blocked")
            records.revision(record.get("revision"))
            if source.get("revision") != record["revision"] or not isinstance(record.get("title"), str) or not 0 < len(record["title"]) <= 160 or not isinstance(record.get("synopsis"), str) or len(record["synopsis"]) > 4000:
                raise ValueError("Unresolvable legacy episode fields; migration blocked")
            history = complete(db, f"tv-library-history#episode#{game}#{identity}", budget)
            for row in history:
                historical = records.decode(row)
                if not historical or historical.get("entityType") != "TVEpisode" or historical.get("schemaVersion") != 1 or historical.get("gameId") != game or historical.get("id") != identity or historical.get("revision") != row.get("sk"):
                    raise ValueError("Unresolvable legacy episode history; migration blocked")
                records.revision(row["sk"])
            if not any(row["sk"] == record["revision"] and row.get("payload") == source["payload"] for row in history):
                raise ValueError("Current episode lacks exact retained history; migration blocked")
            snapshot = {"current": source, "history": history}
            source_hash = digest(snapshot)
            audit_key = {"pk": f"{AUDIT}#{game}", "sk": identity}
            prior = db.get_item(Key=audit_key, ConsistentRead=True).get("Item")
            target = db.get_item(Key=records.pointer(PREFIX, game, "episode", identity), ConsistentRead=True).get("Item")
            imported = records.decode(db.get_item(Key={"pk": f"{PREFIX}-history#episode#{game}#{identity}", "sk": prior.get("destinationRevision", "missing")}, ConsistentRead=True).get("Item")) if prior else None
            current = records.decode(target)
            if prior and prior.get("sourceHash") == source_hash and prior.get("snapshot") and json.loads(prior["snapshot"]) == snapshot and current and imported and current.get("entityType") == "Episode" and current.get("gameId") == game and current.get("id") == identity and imported.get("revision") == prior.get("destinationRevision") and imported.get("migration", {}).get("sourceHash") == source_hash and imported.get("name") == record["title"] and imported.get("description") == record["synopsis"]:
                status = "already-migrated"
            elif prior or target:
                status = "conflict"
            else:
                status = "ready"
            if len(json.dumps({"snapshot": json.dumps(snapshot, separators=(",", ":"))}).encode()) > 320_000:
                raise ValueError("Legacy episode history exceeds bounded audit storage; migration blocked")
            entries.append({"gameId": game, "id": identity, "sourceHash": source_hash, "source": source, "snapshot": snapshot, "status": status})
    return db, entries, digest([{key: item[key] for key in ("gameId", "id", "sourceHash")} for item in entries])


def migrate(media, body, claims):
    if not isinstance(body, dict) or set(body) not in ({"schemaVersion", "apply"}, {"schemaVersion", "apply", "expectedInventoryHash"}) or body.get("schemaVersion") != VERSION or type(body.get("apply")) is not bool:
        raise ValueError("Use schemaVersion 1 and apply false for a dry run")
    db, entries, inventory_hash = inventory(media)
    summary = [{key: item[key] for key in ("gameId", "id", "sourceHash", "status")} for item in entries]
    if not body["apply"]:
        return media._response(200, {"schemaVersion": VERSION, "inventoryHash": inventory_hash, "episodes": summary, "applied": False})
    if body.get("expectedInventoryHash") != inventory_hash or any(item["status"] == "conflict" for item in entries):
        return media._response(409, {"error": "Inventory changed or destination conflicts; review a fresh dry run"})
    # Per-episode atomic transactions make interrupted runs safely resumable. No source is deleted.
    applied = 0
    for item in entries:
        if item["status"] == "already-migrated":
            continue
        source = records.decode(item["source"])
        revision = item["sourceHash"][:32]
        now = datetime.now(timezone.utc).isoformat()
        target = {"schemaVersion": 1, "entityType": "Episode", "gameId": item["gameId"], "id": item["id"], "name": source["title"], "description": source["synopsis"], "revision": revision, "previousRevision": None, "position": source.get("number", 0), "createdAt": source.get("createdAt"), "updatedAt": now, "updatedBy": claims["sub"], "reason": "Import explicit legacy TVEpisode", "migration": {"schemaVersion": VERSION, "sourceHash": item["sourceHash"], "sourceRevision": source["revision"]}}
        payload = json.dumps(target, separators=(",", ":"))
        audit = {"pk": f"{AUDIT}#{item['gameId']}", "sk": item["id"], "sourceHash": item["sourceHash"], "inventoryHash": inventory_hash, "appliedAt": now, "appliedBy": claims["sub"], "snapshot": json.dumps(item["snapshot"], separators=(",", ":")), "destinationRevision": revision}
        puts = [{**records.pointer(PREFIX, item["gameId"], "episode", item["id"]), "revision": revision, "payload": payload}, {"pk": f"{PREFIX}-history#episode#{item['gameId']}#{item['id']}", "sk": revision, "payload": payload}, audit]
        operations = [{"Put": {"TableName": db.name, "Item": records.encode(row), "ConditionExpression": "attribute_not_exists(pk)"}} for row in puts]
        operations.append({"ConditionCheck": {"TableName": db.name, "Key": records.encode({"pk": item["source"]["pk"], "sk": item["source"]["sk"]}), "ConditionExpression": "revision = :r AND payload = :p", "ExpressionAttributeValues": records.encode({":r": source["revision"], ":p": item["source"]["payload"]})}})
        try:
            boto3.client("dynamodb").transact_write_items(TransactItems=operations)
        except ClientError as error:
            if error.response["Error"]["Code"] == "TransactionCanceledException":
                return media._response(409, {"error": "Source or destination changed; rerun dry run to resume", "appliedCount": applied})
            raise
        applied += 1
    return media._response(200, {"schemaVersion": VERSION, "inventoryHash": inventory_hash, "applied": True, "appliedCount": applied, "episodeCount": len(entries), "sceneCount": 0})


def handler(event, _context):
    import index as media

    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "ASSET_MIGRATORS"):
        return media._response(403, {"error": "This account cannot migrate episode organization"})
    try:
        return migrate(media, json.loads(event.get("body") or "{}"), claims)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return media._response(400, {"error": "Migration inventory or request is invalid; no further episodes applied"})
    except ClientError:
        return media._response(503, {"error": "Episode migration unavailable; rerun dry run before retrying"})
