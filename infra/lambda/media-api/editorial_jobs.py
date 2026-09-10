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
TERMINAL = {"FAILED", "READY_FOR_VIDEO_DISCUSSION"}


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


def asset(key, game):
    if (
        not isinstance(key, str)
        or not re.fullmatch(rf"games/{re.escape(game)}/assets/[a-z0-9-]+/original/[^/\\]+", key)
        or not media._valid_key(key)
    ):
        raise ValueError("Expected immutable same-game asset")
    head = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=key, ChecksumMode="ENABLED")
    if not head.get("ChecksumSHA256") or not 0 < head["ContentLength"] <= 2 * 1024**2:
        raise ValueError("Expected checksummed text artifact under 2 MiB")
    return {"key": key, "sha256": head["ChecksumSHA256"], "size": head["ContentLength"]}, head


def document(reference):
    data = media.s3.get_object(Bucket=media.BUCKET_NAME, Key=reference["key"])["Body"].read(
        2 * 1024**2 + 1
    )
    if (
        len(data) != reference["size"]
        or base64.b64encode(hashlib.sha256(data).digest()).decode() != reference["sha256"]
    ):
        raise ValueError("Artifact changed")
    return json.loads(data)


def submit(body):
    if set(body) != {"gameId", "rawKey"} or not media._valid_slug(body["gameId"]):
        raise ValueError("Expected gameId and rawKey")
    ref, head = asset(body["rawKey"], body["gameId"])
    raw = document(ref)
    if (
        raw.get("entityType") != "PlayerTranscript"
        or raw.get("gameId") != body["gameId"]
        or raw.get("artifactType", "raw-transcript") != "raw-transcript"
    ):
        raise ValueError("Only completed raw transcripts can start editorial work")
    if (
        not isinstance(raw.get("segments"), list)
        or not raw["segments"]
        or not isinstance(raw.get("sourceParts"), list)
        or not raw["sourceParts"]
        or not media._valid_slug(raw.get("recordingId"))
        or not media._valid_slug(raw.get("sessionId"))
    ):
        raise ValueError("Incomplete raw transcript")
    for segment in raw["segments"]:
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            raise ValueError("Invalid transcript segment")
        start, end = segment.get("start"), segment.get("end")
        if (
            any(type(v) not in {int, float} or not math.isfinite(v) for v in (start, end))
            or not 0 <= start <= end
        ):
            raise ValueError("Invalid transcript timing")
    job_id = hashlib.sha256(json.dumps([ref, PLAN["version"]], sort_keys=True).encode()).hexdigest()
    job = {
        "pk": "RUNS",
        "sk": job_id,
        "jobId": job_id,
        "gameId": body["gameId"],
        "sessionId": raw["sessionId"],
        "raw": ref,
        "workflowVersion": PLAN["version"],
        "status": "SUBMITTED",
        "createdAt": int(time.time()),
        "contextCutoff": int(media._asset_created_at(head).timestamp()),
        "videoGenerationAuthorized": False,
    }
    try:
        table.put_item(Item=job, ConditionExpression="attribute_not_exists(pk)")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
    return public(read("RUNS", job_id))


def context_page(game, cursor, cutoff):
    if not media._valid_slug(game):
        raise ValueError("Invalid game")
    args = {"Bucket": media.BUCKET_NAME, "Prefix": f"games/{game}/assets/", "MaxKeys": 50}
    if cursor:
        args["ContinuationToken"] = cursor
    page = media.s3.list_objects_v2(**args)
    items = []
    for item in page.get("Contents", []):
        key = item["Key"]
        if (
            not key.endswith((".json", ".md", ".txt"))
            or not 0 < item["Size"] <= 256 * 1024
        ):
            continue
        ref, head = asset(key, game)
        if media._asset_created_at(head).timestamp() > cutoff:
            continue
        stored = head.get("Metadata", {})
        details = json.loads(base64.b64decode(stored.get("panther", "e30=")))
        extra = details.get("extra", {})
        kind = stored.get("kind", "")
        if extra.get("contextUse") == "exclude" or kind in {
            "reading-script",
            "test-script",
            "holdout",
            "raw-transcript",
            "editorial-failed-candidate",
        }:
            continue
        if details.get("category") in {
            "grounded-adaptation",
            "creative-reimagining",
            "playful-derivative",
        }:
            continue
        eligible = (
            kind in {"corrected-transcript", "character-profile", "lore", "game-context"}
            or extra.get("contextUse") == "evidence"
            or details.get("category") in {"canonical-source", "reference"}
        )
        if eligible:
            items.append(
                {
                    **ref,
                    "kind": kind,
                    "metadata": details,
                    "lastModified": media._asset_created_at(head).isoformat(),
                }
            )
    return {"items": items, "cursor": page.get("NextContinuationToken")}


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
        status = "READY_FOR_VIDEO_DISCUSSION" if event["operation"] == "finish" else "FAILED"
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
    if not claims.get("sub") or claims.get("cognito:username") not in {"stu", "other_stu"}:
        return response(403, {"error": "Owner or DM sign-in required"})
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
        if claims.get("cognito:username") != "stu":
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
                        input=json.dumps({"jobId": new["jobId"]}),
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
