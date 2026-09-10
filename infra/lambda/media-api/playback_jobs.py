"""Explicit completed recording sets and durable, leased playback assembly. No audio processing here."""

import base64
import hashlib
import json
import math
import os
import re
import time
import uuid
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError
import index as media

table = boto3.resource("dynamodb").Table(os.environ["PLAYBACK_TABLE"])
states = boto3.client("stepfunctions")


def response(status, body):
    return {"statusCode": status, "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "body": json.dumps(body, default=lambda v: float(v) if isinstance(v, Decimal) else str(v))}


def key(job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{64}", job_id):
        raise ValueError("Invalid job")
    return {"pk": "SETS", "sk": job_id}


def read(job_id):
    return table.get_item(Key=key(job_id), ConsistentRead=True).get("Item")


def public(job):
    return {k: v for k, v in job.items() if k not in {"pk", "sk", "taskToken", "lease", "leaseActor"}}


def reference(object_key):
    head = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=object_key, ChecksumMode="ENABLED")
    checksum = head.get("ChecksumSHA256")
    if not checksum or len(base64.b64decode(checksum, validate=True)) != 32 or not 0 < head["ContentLength"] <= 1024**3:
        raise ValueError("Missing size/checksum")
    return {"key": object_key, "size": head["ContentLength"], "sha256": checksum}


def document(ref, limit=200_000):
    if ref["size"] > limit:
        raise ValueError("Manifest exceeds supported size")
    reply = media.s3.get_object(Bucket=media.BUCKET_NAME, Key=ref["key"])
    try:
        raw = reply["Body"].read(limit + 1)
    finally:
        reply["Body"].close()
    if len(raw) != ref["size"] or base64.b64encode(hashlib.sha256(raw).digest()).decode() != ref["sha256"]:
        raise ValueError("Changed manifest")
    return json.loads(raw)


def submit(body):
    if set(body) != {"gameId", "recordingKey", "manifestSha256", "status"} or body["status"] != "COMPLETE":
        raise ValueError("Explicit COMPLETE set required")
    game, recording_key = body["gameId"], body["recordingKey"]
    if not media._valid_slug(game) or not isinstance(recording_key, str):
        raise ValueError("Invalid game")
    match = re.fullmatch(rf"games/{re.escape(game)}/assets/(recording-[a-f0-9]{{32}})/original/recording.json", recording_key)
    if not match:
        raise ValueError("Invalid recording key")
    ref = reference(recording_key)
    manifest_sha = base64.b64decode(ref["sha256"]).hex()
    if manifest_sha != body["manifestSha256"]:
        raise ValueError("Manifest does not match completion declaration")
    job_id = hashlib.sha256(f"playback-v1:{recording_key}:{manifest_sha}".encode()).hexdigest()
    existing = read(job_id)
    if existing:
        return public(existing)
    doc = document(ref)
    if (doc.get("schemaVersion") != 1 or doc.get("entityType") != "Recording"
            or doc.get("gameId") != game or doc.get("id") != match[1]
            or doc.get("status") not in {"complete", "interrupted"}
            or doc.get("sourceFormat") != "flac" or not media._valid_slug(doc.get("sessionId"))):
        raise ValueError("Invalid finalized recording")
    parts = doc.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 1000:
        raise ValueError("Expected 1–1000 chunks")
    refs, offset = [], 0.0
    prefix = recording_key.removesuffix("recording.json")
    for i, part in enumerate(parts):
        if part.get("file") != f"part-{i:04d}.flac":
            raise ValueError("Chunks must have unique consecutive indexes")
        start, duration = part.get("start"), part.get("duration")
        if (any(type(n) not in (float, int) or not math.isfinite(n) for n in (start, duration))
                or duration <= 0 or abs(start - offset) > 0.02):
            raise ValueError("Invalid chunk timeline")
        offset += duration
    with ThreadPoolExecutor(max_workers=8) as pool:
        refs = list(pool.map(reference, [prefix + part["file"] for part in parts]))
    for part, item in zip(parts, refs, strict=True):
        if item["size"] != part.get("size") or base64.b64decode(item["sha256"]).hex() != part.get("sha256"):
            raise ValueError("Chunk missing or does not match manifest")
    # This immutable set membership is the tag for legacy chunks too: no rewriting old objects.
    job = {**key(job_id), "schemaVersion": 1, "entityType": "RecordingChunkSet", "workflowVersion": 1,
           "jobId": job_id, "chunkSetId": doc["id"], "gameId": game, "sessionId": doc["sessionId"],
           "setStatus": "COMPLETE", "captureStatus": doc["status"], "status": "SUBMITTED",
           "recording": ref, "chunks": refs, "createdAt": int(time.time()), "attempts": 0}
    if len(json.dumps(job).encode()) > 300_000:
        raise ValueError("Completed set exceeds supported size")
    try:
        table.put_item(Item=job, ConditionExpression="attribute_not_exists(pk)")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return public(read(job_id))
    return public(job)


def page(cursor=None):
    args = {"KeyConditionExpression": Key("pk").eq("SETS"), "ConsistentRead": True, "Limit": 25}
    if cursor:
        args["ExclusiveStartKey"] = key(cursor)
    return table.query(**args)


def claim(actor):
    now, cursor = int(time.time()), None
    while True:
        batch = page(cursor)
        for job in batch.get("Items", []):
            if job["status"] not in {"QUEUED", "RUNNING"} or job.get("leaseUntil", 0) > now:
                continue
            lease = uuid.uuid4().hex
            failed = job["attempts"] >= 3
            try:
                result = table.update_item(Key=key(job["jobId"]),
                    UpdateExpression="SET #s = :state, leaseUntil = :until, leaseActor = :actor, lease = :lease ADD attempts :one",
                    ConditionExpression="#s = :old AND leaseUntil <= :now",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":state": "FAILED" if failed else "RUNNING", ":until": now + 600,
                        ":actor": actor, ":lease": lease, ":one": 1, ":old": job["status"], ":now": now},
                    ReturnValues="ALL_NEW")
                if not failed:
                    return {"job": public(result["Attributes"]), "lease": lease}
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
        cursor = batch.get("LastEvaluatedKey", {}).get("sk")
        if not cursor:
            return {"job": None}


def update(body, actor, operation):
    job = read(body.get("jobId"))
    if not job or job.get("leaseActor") != actor or job.get("lease") != body.get("lease"):
        raise ValueError("Invalid worker lease")
    if operation == "complete" and job["status"] == "DONE":
        return public(job)
    now = int(time.time())
    if job["status"] != "RUNNING" or job.get("leaseUntil", 0) <= now:
        raise ValueError("Expired worker lease")
    output = None
    if operation == "complete":
        source_sha = base64.b64decode(job["recording"]["sha256"]).hex()
        prefix = job["recording"]["key"].removesuffix("recording.json")
        stem = prefix + "playback-v1-" + source_sha[:16]
        output = {"manifest": reference(stem + ".json"), "audio": reference(stem + ".m4a")}
        doc = document(output["manifest"], limit=1_000_000)
        if (doc.get("entityType") != "RecordingPlayback" or doc.get("version") != 1
                or doc.get("gameId") != job["gameId"] or doc.get("recordingId") != job["chunkSetId"]
                or doc.get("recordingKey") != job["recording"]["key"] or doc.get("sourceManifestSha256") != source_sha
                or doc.get("audioKey") != output["audio"]["key"] or doc.get("size") != output["audio"]["size"]
                or doc.get("audioSha256") != base64.b64decode(output["audio"]["sha256"]).hex()
                or doc.get("sourceKeys") != [job["recording"]["key"], *[r["key"] for r in job["chunks"]]]):
            raise ValueError("Playback evidence does not match completed set")
    result = table.update_item(Key=key(job["jobId"]),
        UpdateExpression="SET leaseUntil = :until, #s = :state" + (", #out = :output" if output else ""),
        ConditionExpression="#s = :running AND lease = :lease AND leaseActor = :actor AND leaseUntil > :now",
        ExpressionAttributeNames={"#s": "status", **({"#out": "output"} if output else {})},
        ExpressionAttributeValues={":until": now + 600, ":state": "DONE" if output else "RUNNING",
            ":running": "RUNNING", ":lease": body["lease"], ":actor": actor, ":now": now,
            **({":output": output} if output else {})}, ReturnValues="ALL_NEW")
    return public(result["Attributes"])


def internal(event):
    job = read(event["jobId"])
    if not job:
        raise ValueError("Missing completed set")
    if event["operation"] == "dispatch":
        if job.get("taskToken") == event["taskToken"]:
            return {}
        table.update_item(Key=key(job["jobId"]),
            UpdateExpression="SET #s = :queued, taskToken = :token, leaseUntil = :zero",
            ConditionExpression="#s = :submitted AND setStatus = :complete",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":queued": "QUEUED", ":token": event["taskToken"], ":zero": 0,
                ":submitted": "SUBMITTED", ":complete": "COMPLETE"})
    elif job["status"] != "DONE":
        try:
            table.update_item(Key=key(job["jobId"]), UpdateExpression="SET #s = :failed",
                ConditionExpression="#s <> :done", ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":failed": "FAILED", ":done": "DONE"})
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    return {}


def handler(event, _context):
    if "operation" in event and "requestContext" not in event:
        return internal(event)
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not claims.get("sub") or claims.get("cognito:username") not in {"stu", "other_stu"}:
        return response(403, {"error": "Owner or DM sign-in required"})
    try:
        route = event.get("routeKey", "")
        if route == "GET /recording-playback-jobs":
            q = event.get("queryStringParameters") or {}
            if q.get("jobId"):
                job = read(q["jobId"])
                return response(200, {"job": public(job)}) if job else response(404, {"error": "Job not found"})
            batch = page(q.get("cursor"))
            return response(200, {"jobs": [public(j) for j in batch.get("Items", [])],
                "cursor": batch.get("LastEvaluatedKey", {}).get("sk")})
        raw = event.get("body") or "{}"
        if len(raw) > 5000:
            raise ValueError("Request too large")
        body = json.loads(base64.b64decode(raw) if event.get("isBase64Encoded") else raw)
        if route == "POST /recording-sets/complete":
            return response(200, submit(body))
        if claims.get("cognito:username") != "stu":
            return response(403, {"error": "Only the owner's laptop can process playback"})
        if route == "POST /recording-playback-jobs/claim":
            if body.get("workflowVersion") != 1:
                raise ValueError("Unsupported workflow version")
            return response(200, claim(claims["sub"]))
        operation = route.removeprefix("POST /recording-playback-jobs/")
        if operation in {"heartbeat", "complete"}:
            return response(200, update(body, claims["sub"], operation))
        return response(404, {"error": "Unknown operation"})
    except (ValueError, TypeError, KeyError, AttributeError):
        return response(400, {"error": "Invalid or incomplete chunk set, playback evidence, or worker lease"})
    except ClientError as exc:
        return response(409 if exc.response["Error"]["Code"] == "ConditionalCheckFailedException" else 503,
            {"error": "Playback state changed or storage unavailable; retry the same completed set"})


def stream(event, _context):
    failures, decoder = [], TypeDeserializer()
    for record in event.get("Records", []):
        try:
            data = record["dynamodb"]
            new = {k: decoder.deserialize(v) for k, v in data.get("NewImage", {}).items()}
            old = {k: decoder.deserialize(v) for k, v in data.get("OldImage", {}).items()}
            if new.get("status") == old.get("status"):
                continue
            if new.get("status") == "SUBMITTED" and new.get("setStatus") == "COMPLETE":
                try:
                    states.start_execution(stateMachineArn=os.environ["STATE_MACHINE_ARN"],
                        name=new["jobId"], input=json.dumps({"jobId": new["jobId"]}))
                except ClientError as exc:
                    if exc.response["Error"]["Code"] != "ExecutionAlreadyExists":
                        raise
            elif new.get("status") in {"DONE", "FAILED"} and new.get("taskToken"):
                try:
                    states.send_task_success(taskToken=new["taskToken"], output=json.dumps({"status": new["status"]}))
                except ClientError as exc:
                    if exc.response["Error"]["Code"] not in {"TaskDoesNotExist", "TaskTimedOut", "InvalidToken"}:
                        raise
        except Exception:
            failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})
    return {"batchItemFailures": failures}
