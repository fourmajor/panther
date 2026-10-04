"""Episode-owned scene definitions, independent of generated footage or jobs."""

import json
import hashlib
import uuid
import os
import time

import boto3
from botocore.exceptions import ClientError

from access_policy import authorized
import browse_index
import asset_library
import asset_metadata
import scene_inputs
import organization_records as records
from novel_library import slug, text

PREFIX = "episode-scenes-v1"
TYPES = {"general", "opener", "travel", "map", "action", "dialogue"}


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


def guard(db, key, field, value):
    return {
        "ConditionCheck": {
            "TableName": db.name,
            "Key": records.encode(key),
            "ConditionExpression": f"{field} = :r",
            "ExpressionAttributeValues": records.encode({":r": value}),
        }
    }


def selected_output(media, game, episode, scene, key):
    """Resolve a deliberate exact output selection from the bounded materialized catalog."""
    if not isinstance(key, str) or not asset_library.valid_key(media, game, key):
        raise ValueError("Choose an immutable same-game video")
    db = browse_index.table()
    pointer = {"pk": browse_index.partition(game, "all"), "sk": key}
    row = db.get_item(Key=pointer, ConsistentRead=True).get("Item")
    asset = records.decode(row)
    if not isinstance(asset, dict):
        raise ValueError("Video is unavailable in the current catalog")
    metadata = asset.get("metadata")
    extra = metadata.get("extra") if isinstance(metadata, dict) else None
    if (
        not isinstance(extra, dict)
        or not isinstance(asset.get("contentType"), str)
        or not isinstance(asset.get("kind", ""), str)
    ):
        raise ValueError("Invalid video metadata")
    ref = extra.get("sceneRef")
    if (
        not asset
        or asset.get("key") != key
        or not asset.get("contentType", "").startswith("video/")
        or asset.get("lineageWarning")
        or asset_metadata.internal(asset.get("kind", ""))
        or extra.get("relationshipRole") != "finished"
        or not isinstance(ref, dict)
        or ref.get("episodeId") != episode
        or ref.get("sceneId") != scene
    ):
        raise ValueError("Output must explicitly belong to this scene")
    pin_scene(game, ref)
    return ref["revision"], guard(db, pointer, "observed", row["observed"])


def map_asset(media, game, key):
    """Resolve one explicit image from the bounded catalog; never scan source storage."""
    if not isinstance(key, str) or not asset_library.valid_key(media, game, key):
        raise ValueError("Choose a same-game map image")
    db = browse_index.table()
    pointer = {"pk": browse_index.partition(game, "all"), "sk": key}
    row = db.get_item(Key=pointer, ConsistentRead=True).get("Item")
    value = records.decode(row)
    if not isinstance(value, dict):
        raise ValueError("Map image is unavailable in the catalog")
    metadata = value.get("metadata") or {}
    if not isinstance(metadata, dict) or not isinstance(value.get("kind", ""), str):
        raise ValueError("Invalid map metadata")
    extra = metadata.get("extra") or {}
    if not isinstance(extra, dict):
        raise ValueError("Invalid map metadata")
    if (
        value.get("key") != key
        or value.get("contentType") not in {"image/png", "image/jpeg", "image/webp"}
        or value.get("lineageWarning")
        or asset_metadata.internal(value.get("kind", ""))
        or extra.get("relationshipRole") in {"processing", "intermediate", "internal"}
    ):
        raise ValueError("Choose a finished PNG, JPEG or WebP map image")
    return value, guard(db, pointer, "observed", row["observed"])


def pin_episode(game, reference):
    """Freeze explicit scene order and selected outputs; never infer a take or skip a scene."""
    import index as media

    if not isinstance(reference, dict) or set(reference) != {"episodeId", "revision"}:
        raise ValueError("Choose an episode revision")
    episode = slug(media, reference["episodeId"])
    revision = records.revision(reference["revision"])
    db = browse_index.table()
    record = records.decode(
        db.get_item(
            Key={"pk": f"{PREFIX}-history#episode#{game}#{episode}", "sk": revision},
            ConsistentRead=True,
        ).get("Item")
    )
    if (
        not record
        or record.get("entityType") != "Episode"
        or record.get("gameId") != game
        or record.get("id") != episode
        or record.get("schemaVersion") != 1
        or record.get("revision") != revision
    ):
        raise ValueError("Episode revision not found")
    order = record.get("sceneIds", [])
    if (
        not isinstance(order, list)
        or len(order) > 50
        or not all(
            isinstance(identity, str) and media._valid_slug(identity) and len(identity) <= 96
            for identity in order
        )
        or len(set(order)) != len(order)
    ):
        raise ValueError("Invalid stored episode order")
    if not order:
        raise ValueError("Add scenes before rendering the episode")
    scenes, missing = [], []
    for identity in order:
        scene = records.decode(
            db.get_item(
                Key=records.pointer(PREFIX, game, f"scene#{episode}", identity), ConsistentRead=True
            ).get("Item")
        )
        if (
            not scene
            or scene.get("gameId") != game
            or scene.get("episodeId") != episode
            or scene.get("id") != identity
            or scene.get("entityType") != "Scene"
            or scene.get("schemaVersion") != 1
        ):
            raise ValueError("Episode references a missing or invalid scene")
        records.revision(scene.get("revision"))
        if not scene.get("selectedOutputKey"):
            missing.append(identity)
            scenes.append(
                {
                    "sceneRef": {
                        "episodeId": episode,
                        "sceneId": identity,
                        "revision": scene["revision"],
                    },
                    "scene": public(scene),
                    "generationSceneRef": None,
                    "assetKey": None,
                }
            )
            continue
        output_revision, _ = selected_output(
            media, game, episode, identity, scene["selectedOutputKey"]
        )
        if output_revision != scene["selectedOutputSceneRevision"]:
            raise ValueError("Selected output provenance changed")
        scenes.append(
            {
                "sceneRef": {
                    "episodeId": episode,
                    "sceneId": identity,
                    "revision": scene["revision"],
                },
                "generationSceneRef": {
                    "episodeId": episode,
                    "sceneId": identity,
                    "revision": output_revision,
                },
                "scene": public(scene),
                "assetKey": scene["selectedOutputKey"],
            }
        )
    result = {
        "schemaVersion": 1,
        "entityType": "EpisodeComposition",
        "gameId": game,
        "episode": public(record),
        "ready": not missing,
        "missingSceneIds": missing,
        "scenes": scenes,
        "sourceKeys": [scene["assetKey"] for scene in scenes if scene["assetKey"]],
    }
    result["compositionHash"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return result


def save(media, body, claims, kind):
    common = {"gameId", "id", "name", "description", "expectedRevision", "operationId"}
    allowed = common | (
        {"episodeId", "type", "selectedOutputKey", "mapAssetKey", "generationInputs"}
        if kind == "scene"
        else {"sceneIds"}
    )
    required = common - {"description"}
    if kind == "scene":
        required.add("episodeId")
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
    parent_record = None
    storage_kind = f"scene#{slug(media, body['episodeId'])}" if kind == "scene" else kind
    guarded = {
        **body,
        "reason": ("Edit " if body["expectedRevision"] else "Create ")
        + record["entityType"].lower(),
    }
    fingerprint, replay = records.replay(db, PREFIX, game, storage_kind, identity, guarded, media)
    if replay:
        return replay
    previous = records.decode(
        db.get_item(
            Key=records.pointer(PREFIX, game, storage_kind, identity), ConsistentRead=True
        ).get("Item")
    )
    if kind == "scene":
        episode = slug(media, body["episodeId"])
        scene_type = body.get("type", (previous or {}).get("type", "general"))
        if scene_type not in TYPES:
            raise ValueError("Invalid scene type")
        kind = f"scene#{episode}"
        parent_key = records.pointer(PREFIX, game, "episode", episode)
        parent = db.get_item(Key=parent_key, ConsistentRead=True).get("Item")
        if not parent:
            raise ValueError("Episode not found")
        record.update(
            episodeId=episode,
            type=scene_type,
            selectedOutputKey=body.get(
                "selectedOutputKey", (previous or {}).get("selectedOutputKey")
            ),
            selectedOutputSceneRevision=None,
        )
        inputs = scene_inputs.normalize(body.get("generationInputs", (previous or {}).get("generationInputs")), game)
        for character_id in inputs["characterIds"]:
            character = boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"]).get_item(
                Key={"pk": f"GAME#{game}", "sk": f"CHARACTER#{character_id}"}, ConsistentRead=True
            ).get("Item")
            if not character or character.get("gameId") != game or character.get("id") != character_id:
                raise ValueError("Choose a character from this game")
        for source_key in scene_inputs.asset_keys({"generationInputs": inputs}):
            pointer = {"pk": browse_index.partition(game, "all"), "sk": source_key}
            source_row = db.get_item(Key=pointer, ConsistentRead=True).get("Item")
            source = records.decode(source_row)
            if not source or source.get("key") != source_key or asset_metadata.internal(source.get("kind", "")) or source.get("metadata", {}).get("extra", {}).get("relationshipRole") in {"processing", "intermediate", "internal"}:
                raise ValueError("A selected source is unavailable")
            guards.append(guard(db, pointer, "observed", source_row["observed"]))
        record["generationInputs"] = inputs
        map_key = body.get("mapAssetKey", (previous or {}).get("mapAssetKey"))
        if "mapAssetKey" in body or "mapAssetKey" in (previous or {}):
            record["mapAssetKey"] = map_key
        if map_key is not None:
            _, map_guard = map_asset(media, game, map_key)
            guards.append(map_guard)
            record["mapAssetKey"] = map_key
        if record["selectedOutputKey"] is not None:
            output_revision, output_guard = selected_output(
                media, game, episode, identity, record["selectedOutputKey"]
            )
            record["selectedOutputSceneRevision"] = output_revision
            guards.append(output_guard)
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
    else:
        order = body.get("sceneIds", (previous or {}).get("sceneIds", []))
        if (
            not isinstance(order, list)
            or len(order) > 50
            or not all(
                isinstance(value, str) and media._valid_slug(value) and len(value) <= 96
                for value in order
            )
            or len(set(order)) != len(order)
        ):
            raise ValueError("Choose up to fifty distinct episode-owned scenes in order")
        if previous and set(order) != set(previous.get("sceneIds", [])):
            raise ValueError("Reorder every existing scene; scene creation appends separately")
        record["sceneIds"] = order
        for scene_id in order:
            scene_key = records.pointer(PREFIX, game, f"scene#{identity}", scene_id)
            scene = db.get_item(Key=scene_key, ConsistentRead=True).get("Item")
            definition = records.decode(scene)
            if (
                not definition
                or definition.get("episodeId") != identity
                or definition.get("gameId") != game
            ):
                raise ValueError("Scene does not belong to this episode")
            guards.append(guard(db, scene_key, "revision", scene["revision"]))
    if kind.startswith("scene#") and not previous and body["expectedRevision"] is None:
        parent_record = records.decode(parent)
        if identity in parent_record.get("sceneIds", []):
            raise ValueError("Episode order already contains this scene identity")
        parent_record.update(
            sceneIds=[*parent_record.get("sceneIds", []), identity],
            previousRevision=parent["revision"],
            revision=uuid.uuid4().hex,
            updatedAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            updatedBy=claims["sub"],
            reason="Add scene",
        )
        if len(parent_record["sceneIds"]) > 50:
            raise ValueError("An episode supports at most fifty scenes")
        parent_payload = json.dumps(parent_record, separators=(",", ":"), allow_nan=False)
        # Replace the parent ConditionCheck with an atomic CAS write plus retained history.
        guards[-1] = {
            "Put": {
                "TableName": db.name,
                "Item": records.encode(
                    {**parent_key, "revision": parent_record["revision"], "payload": parent_payload}
                ),
                "ConditionExpression": "revision = :r",
                "ExpressionAttributeValues": records.encode({":r": parent["revision"]}),
            }
        }
        guards.append(
            {
                "Put": {
                    "TableName": db.name,
                    "Item": records.encode(
                        {
                            "pk": f"{PREFIX}-history#episode#{game}#{episode}",
                            "sk": parent_record["revision"],
                            "payload": parent_payload,
                        }
                    ),
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            }
        )
    record["position"] = previous["position"] if previous else int(time.time() * 1000)
    record["createdAt"] = (
        previous["createdAt"] if previous else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    if record["entityType"] == "Scene":
        import asset_archive

        guards.extend(
            asset_archive.reference_writes(
                game,
                "scene:{}:{}".format(record["episodeId"], identity),
                [record.get("mapAssetKey"), record.get("selectedOutputKey"), *scene_inputs.asset_keys(record)],
            )
        )
    response = records.commit(db, PREFIX, kind, record, guarded, claims, fingerprint, guards, media)
    if response["statusCode"] == 200 and parent_record:
        payload = json.loads(response["body"])
        payload["episodeRecord"] = public(parent_record)
        return media._response(200, payload)
    return response


def handler(event, _context):
    import index as media

    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    route = event.get("routeKey", "")
    if route == "POST /video-workspace/migrate":
        import episode_migration

        return episode_migration.handler(event, _context)
    if route not in {
        "GET /episode-composition",
        "GET /episodes",
        "POST /episodes",
        "GET /scenes",
        "POST /scenes",
    }:
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
        if route == "GET /episode-composition":
            game = slug(media, q.get("gameId"))
            return media._response(
                200,
                pin_episode(game, {"episodeId": q.get("episodeId"), "revision": q.get("revision")}),
            )
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
