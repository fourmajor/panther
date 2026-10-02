"""Episode-owned scene definitions, independent of generated footage or jobs."""

import json
import os
import time

import boto3
from botocore.exceptions import ClientError

from access_policy import authorized
import browse_index
import organization_records as records
from novel_library import slug, text

PREFIX = "episode-scenes-v1"
TYPES = {"general", "opener", "travel", "action", "dialogue"}


def public(record):
    return {key: value for key, value in record.items() if key != "updatedBy"}


def pin_scene(game, reference):
    if not isinstance(reference, dict) or set(reference) != {"episodeId", "sceneId", "revision"}:
        raise ValueError("Choose a scene revision")
    import index as media

    episode, scene = slug(media, reference["episodeId"]), slug(media, reference["sceneId"])
    revision = records.revision(reference["revision"])
    db = browse_index.table()
    if not db.get_item(
        Key=records.pointer(PREFIX, game, "episode", episode), ConsistentRead=True
    ).get("Item"):
        raise ValueError("Episode not found")
    record = records.decode(
        db.get_item(
            Key={"pk": f"{PREFIX}-history#scene#{episode}#{game}#{scene}", "sk": revision},
            ConsistentRead=True,
        ).get("Item")
    )
    if (
        not record
        or record.get("entityType") != "Scene"
        or record.get("schemaVersion") != 1
        or record.get("episodeId") != episode
        or record.get("gameId") != game
        or record.get("id") != scene
        or record.get("revision") != revision
    ):
        raise ValueError("Scene revision not found")
    return public(record)


def save(media, body, claims, kind):
    common = {"gameId", "id", "name", "description", "expectedRevision", "operationId"}
    allowed = common | ({"episodeId", "type"} if kind == "scene" else set())
    required = allowed - {"description", "type"}
    if not isinstance(body, dict) or not required <= set(body) <= allowed:
        raise ValueError("Invalid episode or scene edit")
    game, identity = slug(media, body["gameId"]), slug(media, body["id"])
    records.revision(body["operationId"])
    records.revision(body["expectedRevision"], optional=True)
    if (
        not boto3.resource("dynamodb")
        .Table(os.environ["CATALOG_TABLE"])
        .get_item(Key={"pk": "GAMES", "sk": game}, ConsistentRead=True)
        .get("Item")
    ):
        raise ValueError("Game not found")
    record = {
        "schemaVersion": 1,
        "entityType": "Scene" if kind == "scene" else "Episode",
        "gameId": game,
        "id": identity,
        "name": text(body["name"], 160),
        "description": text(body.get("description", ""), 4000, empty=True),
    }
    guards, db = [], browse_index.table()
    if kind == "scene":
        episode = slug(media, body["episodeId"])
        scene_type = body.get("type", "general")
        if scene_type not in TYPES:
            raise ValueError("Invalid scene type")
        kind = f"scene#{episode}"
        parent_key = records.pointer(PREFIX, game, "episode", episode)
        parent = db.get_item(Key=parent_key, ConsistentRead=True).get("Item")
        if not parent:
            raise ValueError("Episode not found")
        record.update(episodeId=episode, type=scene_type)
        guards.append(
            {
                "ConditionCheck": {
                    "TableName": db.name,
                    "Key": records.encode(parent_key),
                    "ConditionExpression": "revision = :r",
                    "ExpressionAttributeValues": records.encode({":r": parent["revision"]}),
                }
            }
        )
    previous = records.decode(
        db.get_item(Key=records.pointer(PREFIX, game, kind, identity), ConsistentRead=True).get(
            "Item"
        )
    )
    record["position"] = previous["position"] if previous else int(time.time() * 1000)
    record["createdAt"] = (
        previous["createdAt"] if previous else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    guarded = {
        **body,
        "reason": ("Edit " if body["expectedRevision"] else "Create ")
        + record["entityType"].lower(),
    }
    fingerprint, replay = records.replay(db, PREFIX, game, kind, identity, guarded, media)
    if replay:
        return replay
    return records.commit(db, PREFIX, kind, record, guarded, claims, fingerprint, guards, media)


def handler(event, _context):
    import index as media

    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    route = event.get("routeKey", "")
    if route == "POST /video-workspace/migrate":
        import episode_migration

        return episode_migration.handler(event, _context)
    if route not in {"GET /episodes", "POST /episodes", "GET /scenes", "POST /scenes"}:
        return media._response(404, {"error": "Route not found"})
    read = route.startswith("GET ")
    if not authorized(claims, "CATALOG_READERS" if read else "MODEL_PUBLISHERS"):
        return media._response(
            403,
            {
                "error": "This account cannot "
                + ("view" if read else "edit")
                + " episodes and scenes"
            },
        )
    try:
        q = event.get("queryStringParameters") or {}
        kind = "scene" if route.endswith("/scenes") else "episode"
        if not read:
            response = save(media, json.loads(event.get("body") or "{}"), claims, kind)
        else:
            game = slug(media, q.get("gameId"))
            if kind == "scene":
                kind += "#" + slug(media, q.get("episodeId"))
            response = records.read(browse_index.table(), PREFIX, game, kind, q, media)
        payload = json.loads(response["body"])
        if "record" in payload:
            payload["record"] = public(payload["record"])
        if "records" in payload:
            payload["records"] = [public(record) for record in payload["records"]]
        return media._response(response["statusCode"], payload)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return media._response(
            400,
            {
                "error": "Choose a title and a valid same-game episode. Description and footage are optional."
            },
        )
    except ClientError:
        return media._response(503, {"error": "Episodes and scenes are temporarily unavailable"})
