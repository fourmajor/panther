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


def submit(body):
    legacy = set(body) == {"gameId", "rawKey"}
    if not legacy and set(body) != {"gameId", "creation"}:
        raise ValueError("Expected gameId and rawKey or a creation request")
    if not media._valid_slug(body["gameId"]):
        raise ValueError("Invalid game")
    creation = None
    if legacy:
        source_keys, context_keys = [body["rawKey"]], []
    else:
        creation = body["creation"]
        if (
            not isinstance(creation, dict)
            or set(creation)
            != {"schemaVersion", "target", "title", "brief", "sourceKeys", "contextKeys"}
            or type(creation["schemaVersion"]) is not int
            or creation["schemaVersion"] != 1
            or creation["target"] not in {"novel", "video"}
            or not isinstance(creation["title"], str)
            or not 1 <= len(creation["title"].strip()) <= 160
            or not isinstance(creation["brief"], str)
            or len(creation["brief"]) > 4000
        ):
            raise ValueError("Invalid creation request")
        source_keys, context_keys = creation["sourceKeys"], creation["contextKeys"]
        for keys, minimum, maximum in [(source_keys, 1, 8), (context_keys, 0, 12)]:
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
        if (
            details.get("extra", {}).get("contextUse") == "exclude"
            or stored.get("kind") in {"reading-script", "test-script", "holdout"}
            or details.get("category")
            in {"grounded-adaptation", "creative-reimagining", "playful-derivative"}
        ):
            raise ValueError("Selected context is not source evidence")
        if not (
            stored.get("kind")
            in {"corrected-transcript", "character-profile", "lore", "game-context"}
            or details.get("extra", {}).get("contextUse") == "evidence"
            or details.get("category") in {"canonical-source", "reference"}
        ):
            raise ValueError("Selected context is not eligible evidence")
        contexts.append({**ref, "kind": stored.get("kind", ""), "metadata": details})
    if creation and sum(ref["size"] for ref in [*references, *contexts]) > 512 * 1024:
        raise ValueError("Selected input bundle exceeds the stage context limit")
    identity = (
        [references, contexts, creation, PLAN["version"]]
        if creation
        else [references[0], PLAN["version"]]
    )
    job_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    job = {
        "pk": "RUNS",
        "sk": job_id,
        "jobId": job_id,
        "gameId": body["gameId"],
        "sessionId": raws[0]["sessionId"] if len(raws) == 1 else "collection-" + job_id[:16],
        "raw": references[0],
        "workflowVersion": PLAN["version"],
        "status": "SUBMITTED",
        "createdAt": int(time.time()),
        "contextCutoff": int(max(media._asset_created_at(h).timestamp() for h in heads)),
        "videoGenerationAuthorized": False,
    }
    if creation:
        job.update(creation=creation, rawSources=references, selectedContext=contexts)
    try:
        table.put_item(Item=job, ConditionExpression="attribute_not_exists(pk)")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
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
        ref, head = asset(key, game)
        if media._asset_created_at(head).timestamp() > cutoff:
            continue
        details = item.get("metadata", {})
        extra, kind = details.get("extra", {}), item.get("kind", "")
        if (
            extra.get("contextUse") == "exclude"
            or kind
            in {
                "reading-script",
                "test-script",
                "holdout",
                "raw-transcript",
                "editorial-failed-candidate",
            }
            or details.get("category")
            in {"grounded-adaptation", "creative-reimagining", "playful-derivative"}
        ):
            continue
        if (
            kind in {"corrected-transcript", "character-profile", "lore", "game-context"}
            or extra.get("contextUse") == "evidence"
            or details.get("category") in {"canonical-source", "reference"}
        ):
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
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
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
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
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
    except (ValueError, TypeError, KeyError):
        return response(400, {"error": "Invalid artifact, context request, or stage lease"})
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
