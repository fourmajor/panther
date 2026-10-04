"""Leased editorial stages. Callback tokens stay in AWS; all game content stays private."""

import base64
import hashlib
import json
import math
import os
import re
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError
import index as media
from asset_views import MAP_SCENE_INSTRUCTIONS

table = boto3.resource("dynamodb").Table(os.environ["EDITORIAL_TABLE"])
states = boto3.client("stepfunctions")
PLAN = json.loads(os.environ["EDITORIAL_PLAN"])
STAGES = sum([PLAN[b] for b in ("correction", "novel", "video")], [])
TERMINAL = {"FAILED", "READY_FOR_VIDEO_DISCUSSION", "NOVEL_READY"}


def response(code, value):
    return {
        "statusCode": code,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(value, default=lambda v: float(v) if isinstance(v, Decimal) else str(v)),
    }


def read(pk, sk):
    return table.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item")


def public(item):
    return {k: v for k, v in item.items() if k not in {"pk", "sk", "taskToken", "lease", "actor"}}


def query(pk):
    args = {"KeyConditionExpression": Key("pk").eq(pk), "ConsistentRead": True}
    while True:
        page = table.query(**args)
        yield from page.get("Items", [])
        if not page.get("LastEvaluatedKey"):
            return
        args["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def asset(key, game, maximum=16 * 1024**2):
    if (
        not isinstance(key, str)
        or not re.fullmatch(rf"games/{re.escape(game)}/assets/[a-z0-9-]+/original/[^/\\]+", key)
        or not media._valid_key(key)
    ):
        raise ValueError("Expected immutable same-game asset")
    head = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=key, ChecksumMode="ENABLED")
    if not head.get("ChecksumSHA256") or not 0 < head["ContentLength"] <= maximum:
        raise ValueError("Checksummed text artifact exceeds the supported size")
    return {"key": key, "sha256": head["ChecksumSHA256"], "size": head["ContentLength"]}, head


def pin_map(game, scene):
    if not scene or scene.get("type") != "map":
        return None
    import video_scenes

    key = scene.get("mapAssetKey")
    video_scenes.map_asset(media, game, key)
    head = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=key, ChecksumMode="ENABLED")
    if (
        head.get("ContentType") not in {"image/png", "image/jpeg", "image/webp"}
        or not head.get("ChecksumSHA256")
        or not 0 < head.get("ContentLength", 0) <= 20 * 1024**2
    ):
        raise ValueError("Choose a checksummed map image under 20 MiB")
    return {
        "schemaVersion": 1,
        "key": key,
        "sha256": head["ChecksumSHA256"],
        "size": head["ContentLength"],
        "contentType": head["ContentType"],
        "role": "first-frame",
        "instructions": MAP_SCENE_INSTRUCTIONS,
    }


def document(reference):
    data = media.s3.get_object(Bucket=media.BUCKET_NAME, Key=reference["key"])["Body"].read(
        16 * 1024**2 + 1
    )
    if (
        len(data) != reference["size"]
        or base64.b64encode(hashlib.sha256(data).digest()).decode() != reference["sha256"]
    ):
        raise ValueError("Artifact changed")
    return json.loads(data)


def validate_raw(raw, game):
    if (
        raw.get("entityType") not in {"PlayerTranscript", "BrowserTranscript"}
        or raw.get("gameId") != game
        or raw.get("artifactType", "raw-transcript") != "raw-transcript"
        or (raw.get("entityType") == "BrowserTranscript" and raw.get("mode") != "final")
    ):
        raise ValueError("Only completed raw transcripts can start editorial work")
    if (
        not isinstance(raw.get("segments"), list)
        or not raw["segments"]
        or not media._valid_slug(raw.get("recordingId"))
        or not media._valid_slug(raw.get("sessionId"))
    ):
        raise ValueError("Incomplete raw transcript")
    if raw["entityType"] == "PlayerTranscript" and (
        not isinstance(raw.get("sourceParts"), list) or not raw["sourceParts"]
    ):
        raise ValueError("Missing source parts")
    if raw["entityType"] == "BrowserTranscript" and (
        not isinstance(raw.get("sourceKeys"), list)
        or not raw["sourceKeys"]
        or any(not isinstance(key, str) for key in raw["sourceKeys"])
    ):
        raise ValueError("Missing browser sources")
    for segment in raw["segments"]:
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            raise ValueError("Invalid transcript segment")
        start, end = segment.get("start"), segment.get("end")
        if (
            any(type(v) not in {int, float} or not math.isfinite(v) for v in (start, end))
            or not 0 <= start <= end
        ):
            raise ValueError("Invalid transcript timing")


def pin_cast(game, ids):
    import character_appearances as looks
    import character_details

    pins = []
    for identity in ids:
        _, _, registered = looks.character(game, identity)
        decoded = character_details.decode(registered)
        db = looks.browse_index.table()
        marker = db.get_item(
            Key={"pk": f"{looks.PREFIX}-migration#{game}#{identity}", "sk": "complete"},
            ConsistentRead=True,
        ).get("Item")
        if not marker:
            raise ValueError("Selected character appearance migration is incomplete")
        activation = db.get_item(
            Key=looks.records.pointer(
                looks.PREFIX, game, looks.kind("activation", identity), "current"
            ),
            ConsistentRead=True,
        ).get("Item")
        appearance, refs = None, []
        if activation:
            current, physical, selection, _ = looks.resolve(game, identity)
            if current["detailsRevision"] != registered["detailsRevision"]:
                raise ValueError("Selected character changed; retry the request")
            appearance = {"appearance": physical, "selection": selection}
            for key, maximum, types in [
                (
                    selection["portraitKey"],
                    media.MAX_POSTER_BYTES,
                    {"image/png", "image/jpeg", "image/webp", "image/avif"},
                ),
                (
                    selection.get("modelKey"),
                    media.MAX_MODEL_BYTES,
                    {"model/gltf-binary", "application/octet-stream"},
                ),
            ]:
                if key is None:
                    continue
                if (
                    not isinstance(key, str)
                    or not key.startswith(f"games/{game}/assets/")
                    or not media._valid_key(key)
                ):
                    raise ValueError("Invalid selected appearance reference")
                head = media.s3.head_object(
                    Bucket=media.BUCKET_NAME, Key=key, ChecksumMode="ENABLED"
                )
                metadata = json.loads(
                    base64.b64decode(head.get("Metadata", {}).get("panther", "e30="))
                )
                if (
                    not isinstance(metadata.get("characterIds"), list)
                    or identity not in metadata["characterIds"]
                    or head.get("ContentType") not in types
                    or not 0 < head["ContentLength"] <= maximum
                    or not head.get("ChecksumSHA256")
                ):
                    raise ValueError(
                        "Selected appearance does not explicitly depict this character"
                    )
                refs.append(
                    {
                        "key": key,
                        "sha256": head["ChecksumSHA256"],
                        "size": head["ContentLength"],
                        "contentType": head["ContentType"],
                    }
                )
        pins.append(
            {
                "characterId": identity,
                "name": decoded["name"],
                "detailsRevision": decoded["revision"],
                "details": decoded["details"],
                "appearance": appearance,
                "appearanceAssets": refs,
            }
        )
    return pins


def pin_game(game):
    db = boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"])
    record = db.get_item(Key={"pk": "GAMES", "sk": game}, ConsistentRead=True).get("Item")
    if not record:
        raise ValueError("Game not found")
    from visual_styles import STYLES

    facts = {
        key: record[key]
        for key in ("id", "name", "ruleset", "purpose", "description", "visualStyle")
        if key in record
    }
    return {
        "game": facts,
        "visualStyles": [style for style in STYLES if style["id"] == facts.get("visualStyle")],
    }


def episode_destination_writes(record, *, previous=None):
    import episode_destination
    import browse_index
    return episode_destination.writes(browse_index.table(), record, previous=previous)


def submit(body):
    legacy = set(body) == {"gameId", "rawKey"}
    if not legacy and set(body) != {"gameId", "creation"}:
        raise ValueError("Expected gameId and rawKey or a creation request")
    if not media._valid_slug(body["gameId"]):
        raise ValueError("Invalid game")
    creation, selected_scene, chapter_source = None, None, None
    if legacy:
        source_keys, context_keys = [body["rawKey"]], []
    else:
        creation = body["creation"]
        version = creation.get("schemaVersion") if isinstance(creation, dict) else None
        fields = {"schemaVersion", "target", "title", "brief", "sourceKeys", "contextKeys"}
        if version == 4:
            if set(creation) != {"schemaVersion", "target", "chapterId"} or creation["target"] != "video" or not re.fullmatch(r"[a-f0-9]{64}", creation.get("chapterId", "")):
                raise ValueError("Choose a novel chapter to adapt")
            import manual_chapters
            import novel

            chapter = manual_chapters.read(body["gameId"], creation["chapterId"], media)
            if not chapter:
                chapter_job = read("RUNS", creation["chapterId"])
                if not chapter_job or chapter_job.get("gameId") != body["gameId"]:
                    raise ValueError("Choose a chapter from this game")
                chapter = novel.chapter(chapter_job)
            if not chapter or chapter.get("gameId") != body["gameId"]:
                raise ValueError("Chapter is not ready for adaptation")
            chapter_source, _ = asset(chapter["details"]["artifact"]["key"], body["gameId"], maximum=512 * 1024)
            roster = boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"]).query(KeyConditionExpression=Key("pk").eq(f"GAME#{body['gameId']}") & Key("sk").begins_with("CHARACTER#"), Limit=21, ConsistentRead=True)
            if roster.get("LastEvaluatedKey") or len(roster.get("Items", [])) > 20:
                raise ValueError("Episode adaptation requires a bounded character roster")
            creation = {**creation, "title": chapter["title"], "brief": "Adapt the supplied novel chapter into an episode, preserving its story outcomes.", "sourceKeys": [], "contextKeys": [], "characterIds": sorted(character["id"] for character in roster.get("Items", []))}
            fields.update({"chapterId", "characterIds"})
        if version == 3:
            required = {"schemaVersion", "target", "brief", "sourceKeys", "contextKeys"}
            if (
                not required <= set(creation) <= required | {"title"}
                or creation["target"] != "novel"
            ):
                raise ValueError("Expected a prompt-led novel request")
            prompt = creation["brief"]
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("Choose a chapter prompt")
            # This is a transparent request label, not a claimed generated title.
            creation = {**creation, "title": creation.get("title", prompt.strip()[:160])}
        if version == 2:
            required = {
                "schemaVersion",
                "target",
                "sceneRef",
                "characterIds",
                "sourceKeys",
                "contextKeys",
            }
            if not required <= set(creation) or not set(creation) <= required | {"title", "brief", "storyboardShotRef"}:
                raise ValueError("Expected a scene-owned video creation request")
            ref = creation["sceneRef"]
            if (
                not isinstance(ref, dict)
                or set(ref) != {"episodeId", "sceneId", "revision"}
                or not media._valid_slug(ref["episodeId"])
                or not media._valid_slug(ref["sceneId"])
                or not isinstance(ref["revision"], str)
                or not re.fullmatch(r"[a-f0-9]{32}", ref["revision"])
            ):
                raise ValueError("Invalid scene reference")
            import video_scenes

            selected_scene = video_scenes.pin_scene(body["gameId"], ref)
            import episode_storyboards
            episode_storyboards.require_ready(selected_scene)
            if creation.get('storyboardShotRef'):
                import storyboard_videos
                reference = creation['storyboardShotRef']
                if not isinstance(reference, dict) or set(reference) != {'revision', 'shotId'}:
                    raise ValueError('Choose an exact storyboard shot revision')
                board, selected_shot = storyboard_videos.shot(selected_scene, reference['shotId'])
                if board['revision'] != reference['revision']:
                    raise ValueError('The storyboard changed; choose its current shot')
                fields.add('storyboardShotRef')
            prompt = creation.get("brief", "")
            if not isinstance(prompt, str):
                raise ValueError("Expected a scene prompt")
            creation = {
                **creation,
                "brief": prompt if prompt.strip() else selected_scene["name"],
                "title": creation.get("title", selected_scene["name"][:160]),
            }
            fields.update({"characterIds", "sceneRef"})
        if (
            not isinstance(creation, dict)
            or set(creation) != fields
            or type(version) is not int
            or version not in {1, 2, 3, 4}
            or creation["target"] not in {"novel", "video"}
            or version == 2
            and creation["target"] != "video"
            or not isinstance(creation["title"], str)
            or not 1 <= len(creation["title"].strip()) <= 160
            or not isinstance(creation["brief"], str)
            or len(creation["brief"]) > 4000
            or version == 2
            and not creation["brief"].strip()
        ):
            raise ValueError("Invalid creation request")
        if version == 2:
            ids = creation["characterIds"]
            if (
                not isinstance(ids, list)
                or len(ids) > 12
                or any(not media._valid_slug(i) for i in ids)
                or len(ids) != len(set(ids))
            ):
                raise ValueError("Invalid selected characters")
        source_keys, context_keys = creation["sourceKeys"], creation["contextKeys"]
        for keys, minimum, maximum in [
            (source_keys, 0 if version in {2, 3, 4} else 1, 8),
            (context_keys, 0, 12),
        ]:
            if (
                not isinstance(keys, list)
                or not minimum <= len(keys) <= maximum
                or any(not isinstance(key, str) for key in keys)
                or len(set(keys)) != len(keys)
            ):
                raise ValueError("Invalid selected inputs")
        if set(source_keys) & set(context_keys):
            raise ValueError("Transcript inputs and context must be distinct")
    references, raws, heads = [], [], []
    for key in source_keys:
        if not isinstance(key, str) or not key.endswith(".json"):
            raise ValueError("Expected structured raw transcript JSON")
        ref, head = asset(key, body["gameId"], maximum=16 * 1024**2)
        raw = document(ref)
        validate_raw(raw, body["gameId"])
        references.append(ref)
        raws.append(raw)
        heads.append(head)
    contexts = []
    for key in context_keys:
        if not key.endswith((".json", ".md", ".txt")):
            raise ValueError("Expected text context")
        ref, head = asset(key, body["gameId"], maximum=2 * 1024**2)
        stored = head.get("Metadata", {})
        details = json.loads(base64.b64decode(stored.get("panther", "e30=")))
        from creative_context import eligible

        if not eligible(stored.get("kind", ""), details):
            raise ValueError("Selected context is not eligible creative evidence")
        contexts.append({**ref, "kind": stored.get("kind", ""), "metadata": details})
    cast = (
        pin_cast(body["gameId"], creation["characterIds"])
        if creation and creation["schemaVersion"] in {2, 4}
        else []
    )
    game_context = pin_game(body["gameId"]) if creation and creation["schemaVersion"] in {2, 4} else None
    selected_map = pin_map(body["gameId"], selected_scene)
    snapshot_size = len(
        json.dumps([cast, game_context, selected_scene, selected_map], default=str).encode()
    )
    if snapshot_size > 256 * 1024:
        raise ValueError("Selected character snapshots exceed the durable job limit")
    if (
        creation
        and sum(ref["size"] for ref in [*references, *contexts]) + snapshot_size > 512 * 1024
    ):
        raise ValueError("Selected input bundle exceeds the stage context limit")
    identity = (
        [references, contexts, creation, cast, game_context, selected_scene, PLAN["version"]]
        if creation
        else [references[0], PLAN["version"]]
    )
    if selected_map is not None:
        identity.append(selected_map)
    if chapter_source:
        identity.append(chapter_source)
    job_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    job = {
        "pk": "RUNS",
        "sk": job_id,
        "jobId": job_id,
        "gameId": body["gameId"],
        "sessionId": raws[0]["sessionId"]
        if len(raws) == 1
        else "collection-" + job_id[:16]
        if raws
        else None,
        "raw": references[0] if references else None,
        "sourceMode": "transcript" if references else "prompt",
        "workflowVersion": PLAN["version"],
        "status": "SUBMITTED",
        "createdAt": int(time.time()),
        "contextCutoff": int(
            max((media._asset_created_at(h).timestamp() for h in heads), default=time.time())
        ),
        "videoGenerationAuthorized": False,
    }
    if creation:
        job.update(
            creation=creation,
            rawSources=references,
            selectedContext=contexts,
            selectedCharacters=cast,
            gameContext=game_context,
            selectedScene=selected_scene,
            selectedMap=selected_map,
        )
    if selected_scene and not creation.get("storyboardShotRef"):
        job["episodeDestination"] = True
    destination = None
    if chapter_source or not creation:
        from episode_destination import placeholder
        job.update(episodeDestination=True)
        if chapter_source:
            job["chapterSource"] = chapter_source
        destination = placeholder(job)
        job["episodeRef"] = {"episodeId": destination["id"], "revision": destination["revision"]}
    try:
        import asset_archive
        from boto3.dynamodb.types import TypeSerializer

        serializer = TypeSerializer()
        stored_job = json.loads(json.dumps(job), parse_float=Decimal)
        pinned = [ref["key"] for ref in [*references, *contexts]]
        if chapter_source:
            pinned.append(chapter_source["key"])
        if selected_map:
            pinned.append(selected_map["key"])
        for character in cast:
            pinned.extend(ref["key"] for ref in character.get("appearanceAssets", []))
            if character.get("details", {}).get("thumbnailAssetKey"):
                pinned.append(character["details"]["thumbnailAssetKey"])
        boto3.client("dynamodb").transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": table.name,
                        "Item": {key: serializer.serialize(value) for key, value in stored_job.items()},
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                *asset_archive.reference_writes(
                    body["gameId"],
                    "editorial:" + job_id,
                    pinned,
                    {"table": table.name, "pk": "RUNS", "sk": job_id},
                ),
                *(episode_destination_writes(destination) if destination else []),
            ]
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {
            "ConditionalCheckFailedException",
            "TransactionCanceledException",
        }:
            raise
    return public(read("RUNS", job_id))


def context_page(game, cursor, cutoff):
    if not media._valid_slug(game):
        raise ValueError("Invalid game")
    from browse_index import page

    result = page(game, "all", cursor)
    items = []
    for item in result["assets"]:
        key = item["key"]
        if not key.endswith((".json", ".md", ".txt")) or not 0 < item.get("size", 0) <= 256 * 1024:
            continue
        details = item.get("metadata", {})
        kind = item.get("kind", "")
        from creative_context import eligible

        if not eligible(kind, details):
            continue
        ref, head = asset(key, game)
        if media._asset_created_at(head).timestamp() > cutoff:
            continue
        stored = head.get("Metadata", {})
        kind = stored.get("kind", kind)
        details = json.loads(base64.b64decode(stored.get("panther", "e30=")))
        if eligible(kind, details):
            items.append(
                {
                    **ref,
                    "kind": kind,
                    "metadata": details,
                    "lastModified": media._asset_created_at(head).isoformat(),
                }
            )
    return {"items": items, "cursor": result["cursor"]}


def claim(actor, version=1):
    if type(version) is not int or version < 1:
        raise ValueError("Invalid worker version")
    now = int(time.time())
    for task in query("TASKS"):
        if (
            task["status"] not in {"QUEUED", "RUNNING"}
            or task.get("leaseUntil", 0) > now
            or task.get("notBefore", 0) > now
        ):
            continue
        job = read("RUNS", task["jobId"])
        if job["status"] in TERMINAL or job["workflowVersion"] != version:
            continue
        if job["createdAt"] + 31 * 86400 <= now:
            internal({"jobId": job["jobId"], "operation": "fail"})
            continue
        if task.get("attempts", 0) >= 3:
            table.update_item(
                Key={"pk": "TASKS", "sk": task["sk"]},
                UpdateExpression="SET #s = :failed",
                ConditionExpression="#s = :old AND leaseUntil <= :now",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":failed": "FAILED",
                    ":old": task["status"],
                    ":now": now,
                },
            )
            continue
        lease = uuid.uuid4().hex
        try:
            updated = table.update_item(
                Key={"pk": "TASKS", "sk": task["sk"]},
                UpdateExpression="SET #s = :running, leaseUntil = :until, lease = :lease, actor = :actor ADD attempts :one",
                ConditionExpression="#s = :old AND leaseUntil <= :now",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":running": "RUNNING",
                    ":until": now + 600,
                    ":lease": lease,
                    ":actor": actor,
                    ":one": 1,
                    ":old": task["status"],
                    ":now": now,
                },
                ReturnValues="ALL_NEW",
            )["Attributes"]
            return {
                "task": public(updated),
                "job": public(job),
                "lease": lease,
                "artifacts": {
                    t["stage"]: t["output"]
                    for t in query("TASKS")
                    if t["jobId"] == job["jobId"] and t["status"] == "DONE"
                },
            }
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {
                "ConditionalCheckFailedException",
                "TransactionCanceledException",
            }:
                raise
    return {"task": None}


def owned(body, actor):
    job_id, stage = body["jobId"], body["stage"]
    if not re.fullmatch(r"[a-f0-9]{64}", job_id) or stage not in STAGES:
        raise ValueError("Invalid stage")
    task = read("TASKS", f"{job_id}:{stage}")
    if (
        not task
        or task.get("lease") != body["lease"]
        or task.get("actor") != actor
        or task["status"] != "RUNNING"
        or task["leaseUntil"] <= time.time()
        or read("RUNS", job_id)["status"] in TERMINAL
    ):
        raise ValueError("Expired or foreign lease")
    return task


def publish_episode(job, result, ref, task, body):
    import episode_destination
    import browse_index
    import organization_records
    episode, scenes = episode_destination.records(job, result, ref)
    pointer = organization_records.pointer("episode-scenes-v1", job["gameId"], "episode", episode["id"])
    current = organization_records.decode(browse_index.table().get_item(Key=pointer, ConsistentRead=True).get("Item"))
    # Safe retry after publication but before task completion. A later
    # human edit is never overwritten by replaying a worker callback.
    published = browse_index.table().get_item(Key={"pk": f"episode-scenes-v1-history#episode#{job['gameId']}#{episode['id']}", "sk": episode["revision"]}, ConsistentRead=True).get("Item")
    if published:
        if organization_records.decode(published) != episode:
            raise ValueError("Episode publication history conflicts")
    else:
        if not current or current["revision"] != job["episodeRef"]["revision"]:
            raise ValueError("Episode changed while planning; retained plan requires reconciliation")
        import asset_archive
        source_keys = sorted({ref["key"], *[key for scene in scenes for key in scene["productionSource"]["referenceKeys"]]})
        operations = [
            *episode_destination_writes(episode, previous=job["episodeRef"]["revision"]),
            *[operation for scene in scenes for operation in episode_destination_writes(scene)],
            {"ConditionCheck": {"TableName": table.name,
                "Key": organization_records.encode({"pk": "TASKS", "sk": task["sk"]}),
                "ConditionExpression": "lease = :l AND leaseUntil > :n AND #s = :r AND actor = :a",
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": organization_records.encode({":l": body["lease"], ":n": int(time.time()), ":r": "RUNNING", ":a": task["actor"]})}},
            *asset_archive.reference_writes(job["gameId"], "episode-production:" + episode["id"], source_keys,
                {"table": browse_index.table().name, **pointer})]
        if len(operations) > 100:
            raise ValueError("Episode publication exceeds the bounded transaction limit")
        boto3.client("dynamodb").transact_write_items(TransactItems=operations)


def update(task, body, operation):
    now = int(time.time())
    values = {":lease": body["lease"], ":now": now, ":running": "RUNNING"}
    expression = "SET leaseUntil = :until"
    values[":until"] = now + 600
    if operation == "defer":
        expression = "SET #s = :queued, leaseUntil = :until, notBefore = :later ADD attempts :minus"
        values.update({":queued": "QUEUED", ":until": 0, ":later": now + 3600, ":minus": -1})
    elif operation == "complete":
        ref, _ = asset(body["outputKey"], task["gameId"])
        prefix = f"games/{task['gameId']}/assets/editorial-{task['jobId'][:32]}-"
        if not ref["key"].startswith(prefix):
            raise ValueError("Output must belong to this run")
        result = document(ref)
        if (
            result.get("jobId") != task["jobId"]
            or result.get("stage") != task["stage"]
            or result.get("workflowVersion") != read("RUNS", task["jobId"])["workflowVersion"]
            or result.get("videoGenerationAuthorized") is not False
        ):
            raise ValueError("Invalid editorial artifact envelope")
        accepted = result.get("passed") is True
        if result["workflowVersion"] >= 2:
            if result.get("structuralValidation") != "passed" or result.get(
                "publicationStatus"
            ) not in {"accepted", "accepted-with-notes"}:
                raise ValueError("Missing validated publication decision")
            if result["publicationStatus"] == "accepted" and not accepted:
                raise ValueError("Failed review cannot claim unconditional acceptance")
            accepted = True
        job = read("RUNS", task["jobId"])
        if accepted and task["stage"] == "video-generation-packets" and job.get("episodeDestination"):
            import browse_index
            import organization_records

            if job.get("selectedScene"):
                from episode_destination import scene_record
                scene = scene_record(job, result, ref)
                pointer = organization_records.pointer("episode-scenes-v1", job["gameId"], "scene#" + scene["episodeId"], scene["id"])
                current = organization_records.decode(browse_index.table().get_item(Key=pointer, ConsistentRead=True).get("Item"))
                historical = browse_index.table().get_item(Key={"pk": f"episode-scenes-v1-history#scene#{scene['episodeId']}#{job['gameId']}#{scene['id']}", "sk": scene["revision"]}, ConsistentRead=True).get("Item")
                if historical:
                    if organization_records.decode(historical) != scene:
                        raise ValueError("Scene production history conflicts")
                else:
                    if not current or current["revision"] != job["selectedScene"]["revision"]:
                        raise ValueError("Scene changed while planning; retained plan requires reconciliation")
                    import asset_archive
                    operations = [*episode_destination_writes(scene, previous=current["revision"]),
                        {"ConditionCheck": {"TableName": table.name, "Key": organization_records.encode({"pk": "TASKS", "sk": task["sk"]}),
                            "ConditionExpression": "lease = :l AND leaseUntil > :n AND #s = :r",
                            "ExpressionAttributeNames": {"#s": "status"},
                            "ExpressionAttributeValues": organization_records.encode({":l": body["lease"], ":n": int(time.time()), ":r": "RUNNING"})}},
                        *asset_archive.reference_writes(job["gameId"], "scene-production:" + scene["episodeId"] + ":" + scene["id"], [ref["key"], *scene["productionSource"]["referenceKeys"]], {"table": browse_index.table().name, **pointer})]
                    boto3.client("dynamodb").transact_write_items(TransactItems=operations)
            else:
                publish_episode(job, result, ref, task, body)
        expression = "SET #s = :done, #output = :output, leaseUntil = :until"
        values.update(
            {
                ":done": "DONE" if accepted else "FAILED",
                ":output": ref,
                ":until": 0,
            }
        )
    table.update_item(
        Key={"pk": "TASKS", "sk": task["sk"]},
        UpdateExpression=expression,
        ConditionExpression="lease = :lease AND leaseUntil > :now AND #s = :running",
        ExpressionAttributeNames={
            "#s": "status",
            **({"#output": "output"} if operation == "complete" else {}),
        },
        ExpressionAttributeValues=values,
    )
    return {"ok": True}


def internal(event):
    job_id = event["jobId"]
    job = read("RUNS", job_id)
    if not job:
        raise ValueError("Missing run")
    if event["operation"] == "dispatch":
        stage = event["stage"]
        if stage not in STAGES or job["status"] in TERMINAL:
            raise ValueError("Invalid dispatch")
        task = {
            "pk": "TASKS",
            "sk": f"{job_id}:{stage}",
            "jobId": job_id,
            "gameId": job["gameId"],
            "stage": stage,
            "status": "QUEUED",
            "taskToken": event["taskToken"],
            "leaseUntil": 0,
            "attempts": 0,
        }
        try:
            table.put_item(Item=task, ConditionExpression="attribute_not_exists(pk)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {
                "ConditionalCheckFailedException",
                "TransactionCanceledException",
            }:
                raise
            if read("TASKS", task["sk"])["taskToken"] != event["taskToken"]:
                raise ValueError("Refusing mismatched stage token")
    else:
        status = (
            (
                "NOVEL_READY"
                if job.get("creation", {}).get("target") == "novel"
                else "READY_FOR_VIDEO_DISCUSSION"
            )
            if event["operation"] == "finish"
            else "FAILED"
        )
        table.update_item(
            Key={"pk": "RUNS", "sk": job_id},
            UpdateExpression="SET #s = :status",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":status": status},
        )
    return {}


def handler(event, _context):
    if "operation" in event and "requestContext" not in event:
        return internal(event)
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    from access_policy import authorized

    read_only = event.get("routeKey") == "GET /editorial-jobs"
    if not authorized(claims, "CATALOG_READERS" if read_only else "MODEL_PUBLISHERS"):
        return response(403, {"error": "This account cannot access editorial jobs"})
    try:
        route = event.get("routeKey", "")
        q = event.get("queryStringParameters") or {}
        if route == "GET /editorial-jobs":
            if q.get("jobId"):
                job = read("RUNS", q["jobId"])
                return (
                    response(
                        200,
                        {
                            "job": public(job),
                            "tasks": [
                                public(t) for t in query("TASKS") if t["jobId"] == job["jobId"]
                            ],
                        },
                    )
                    if job
                    else response(404, {"error": "Run not found"})
                )
            if q.get("gameId"):
                game = q["gameId"]
                if not media._valid_slug(game):
                    raise ValueError("Invalid game")
                args = {
                    "KeyConditionExpression": Key("pk").eq("RUNS"),
                    "Limit": 50,
                    "ConsistentRead": True,
                }
                if q.get("cursor"):
                    cursor = json.loads(base64.urlsafe_b64decode(q["cursor"]))
                    if (
                        set(cursor) != {"gameId", "sk"}
                        or cursor["gameId"] != game
                        or not re.fullmatch(r"[a-f0-9]{64}", cursor["sk"])
                    ):
                        raise ValueError("Invalid game cursor")
                    args["ExclusiveStartKey"] = {"pk": "RUNS", "sk": cursor["sk"]}
                page = table.query(**args)
                next_key = page.get("LastEvaluatedKey")
                return response(
                    200,
                    {
                        "jobs": [public(j) for j in page.get("Items", []) if j["gameId"] == game],
                        "cursor": base64.urlsafe_b64encode(
                            json.dumps({"gameId": game, "sk": next_key["sk"]}).encode()
                        ).decode()
                        if next_key
                        else None,
                    },
                )
            return response(200, {"jobs": [public(j) for j in query("RUNS")]})
        if route == "GET /editorial-context":
            job = read("RUNS", q["jobId"])
            if not job:
                raise ValueError("Missing job")
            return response(200, context_page(job["gameId"], q.get("cursor"), job["contextCutoff"]))
        raw = event.get("body") or "{}"
        if len(raw) > 20000:
            raise ValueError("Request too large")
        body = json.loads(base64.b64decode(raw) if event.get("isBase64Encoded") else raw)
        if route == "POST /editorial-jobs":
            return response(200, submit(body))
        if not authorized(claims, "MODEL_WORKERS"):
            return response(403, {"error": "Only the owner's laptop can process stages"})
        if route == "POST /editorial-jobs/claim":
            return response(200, claim(claims["sub"], body.get("workflowVersion", 1)))
        operation = route.removeprefix("POST /editorial-jobs/")
        if operation not in {"heartbeat", "defer", "complete"}:
            return response(404, {"error": "Unknown operation"})
        return response(200, update(owned(body, claims["sub"]), body, operation))
    except (ValueError, TypeError, KeyError) as error:
        message = (
            str(error)
            if event.get("routeKey") == "POST /editorial-jobs" and type(error) is ValueError
            else "Invalid artifact, context request, or stage lease"
        )
        return response(400, {"error": message})
    except ClientError as exc:
        return response(
            409 if exc.response["Error"]["Code"] == "ConditionalCheckFailedException" else 503,
            {"error": "Editorial state changed or storage unavailable; inspect before retrying"},
        )


def stream(event, _context):
    failures = []
    decoder = TypeDeserializer()
    for record in event.get("Records", []):
        try:
            data = record["dynamodb"]
            new = {k: decoder.deserialize(v) for k, v in data.get("NewImage", {}).items()}
            old = {k: decoder.deserialize(v) for k, v in data.get("OldImage", {}).items()}
            if new.get("status") == old.get("status"):
                continue
            if new.get("pk") == "RUNS" and new.get("status") == "SUBMITTED":
                try:
                    states.start_execution(
                        stateMachineArn=os.environ["STATE_MACHINE_ARN"],
                        name=new["jobId"],
                        input=json.dumps(
                            {
                                "jobId": new["jobId"],
                                "target": new.get("creation", {}).get("target", "both"),
                                "sourceMode": new.get("sourceMode", "transcript"),
                            }
                        ),
                    )
                except ClientError as exc:
                    if exc.response["Error"]["Code"] != "ExecutionAlreadyExists":
                        raise
            elif new.get("pk") == "TASKS" and new.get("status") in {"DONE", "FAILED"}:
                try:
                    states.send_task_success(
                        taskToken=new["taskToken"], output=json.dumps({"status": new["status"]})
                    )
                except ClientError as exc:
                    if exc.response["Error"]["Code"] not in {
                        "TaskDoesNotExist",
                        "TaskTimedOut",
                        "InvalidToken",
                    }:
                        raise
        except Exception:
            failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})
    return {"batchItemFailures": failures}
