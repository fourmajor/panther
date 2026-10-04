"""Publish existing screen-pipeline output as the canonical owned Episode tree."""

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal

import episode_storyboards

VERSION = 1


def revision(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()[:32]


def placeholder(job):
    identity = "episode-" + job["jobId"][:24]
    timestamp = datetime.fromtimestamp(int(job["createdAt"]), timezone.utc).isoformat()
    return {
        "schemaVersion": 1,
        "entityType": "Episode",
        "gameId": job["gameId"],
        "id": identity,
        "name": (job.get("creation") or {}).get("title", "Session adaptation"),
        "description": "",
        "sceneIds": [],
        "revision": revision([VERSION, job["jobId"], "planning"]),
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "position": int(job["createdAt"]) * 1000,
        "production": {"schemaVersion": VERSION, "jobId": job["jobId"], "state": "planning"},
    }


def records(job, envelope, source):
    """Pure publication projection; exact originals remain pinned, never rewritten."""
    if (
        envelope.get("gameId") != job["gameId"]
        or envelope.get("jobId") != job["jobId"]
        or envelope.get("stage") != "video-generation-packets"
        or envelope.get("structuralValidation") != "passed"
        or envelope.get("publicationStatus") not in {"accepted", "accepted-with-notes"}
        or envelope.get("videoGenerationAuthorized") is not False
    ):
        raise ValueError("Episode publication requires the validated screen pipeline revision")
    payload = envelope["payload"]
    manifest, shots = payload["episode"], payload["shots"]
    if (
        manifest.get("schemaVersion") != VERSION
        or not isinstance(shots, list)
        or not 1 <= len(shots) <= 100
    ):
        raise ValueError("Invalid episode destination manifest")
    planned = manifest.get("scenes")
    if not isinstance(planned, list) or not 1 <= len(planned) <= 24:
        raise ValueError("Episode destination requires bounded owned scenes")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("key"), str)
        or not source["key"].startswith(f"games/{job['gameId']}/assets/")
        or not isinstance(source.get("sha256"), str)
        or not source["sha256"]
        or type(source.get("size")) is not int
        or not 0 < source["size"] <= 2 * 1024**2
    ):
        raise ValueError("Missing exact production source")
    episode = placeholder(job)
    for name, field, limit in [("name", "title", 160), ("description", "synopsis", 4000)]:
        text = manifest.get(field)
        if not isinstance(text, str) or not text.strip() or len(text) > limit:
            raise ValueError("Invalid episode destination text")
        episode[name] = text
    by_id = {shot["shotId"]: shot for shot in shots}
    if len(by_id) != len(shots):
        raise ValueError("Duplicate production shot identities")
    covered, scenes = [], []
    for index, definition in enumerate(planned):
        identity = definition.get("id")
        if (
            not isinstance(identity, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identity)
            or len(identity) > 64
            or identity in episode["sceneIds"]
        ):
            raise ValueError("Invalid owned scene identity")
        scene_shots = definition.get("shotIds")
        if (
            not isinstance(scene_shots, list)
            or not scene_shots
            or any(shot not in by_id for shot in scene_shots)
        ):
            raise ValueError("Scene must own existing planned shots")
        covered.extend(scene_shots)
        cast = {character["characterId"] for character in job.get("selectedCharacters", [])}
        characters, references = definition.get("characterIds"), definition.get("referenceKeys")
        if (
            not isinstance(characters, list)
            or any(not isinstance(value, str) for value in characters)
            or len(characters) != len(set(characters))
            or not set(characters) <= cast
            or not isinstance(references, list)
            or any(
                not isinstance(key, str) or key not in envelope["sourceKeys"] for key in references
            )
        ):
            raise ValueError("Scene references must match the exact production inputs")
        values = [
            {
                "shotId": "shot-" + revision(shot_id),
                "description": by_id[shot_id]["description"],
                "camera": by_id[shot_id]["camera"],
                "durationSeconds": by_id[shot_id]["durationSeconds"],
                "frameKey": None,
                "narration": "",
            }
            for shot_id in scene_shots
        ]
        board = episode_storyboards.create(values, job["gameId"], origin="ai", actor=job["jobId"])
        scene = {
            "schemaVersion": 1,
            "entityType": "Scene",
            "gameId": job["gameId"],
            "episodeId": episode["id"],
            "id": identity,
            "name": definition["title"],
            "description": definition["prompt"],
            "type": definition["type"],
            "narration": definition["narration"],
            "storyboard": board,
            "planningState": "needs-approval",
            "productionSource": {
                "artifact": copy.deepcopy(source),
                "shotIds": scene_shots,
                "plannedShots": [copy.deepcopy(by_id[shot]) for shot in scene_shots],
                "referenceKeys": copy.deepcopy(references),
            },
            "generationInputs": {
                "schemaVersion": 1,
                "characterIds": definition["characterIds"],
                "sourceKeys": [],
                "contextKeys": [],
            },
            "storyboardVideoVersion": 1,
            "shotTakes": {},
            "selectedOutputKey": None,
            "selectedOutputSceneRevision": None,
            "revision": revision([source, identity]),
            "position": index,
            "createdAt": episode["createdAt"],
            "updatedAt": episode["updatedAt"],
        }
        for field, limit in [("name", 160), ("description", 4000), ("narration", 5000)]:
            if (
                not isinstance(scene[field], str)
                or len(scene[field]) > limit
                or field != "narration"
                and not scene[field].strip()
            ):
                raise ValueError("Invalid owned scene direction")
        if scene["type"] not in {"general", "opener", "travel", "map", "action", "dialogue"}:
            raise ValueError("Invalid owned scene type")
        episode["sceneIds"].append(identity)
        scenes.append(scene)
    if covered != [shot["shotId"] for shot in shots]:
        raise ValueError("Episode scenes must partition the exact locked shot order")
    episode["previousRevision"] = episode["revision"]
    episode["revision"] = revision([source, "episode"])
    episode["production"].update(state="planned", artifact=copy.deepcopy(source))
    return episode, scenes


def writes(db, record, *, previous=None):
    """Canonical owned record plus immutable history in the caller's transaction."""
    import organization_records

    kind = "scene#" + record["episodeId"] if record["entityType"] == "Scene" else "episode"
    pointer = organization_records.pointer(
        "episode-scenes-v1", record["gameId"], kind, record["id"]
    )
    payload = json.dumps(record, separators=(",", ":"), allow_nan=False)
    if len(payload.encode()) > 64000:
        raise ValueError("Episode production record exceeds its bound")
    put = {
        "TableName": db.name,
        "Item": organization_records.encode(
            {**pointer, "revision": record["revision"], "payload": payload}
        ),
        "ConditionExpression": "revision = :old" if previous else "attribute_not_exists(pk)",
    }
    if previous:
        put["ExpressionAttributeValues"] = organization_records.encode({":old": previous})
    return [
        {"Put": put},
        {
            "Put": {
                "TableName": db.name,
                "Item": organization_records.encode(
                    {
                        "pk": f"episode-scenes-v1-history#{kind}#{record['gameId']}#{record['id']}",
                        "sk": record["revision"],
                        "payload": payload,
                    }
                ),
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
    ]


def scene_record(job, envelope, source):
    """Publish a scene-directed planning run into that scene, not another episode."""
    previous = job.get("selectedScene")
    if not previous or previous.get("gameId") != job["gameId"]:
        raise ValueError("Scene production requires its exact submitted revision")
    _, planned = records(job, envelope, source)
    if len(planned) != 1 or planned[0]["id"] != previous["id"]:
        raise ValueError("A scene-directed run must preserve its owned scene identity")
    result = json.loads(json.dumps(previous, default=lambda value: float(value) if isinstance(value, Decimal) else value))
    for field in ("storyboard", "narration", "productionSource", "planningState"):
        result[field] = planned[0][field]
    result.update(
        previousRevision=previous["revision"],
        revision=revision([source, previous["episodeId"], previous["id"]]),
    )
    return result
