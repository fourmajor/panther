"""Versioned workflow observation. No execution, asset scans, tokens or paid requests."""

import base64
import json
import os
import re
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from workflow_hierarchy import summary
from tag_management import timestamp
from botocore.exceptions import ClientError
from access_policy import authorized

DB = boto3.resource("dynamodb")
TX = boto3.client("dynamodb")
INDEX = DB.Table(os.environ["WORKSHOP_TABLE"])
SOURCES = json.loads(os.environ["WORKSHOP_SOURCES"])
PLAN = json.loads(os.environ["WORKSHOP_PLAN"])
KINDS = (*SOURCES, "video-production", "video-generation", "session-finalization")
STATE = {"pk": "SYSTEM", "sk": "workshop-v1"}
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
STATES = {"pending", "queued", "running", "done", "failed", "paused", "unknown"}


def reply(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "body": json.dumps(body, default=lambda v: float(v) if isinstance(v, Decimal) else str(v))}


def get(table, pk, sk):
    return table.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item")


def encode(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


def decode(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("Invalid cursor")
    result = json.loads(base64.urlsafe_b64decode(value))
    if not isinstance(result, dict):
        raise ValueError("Invalid cursor")
    return result


def status(value):
    return {"SUBMITTED": "queued", "QUEUED": "queued", "RUNNING": "running", "PUBLISHING": "running",
            "DONE": "done", "PUBLISHED": "done", "NOVEL_READY": "done", "READY_FOR_VIDEO_DISCUSSION": "done",
            "FAILED": "failed", "SUPERSEDED": "paused", "CONFLICT": "paused", "UNKNOWN": "unknown"}.get(value, "unknown")


def phase(name, state, item=None):
    item = item or {}
    return {"id": name, "label": name.replace("-", " ").capitalize(), "status": state,
            **{field: item[field] for field in ("leaseUntil", "notBefore", "attempts") if field in item},
            **({"outputKey": item["output"]["key"]} if isinstance(item.get("output"), dict) and item["output"].get("key") else {})}


def source_view(kind, key):
    table = DB.Table(SOURCES[kind]["name"])
    item = get(table, key["pk"], key["sk"])
    if not item:
        return None
    if kind == "editorial":
        job_id = item.get("jobId")
        if not job_id or item["pk"] not in {"RUNS", "TASKS"}:
            return None
        job = get(table, "RUNS", job_id)
        if not job:
            return None
        page = table.query(KeyConditionExpression=Key("pk").eq("TASKS") & Key("sk").begins_with(job_id + ":"), Limit=100, ConsistentRead=True)
        if page.get("LastEvaluatedKey"):
            raise ValueError("Editorial stage inventory exceeds supported bound")
        tasks = {t["stage"]: t for t in page.get("Items", [])}
        target = job.get("target", job.get("creation", {}).get("target"))
        video = [name for name in PLAN["video"] if name != "video-source-brief" or job.get("workflowVersion", 1) >= 4]
        names = PLAN["correction"] + (PLAN["novel"] if target != "video" else []) + (video if target != "novel" else [])
        stages = [phase(name, status(tasks[name]["status"]) if name in tasks else "pending", tasks.get(name)) for name in names]
        title = job.get("creation", {}).get("title") or "Transcript → story & screen planning"
        note = "Screen planning ends before paid video generation. Approval of the exact script/storyboard is required; completed planning never authorizes spending." if target != "novel" else "Novel adaptation; raw evidence remains unchanged."
    elif kind in {"model", "playback"}:
        if item["pk"] != ("JOBS" if kind == "model" else "SETS") or not item.get("jobId"):
            return None
        job = item
        stages = [phase("reconstruction-review-publication" if kind == "model" else "assemble-verify-publish", status(job["status"]), job)]
        title = ("3D model · " + job.get("characterId", "Character")) if kind == "model" else "Continuous audio playback"
        note = "This worker reports one combined stage; finer progress is not reported."
    else:
        match = re.fullmatch(rf"({SLUG})#(recording-[a-f0-9]{{32}})", item["pk"])
        if not match or (not item["sk"].startswith("FINAL") and item.get("mode") != "final"):
            return None
        game, recording = match.groups()
        plan = get(table, item["pk"], "FINAL-PLAN")
        if not plan:
            return None
        page = table.query(KeyConditionExpression=Key("pk").eq(item["pk"]) & Key("sk").begins_with("FINAL#"), Limit=200, ConsistentRead=True)
        if page.get("LastEvaluatedKey"):
            raise ValueError("Transcription window inventory exceeds supported bound")
        windows = sorted(page.get("Items", []), key=lambda w: w.get("start", 0))
        final = get(table, item["pk"], "FINAL-TRANSCRIPT")
        stages = [phase(f"transcription-window-{i + 1}", status(w["status"])) for i, w in enumerate(windows)]
        for i in range(len(windows), int(plan["groupCount"])):
            stages.append(phase(f"transcription-window-{i + 1}", "pending"))
        stages.append(phase("preserve-final-transcript", "done" if final else "pending"))
        state = "DONE" if final else "FAILED" if any(w["status"] == "FAILED" for w in windows) else "RUNNING" if any(w["status"] == "RUNNING" for w in windows) else "UNKNOWN" if any(w["status"] == "UNKNOWN" for w in windows) else "QUEUED"
        job = {"jobId": recording, "gameId": game, "status": state, "createdAt": min((w.get("createdAt", 0) for w in windows), default=0)}
        title = "Final transcription · " + plan.get("sessionName", "Recording")
        note = "Speakers are unassigned until a separate player-attribution step."
    return {"schemaVersion": 1, "id": kind + "~" + job["jobId"], "kind": kind, "gameId": job["gameId"],
            "title": title[:240], "status": status(job["status"]), "sourceStatus": job["status"],
            "createdAt": job.get("createdAt", 0), "sessionId": job.get("sessionId"), "stages": stages,
            "note": note, "observedAt": int(time.time()), "source": "durable-job", "workflowVersion": job.get("workflowVersion")}


def type_inventory(game, kind):
    """Bounded indexing-only backfill; browsing never enumerates run history."""
    rows, cursor = [], None
    for _ in range(100):
        args = {"KeyConditionExpression": Key("pk").eq("GAME#" + game) & Key("sk").begins_with(kind + "~"), "Limit": 100, "ConsistentRead": True}
        if cursor:
            args["ExclusiveStartKey"] = cursor
        page = INDEX.query(**args)
        rows.extend(page.get("Items", []))
        cursor = page.get("LastEvaluatedKey")
        if not cursor:
            return rows
    raise ValueError("Workflow type exceeds supported rebuild bound")


def store(value, previous):
    item = {**value, "pk": "GAME#" + value["gameId"], "sk": value["id"], "revision": uuid.uuid4().hex}
    aggregate = get(INDEX, "TYPES#" + value["gameId"], value["kind"])
    if aggregate:
        counts = dict(aggregate["counts"])
        if previous:
            old = previous.get("status", "unknown")
            counts[old if old in counts else "unknown"] -= 1
        new = value.get("status", "unknown")
        counts[new if new in counts else "unknown"] += 1
        if any(n < 0 for n in counts.values()):
            raise ValueError("Workflow type requires a complete rebuild")
        totals = {**aggregate, "counts": counts, "total": sum(counts.values()), "successful": counts["done"], "failed": counts["failed"], "active": counts["running"] + counts["queued"], "latestRunAt": max(int(timestamp(aggregate.get("latestRunAt"))), int(timestamp(value.get("createdAt")))), "latestActivityAt": max(int(timestamp(aggregate.get("latestActivityAt"))), int(timestamp(value.get("reportedAt") or value.get("observedAt"))))}
    else:
        records = [row for row in type_inventory(value["gameId"], value["kind"]) if row["id"] != value["id"]]
        totals = summary(value["kind"], [*records, value])
    totals.update(pk="TYPES#" + value["gameId"], sk=value["kind"], revision=uuid.uuid4().hex)
    serializer = TypeSerializer()
    writes = []
    for new_item, old_item in ((item, previous), (totals, aggregate)):
        put = {"TableName": INDEX.name, "Item": serializer.serialize(new_item)["M"], "ConditionExpression": "revision = :previous" if old_item else "attribute_not_exists(pk)"}
        if old_item:
            put["ExpressionAttributeValues"] = {":previous": serializer.serialize(old_item["revision"])}
        writes.append({"Put": put})
    try:
        TX.transact_write_items(TransactItems=writes)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException" and all(reason.get("Code") in {"None", "ConditionalCheckFailed"} for reason in exc.response.get("CancellationReasons", [])):
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "Workflow hierarchy revision changed"}}, "PutItem") from exc
        raise
    return item


def project(kind, key):
    # Read sources again after every optimistic conflict: an old stream event cannot
    # overwrite a newer snapshot merely because delivery order differs across keys.
    for _ in range(4):
        value = source_view(kind, key)
        if not value:
            return
        previous = get(INDEX, "GAME#" + value["gameId"], value["id"])
        value = source_view(kind, key)
        try:
            store(value, previous)
            return
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    raise RuntimeError("Workflow projection conflict; retry safely")


def flow(item):
    """Read-time topology from the implemented pipeline, never inferred execution."""
    ids = [stage["id"] for stage in item["stages"]]
    lanes, edges = [], []
    if item["kind"] == "editorial":
        common = [name for name in ids if not name.startswith(("novel-", "video-"))]
        branches = [("novel", "Novel adaptation", [name for name in ids if name.startswith("novel-")]),
                    ("video", "Screen planning", [name for name in ids if name.startswith("video-")])]
        if common:
            lanes.append({"id": "shared", "label": "Shared context & correction", "stageIds": common})
        for identity, label, names in branches:
            if names:
                lanes.append({"id": identity, "label": label, "stageIds": names})
                if common:
                    edges.append({"from": common[-1], "to": names[0]})
        for lane in lanes:
            edges.extend({"from": a, "to": b} for a, b in zip(lane["stageIds"], lane["stageIds"][1:]))
        mode = "branched"
        note = "Adaptation branches may proceed independently after shared correction. Screen planning stops before paid generation."
    elif item["kind"] in {"video-generation", "transcription"}:
        independent = ids[:-1] if item["kind"] == "transcription" else ids
        lanes = [{"id": name, "label": "Independent task", "stageIds": [name]} for name in independent]
        if item["kind"] == "transcription":
            lanes.append({"id": "join", "label": "After all windows", "stageIds": ids[-1:]})
            edges = [{"from": name, "to": ids[-1]} for name in independent]
        mode = "independent"
        note = "Tasks have no dependency on one another. This does not imply simultaneous execution or permission to generate."
        if item["kind"] == "video-generation" and "storyboard-approval" in ids:
            shots = [name for name in ids if name != "storyboard-approval"]
            lanes = [{"id": "approval", "label": "Owner approval", "stageIds": ["storyboard-approval"]}] + [{"id": name, "label": "Independent shot", "stageIds": [name]} for name in shots]
            edges = [{"from": "storyboard-approval", "to": name} for name in shots]
            note = "Owner storyboard approval gates generation; shots are independent after that checkpoint."
    else:
        lanes = [{"id": "sequence", "label": "Reported steps", "stageIds": ids}]
        edges = [{"from": a, "to": b} for a, b in zip(ids, ids[1:])]
        mode, note = "sequence", "Arrows show step order, not time remaining."
    return {"schemaVersion": 1, "mode": mode, "lanes": lanes, "edges": edges, "note": note}


def public(item, detail=False):
    allowed = {"schemaVersion", "id", "kind", "gameId", "title", "status", "sourceStatus", "createdAt", "sessionId", "note", "observedAt", "source", "workflowVersion", "reportedAt", "revision"}
    result = {k: v for k, v in item.items() if k in allowed}
    stages = item["stages"]
    result.update(completedStages=sum(s["status"] == "done" for s in stages), totalStages=len(stages),
                  activeStages=[s for s in stages if s["status"] in {"running", "queued", "failed", "paused", "unknown"}])
    if detail:
        result["stages"] = stages
        result["flow"] = flow(item)
    return result


def handler(event, _context):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    route = event.get("routeKey")
    if not authorized(claims, "CATALOG_READERS" if route == "GET /workflows" else "MODEL_WORKERS"):
        return reply(403, {"error": "Workflow access denied"})
    try:
        if route == "POST /workflow-progress":
            if len(event.get("body") or "") > 65536:
                raise ValueError("Progress report too large")
            body = json.loads(event.get("body") or "{}")
            if set(body) != {"kind", "gameId", "runId", "title", "stages", "status", "expectedRevision"} or body["kind"] not in {"video-production", "video-generation", "session-finalization"}:
                raise ValueError("Invalid progress envelope")
            if len(body["gameId"]) > 96 or not re.fullmatch(SLUG, body["gameId"]) or not re.fullmatch(r"[a-f0-9]{64}", body["runId"]):
                raise ValueError("Invalid workflow identity")
            if body["status"] not in STATES or not isinstance(body["title"], str) or not 0 < len(body["title"]) <= 240:
                raise ValueError("Invalid progress summary")
            if not isinstance(body["stages"], list) or not 0 < len(body["stages"]) <= 100:
                raise ValueError("Invalid stages")
            ids = set()
            for stage in body["stages"]:
                if set(stage) != {"id", "label", "status"} or not re.fullmatch(SLUG, stage["id"]) or stage["status"] not in STATES or not isinstance(stage["label"], str) or not 0 < len(stage["label"]) <= 160 or stage["id"] in ids:
                    raise ValueError("Invalid stage record")
                ids.add(stage["id"])
            identity = body["kind"] + "~" + body["runId"]
            previous = get(INDEX, "GAME#" + body["gameId"], identity)
            if (previous or {}).get("revision") != body["expectedRevision"]:
                return reply(409, {"error": "Progress revision changed"})
            note = "Local finalization report; adaptation progress appears in the linked story/screen workflow. Video stops for storyboard approval." if body["kind"] == "session-finalization" else "Local report; generation completion is not final movie delivery or quality approval."
            item = store({"schemaVersion": 1, "id": identity, "kind": body["kind"], "gameId": body["gameId"], "title": body["title"], "status": body["status"], "stages": body["stages"], "createdAt": (previous or {}).get("createdAt", int(time.time())), "reportedAt": int(time.time()), "source": "local-worker", "note": note}, previous)
            return reply(200, {"workflow": public(item, True)})
        if route != "GET /workflows":
            return reply(404, {"error": "Unknown workflow route"})
        q = event.get("queryStringParameters") or {}
        game = q.get("gameId", "")
        if not re.fullmatch(SLUG, game):
            raise ValueError("Invalid game")
        if q.get("id"):
            if not re.fullmatch(r"(?:editorial|model|playback|transcription|video-production|video-generation|session-finalization)~[a-z0-9-]{1,80}", q["id"]):
                raise ValueError("Invalid workflow ID")
            item = get(INDEX, "GAME#" + game, q["id"])
            return reply(200, {"workflow": public(item, True)}) if item else reply(404, {"error": "Workflow not found in this game"})
        marker = get(INDEX, **STATE)
        if not marker or set(marker.get("sources", [])) != set(SOURCES):
            return reply(503, {"error": "Workflow history is being indexed; the library is not complete yet."})
        if q.get("view") == "types":
            if marker.get("hierarchyVersion") != 1:
                return reply(503, {"error": "Workflow types are being indexed; totals are not complete yet."})
            page = INDEX.query(KeyConditionExpression=Key("pk").eq("TYPES#" + game), Limit=30, ConsistentRead=True)
            if page.get("LastEvaluatedKey"):
                return reply(503, {"error": "Workflow type inventory exceeds its supported bound."})
            return reply(200, {"schemaVersion": 1, "types": [{k: v for k, v in item.items() if k not in {"pk", "sk", "revision"}} for item in page.get("Items", [])]})
        kind = q.get("type")
        if q.get("view") == "runs" and kind not in KINDS:
            raise ValueError("Unknown workflow type")
        condition = Key("pk").eq("GAME#" + game)
        if q.get("view") == "runs":
            condition &= Key("sk").begins_with(kind + "~")
        args = {"KeyConditionExpression": condition, "Limit": 30, "ConsistentRead": True}
        if q.get("cursor"):
            cursor = decode(q["cursor"])
            if set(cursor) != {"pk", "sk"} or cursor["pk"] != "GAME#" + game or not isinstance(cursor["sk"], str) or q.get("view") == "runs" and not cursor["sk"].startswith(kind + "~"):
                raise ValueError("Foreign workflow cursor")
            args["ExclusiveStartKey"] = cursor
        page = INDEX.query(**args)
        return reply(200, {"workflows": [public(i) for i in page.get("Items", [])], "cursor": encode(page["LastEvaluatedKey"]) if page.get("LastEvaluatedKey") else None, "schemaVersion": 1})
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return reply(400, {"error": "Invalid workflow request"})
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return reply(409, {"error": "Workflow observation changed; retry with current revision"})
        raise


def project_handler(event, _context):
    if "Records" in event:
        failures = []
        for record in event["Records"]:
            try:
                kind = next(k for k, v in SOURCES.items() if record["eventSourceARN"].startswith(v["arn"] + "/stream/"))
                key = {k: TypeDeserializer().deserialize(v) for k, v in record["dynamodb"]["Keys"].items()}
                project(kind, key)
            except Exception:
                failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})
        return {"batchItemFailures": failures}
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "MODEL_WORKERS"):
        return reply(403, {"error": "Workflow indexing requires worker access"})
    try:
        body = json.loads(event.get("body") or "{}")
        kind = body["kind"]
        if kind == "hierarchy":
            args = {"Limit": 25, "ConsistentRead": True}
            if body.get("cursor"):
                pointer = decode(body["cursor"])
                if set(pointer) != {"kind", "key"} or pointer["kind"] != kind or set(pointer["key"]) != {"pk", "sk"}:
                    raise ValueError("Invalid hierarchy rebuild cursor")
                args["ExclusiveStartKey"] = pointer["key"]
            page = INDEX.scan(**args)
            for item in page.get("Items", []):
                if item.get("pk", "").startswith("GAME#") and item.get("kind") in KINDS:
                    store({k: v for k, v in item.items() if k not in {"pk", "sk", "revision"}}, item)
            last = page.get("LastEvaluatedKey")
            if not last:
                INDEX.update_item(Key=STATE, UpdateExpression="SET hierarchyVersion = :version", ExpressionAttributeValues={":version": 1})
            return reply(200, {"kind": kind, "inspected": len(page.get("Items", [])), "cursor": encode({"kind": kind, "key": last}) if last else None, "complete": not bool(last)})
        if kind not in SOURCES:
            raise ValueError("Invalid source")
        args = {"Limit": 25, "ConsistentRead": True, "ProjectionExpression": "pk, sk"}
        if body.get("cursor"):
            cursor = decode(body["cursor"])
            if set(cursor) != {"kind", "key"} or cursor["kind"] != kind or set(cursor["key"]) != {"pk", "sk"}:
                raise ValueError("Invalid rebuild cursor")
            args["ExclusiveStartKey"] = cursor["key"]
        page = DB.Table(SOURCES[kind]["name"]).scan(**args)
        for key in page.get("Items", []):
            project(kind, key)
        last = page.get("LastEvaluatedKey")
        if not last:
            INDEX.update_item(Key=STATE, UpdateExpression="ADD sources :source, hierarchySources :source", ExpressionAttributeValues={":source": {kind}})
        return reply(200, {"kind": kind, "inspected": len(page.get("Items", [])), "cursor": encode({"kind": kind, "key": last}) if last else None, "complete": not bool(last)})
    except (ValueError, TypeError, KeyError):
        return reply(400, {"error": "Invalid rebuild request or unsupported workflow inventory"})
