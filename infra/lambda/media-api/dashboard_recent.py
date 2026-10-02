"""Whole-inventory recent summaries, from bounded materialized metadata only."""

from datetime import datetime, timezone
import json
from decimal import Decimal
import math
import re

from boto3.dynamodb.conditions import Key
import browse_index
import storage_layout

MAX_ASSETS = 5000
MAX_CHARACTERS = 500
MAX_METADATA_BYTES = 16 * 1024**2
MAX_METADATA_PAGES = 200


def observed_time(value):
    """Unknown dates stay unknown; zero never becomes an invented creation date."""
    try:
        if type(value) in {int, float, Decimal} and math.isfinite(value) and value > 0:
            return datetime.fromtimestamp(value, timezone.utc).timestamp()
        if isinstance(value, str):
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if date.tzinfo is not None:
                return date.timestamp()
    except (ValueError, OverflowError, OSError):
        pass
    return None


def date_value(value):
    timestamp = observed_time(value)
    if timestamp is None:
        return None
    return (
        value
        if isinstance(value, str)
        else datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    )


def bounded_query(table, args, limit):
    items, seen, size = [], set(), 0
    while True:
        page = table.query(**args)
        entries = page.get("Items", [])
        size += sum(len(item.get("payload", "").encode()) for item in entries)
        items.extend(entries)
        if size > MAX_METADATA_BYTES or len(seen) >= MAX_METADATA_PAGES:
            raise RuntimeError("Dashboard metadata exceeds its complete-summary bound")
        if len(items) > limit:
            raise RuntimeError("Dashboard inventory exceeds its complete-summary bound")
        following = page.get("LastEvaluatedKey")
        if not following:
            return items
        encoded = json.dumps(following, sort_keys=True)
        if encoded in seen:
            raise RuntimeError("Dashboard catalog pagination did not progress")
        seen.add(encoded)
        args = {**args, "ExclusiveStartKey": following}


def character_summaries(catalog, game):
    records = bounded_query(
        catalog.table,
        {
            "KeyConditionExpression": Key("pk").eq(f"GAME#{game}")
            & Key("sk").begins_with("CHARACTER#"),
            "ConsistentRead": True,
            "Limit": 100,
            "ProjectionExpression": "id, gameId, #n, detailsRevision, detailsSubtitle, detailsThumbnailKey, updatedAt, detailsUpdatedAt, createdAt",
            "ExpressionAttributeNames": {"#n": "name"},
        },
        MAX_CHARACTERS,
    )
    # Current immutable revision history is a date source, never the actor roster or a guessed date.
    keys = [
        {"pk": f"CHARACTER_DETAILS_HISTORY#{game}#{r['id']}", "sk": r["detailsRevision"]}
        for r in records
        if isinstance(r.get("detailsRevision"), str)
    ]
    dates = {}
    for offset in range(0, len(keys), 100):
        pending = {
            catalog.table.name: {
                "Keys": keys[offset : offset + 100],
                "ConsistentRead": True,
                "ProjectionExpression": "pk, sk, recordedAt",
            }
        }
        for _ in range(3):
            result = catalog.table.meta.client.batch_get_item(RequestItems=pending)
            for entry in result.get("Responses", {}).get(catalog.table.name, []):
                dates[(entry["pk"], entry["sk"])] = entry.get("recordedAt")
            pending = result.get("UnprocessedKeys", {})
            if not pending:
                break
        if pending:
            raise RuntimeError("Dashboard character history is temporarily unavailable")
    summaries = []
    for record in records:
        values = [
            record.get("detailsUpdatedAt"),
            record.get("updatedAt"),
            record.get("createdAt"),
            dates.get(
                (f"CHARACTER_DETAILS_HISTORY#{game}#{record['id']}", record.get("detailsRevision"))
            ),
        ]
        known = [
            (observed_time(value), value) for value in values if observed_time(value) is not None
        ]
        updated = max(known, key=lambda pair: pair[0])[1] if known else None
        updated = date_value(updated)
        summaries.append(
            {
                "id": record["id"],
                "gameId": game,
                "name": record.get("name", record["id"]),
                "detailsSubtitle": record.get("detailsSubtitle"),
                "updatedAt": updated,
            }
        )
    return summaries


def recent(catalog, game):
    db = browse_index.table()
    if not db.get_item(
        Key={"pk": f"v{browse_index.VERSION}#catalog", "sk": "ready"}, ConsistentRead=True
    ).get("Item"):
        raise browse_index.IndexNotReady(
            "The asset catalog is not ready; recent items are unavailable"
        )
    rows = bounded_query(
        db,
        {
            "KeyConditionExpression": Key("pk").eq(browse_index.partition(game, "all")),
            "ConsistentRead": True,
            "Limit": 100,
            "ProjectionExpression": "sk, payload",
        },
        MAX_ASSETS,
    )
    assets = [json.loads(row["payload"]) for row in rows]
    by_key = {asset["key"]: asset for asset in assets}
    groups = {
        "characters": character_summaries(catalog, game),
        "transcripts": [],
        "videos": [],
        "chapters": [],
    }
    for asset in assets:
        key = asset.get("key")
        if (
            not isinstance(key, str)
            or not storage_layout.REFERENCE.fullmatch(key)
            or not key.startswith(f"games/{game}/assets/")
        ):
            raise RuntimeError("Dashboard catalog contains a foreign or invalid asset")
        kind, name = asset.get("kind", ""), asset.get("name", key.split("/")[-1])
        metadata = asset.get("metadata", {})
        if metadata.get("extra", {}).get("relationshipRole") == "intermediate":
            continue
        title = metadata.get("title") or name
        entry = {
            "key": key,
            "name": name,
            "title": title,
            "contentType": asset.get("contentType"),
            "kind": kind,
            "lastModified": date_value(asset.get("lastModified")),
        }
        if kind in {"transcript", "raw-transcript", "corrected-transcript", "edited-transcript"}:
            if not (key.endswith(".md") and by_key.get(key[:-3] + ".json", {}).get("kind") == kind):
                groups["transcripts"].append(entry)
        if asset.get("contentType", "").startswith("video/") or re.search(
            r"\.(mp4|webm|mov|m4v|ogv)$", name, re.I
        ):
            groups["videos"].append(entry)
        chapter = asset.get("novel", {})
        if isinstance(chapter, dict) and chapter.get("state") == "available":
            groups["chapters"].append(
                {**entry, "id": chapter["id"], "title": chapter.get("title", title)}
            )
    counts = {name: len(items) for name, items in groups.items()}
    for name, items in groups.items():

        def order(item):
            date = observed_time(
                item.get("updatedAt") if name == "characters" else item.get("lastModified")
            )
            return (date is None, -(date or 0), item.get("id", item.get("key", "")))

        groups[name] = sorted(items, key=order)[:5]
    return {"complete": True, "groups": groups, "counts": counts}
