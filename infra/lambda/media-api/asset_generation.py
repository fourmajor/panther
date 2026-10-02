"""Leased subscription-image requests; AWS coordinates, never runs paid inference."""

import hashlib
import base64
import json
import os
import re
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from access_policy import authorized
import index as media

TYPES = {"map", "blueprint", "location"}


def table():
    return boto3.resource("dynamodb").Table(os.environ["ASSET_GENERATION_TABLE"])


def public(item):
    value = {k: v for k, v in item.items() if k not in {"pk", "sk", "lease", "actor"}}
    return json.loads(
        json.dumps(value, default=lambda v: int(v) if isinstance(v, Decimal) else str(v))
    )


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Invalid generation job")
    return value


def read(job_id):
    return (
        table()
        .get_item(Key={"pk": "JOBS", "sk": identity(job_id)}, ConsistentRead=True)
        .get("Item")
    )


def submit(body):
    if not isinstance(body, dict) or set(body) != {
        "gameId",
        "type",
        "name",
        "prompt",
        "operationId",
    }:
        raise ValueError("Choose an asset type, name and prompt")
    game = body["gameId"]
    if not media._valid_slug(game) or body["type"] not in TYPES:
        raise ValueError("Invalid asset type or game")
    if not re.fullmatch(r"[a-f0-9]{32}", body["operationId"] or ""):
        raise ValueError("Invalid generation operation")
    for name, maximum in (("name", 160), ("prompt", 4000)):
        if not isinstance(body[name], str) or not 1 <= len(body[name].strip()) <= maximum:
            raise ValueError("Choose an asset name and prompt")
    game_record = (
        boto3.resource("dynamodb")
        .Table(os.environ["CATALOG_TABLE"])
        .get_item(Key={"pk": "GAMES", "sk": game}, ConsistentRead=True)
        .get("Item")
    )
    if not game_record:
        raise ValueError("Game not found")
    request = {**body, "schemaVersion": 1}
    job_id = hashlib.sha256(
        json.dumps({"gameId": game, "operationId": body["operationId"]}, sort_keys=True).encode()
    ).hexdigest()
    record = {
        **request,
        "pk": "JOBS",
        "sk": job_id,
        "jobId": job_id,
        "status": "QUEUED",
        "createdAt": int(time.time()),
        "assetKey": None,
        "visualStyle": game_record.get("visualStyle"),
        "generationAuthorized": True,
    }
    try:
        table().put_item(Item=record, ConditionExpression="attribute_not_exists(pk)")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
    stored = read(job_id)
    if any(stored.get(k) != v for k, v in request.items()):
        raise ValueError("Generation operation was already used with different inputs")
    return public(stored)


def claim(claims):
    # Bounded job page, not an asset-storage scan; expired running jobs are never regenerated.
    page = table().query(
        IndexName="StatusIndex", KeyConditionExpression=Key("status").eq("QUEUED"), Limit=20
    )
    for item in page.get("Items", []):
        if item.get("status") != "QUEUED":
            continue
        lease = uuid.uuid4().hex
        try:
            result = table().update_item(
                Key={"pk": "JOBS", "sk": item["jobId"]},
                UpdateExpression="SET #s=:running, lease=:lease, actor=:actor, leaseUntil=:until",
                ConditionExpression="#s=:queued",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":running": "GENERATING",
                    ":queued": "QUEUED",
                    ":lease": lease,
                    ":actor": claims["sub"],
                    ":until": int(time.time()) + 3600,
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                continue
            raise
        return {"job": public(result["Attributes"]), "lease": lease}
    return {"job": None}


def resume(body, claims):
    if set(body) != {"jobId"}:
        raise ValueError("Choose a saved generation job")
    job = read(body["jobId"])
    if (
        not job
        or job.get("actor") != claims["sub"]
        or not (
            job["status"] == "ATTENTION"
            or job["status"] == "GENERATING"
            and job.get("leaseUntil", 0) < time.time()
        )
    ):
        raise ValueError("This worker cannot resume that job")
    lease = uuid.uuid4().hex
    result = table().update_item(
        Key={"pk": "JOBS", "sk": job["jobId"]},
        UpdateExpression="SET #s=:running, lease=:lease, leaseUntil=:until REMOVE message",
        ConditionExpression="(#s=:attention OR (#s=:running AND leaseUntil<:now)) AND actor=:actor",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":running": "GENERATING",
            ":attention": "ATTENTION",
            ":actor": claims["sub"],
            ":now": int(time.time()),
            ":lease": lease,
            ":until": int(time.time()) + 3600,
        },
        ReturnValues="ALL_NEW",
    )
    return {"job": public(result["Attributes"]), "lease": lease}


def jobs_page(game, cursor=None):
    if not media._valid_slug(game):
        raise ValueError("Choose a game")
    args = {
        "IndexName": "GameIndex",
        "KeyConditionExpression": Key("gameId").eq(game),
        "Limit": 25,
        "ScanIndexForward": False,
    }
    if cursor:
        if not isinstance(cursor, str) or len(cursor) > 4096:
            raise ValueError("Invalid generation cursor")
        pointer = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True).decode())
        if (
            not isinstance(pointer, dict)
            or set(pointer) != {"pk", "sk", "gameId", "createdAt"}
            or pointer["gameId"] != game
            or pointer["pk"] != "JOBS"
            or type(pointer["createdAt"]) is not int
            or pointer["createdAt"] < 0
        ):
            raise ValueError("Invalid generation cursor")
        identity(pointer["sk"])
        args["ExclusiveStartKey"] = pointer
    result = table().query(**args)
    pointer = result.get("LastEvaluatedKey")
    return {
        "jobs": [status_view(item) for item in result.get("Items", [])],
        "cursor": base64.urlsafe_b64encode(json.dumps(pointer, default=int).encode()).decode()
        if pointer
        else None,
    }


def status_view(job):
    value = public(job)
    if value["status"] == "GENERATING" and job.get("leaseUntil", 0) < time.time():
        value.update(
            status="ATTENTION",
            message="The image worker stopped. Check its saved output before generating again.",
        )
    return value


def worker_update(body, claims, operation):
    expected = {"jobId", "lease"} | (
        {"assetKey"} if operation == "complete" else {"message"} if operation == "defer" else set()
    )
    if set(body) != expected:
        raise ValueError("Invalid worker result")
    job = read(body["jobId"])
    if not job or job.get("lease") != body["lease"] or job.get("actor") != claims["sub"]:
        raise ValueError("Generation lease is unavailable")
    if (
        job["status"] == "PUBLISHED"
        and operation == "complete"
        and job["assetKey"] == body["assetKey"]
    ):
        return public(job)
    if job["status"] != "GENERATING":
        raise ValueError("Generation is no longer running")
    updates = {"leaseUntil": int(time.time()) + 3600}
    if operation == "complete":
        key = body["assetKey"]
        if not isinstance(key, str) or not re.fullmatch(
            rf"games/{re.escape(job['gameId'])}/assets/[a-z0-9-]+/original/[^/\\]+", key
        ):
            raise ValueError("Choose an immutable same-game generated image")
        # Exact storage verification is authoritative before the asynchronous browse projection catches up.
        head = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=key, ChecksumMode="ENABLED")
        metadata = json.loads(
            base64.b64decode(head.get("Metadata", {}).get("panther", "e30="), validate=True)
        )
        if not isinstance(metadata, dict) or not isinstance(metadata.get("extra"), dict):
            raise ValueError("Output has no generation metadata")
        extra = metadata["extra"]
        if (
            extra.get("assetGenerationJobId") != job["jobId"]
            or extra.get("assetType") != job["type"]
        ):
            raise ValueError("Output does not belong to this generation job")
        generation = extra.get("generation")
        cost = generation.get("cost") if isinstance(generation, dict) else None
        if (
            not isinstance(generation, dict)
            or generation.get("provider") != "OpenAI"
            or not isinstance(cost, dict)
            or cost.get("status") != "subscription"
            or extra.get("relationshipRole") != "finished"
        ):
            raise ValueError("Output requires honest subscription generation metadata")
        if (
            head.get("ContentType") != "image/png"
            or not 0 < head.get("ContentLength", 0) <= 20 * 1024**2
            or not head.get("ChecksumSHA256")
            or head["ChecksumSHA256"] != extra.get("sha256")
        ):
            raise ValueError("Generated image bytes are unavailable or changed")
        updates.update(status="PUBLISHED", assetKey=key)
    elif operation == "defer":
        message = body["message"]
        if not isinstance(message, str) or not 1 <= len(message) <= 500:
            raise ValueError("Invalid generation failure")
        updates.update(status="ATTENTION", message=message)
    names = {f"#u{i}": k for i, k in enumerate(updates)}
    values = {f":u{i}": v for i, v in enumerate(updates.values())}
    values.update({":lease": body["lease"], ":actor": claims["sub"]})
    result = table().update_item(
        Key={"pk": "JOBS", "sk": job["jobId"]},
        UpdateExpression="SET " + ", ".join(f"#u{i}=:u{i}" for i in range(len(updates))),
        ConditionExpression="lease=:lease AND actor=:actor",
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return public(result["Attributes"])


def handler(event, _context):
    route = event.get("routeKey", "")
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    operation = route.rsplit("/", 1)[-1]
    worker = operation in {"claim", "heartbeat", "defer", "complete", "resume"}
    if not authorized(
        claims,
        "MODEL_WORKERS"
        if worker
        else "CATALOG_READERS"
        if route.startswith("GET ")
        else "MODEL_PUBLISHERS",
    ):
        return media._response(403, {"error": "This account cannot use asset generation"})
    try:
        if route == "POST /asset-generation":
            value = submit(json.loads(event.get("body") or "{}"))
        elif route == "GET /asset-generation":
            q = event.get("queryStringParameters") or {}
            if not q.get("jobId"):
                return media._response(200, jobs_page(q.get("gameId"), q.get("cursor")))
            job = read(q.get("jobId"))
            if not job or job["gameId"] != q.get("gameId"):
                return media._response(404, {"error": "Generation job not found"})
            value = status_view(job)
        elif route == "POST /asset-generation/claim":
            value = claim(claims)
        elif route == "POST /asset-generation/resume":
            value = resume(json.loads(event.get("body") or "{}"), claims)
        elif worker and route.startswith("POST /asset-generation/"):
            value = worker_update(json.loads(event.get("body") or "{}"), claims, operation)
        else:
            return media._response(404, {"error": "Route not found"})
        return media._response(200, value)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return media._response(400, {"error": "Choose a valid asset type, name and prompt"})
    except ClientError:
        return media._response(503, {"error": "Asset generation is temporarily unavailable"})
