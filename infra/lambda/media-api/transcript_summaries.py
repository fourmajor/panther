"""Versioned, source-pinned reading projections; raw speech is never modified."""

import base64
import hashlib
import json
import os
import re
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from access_policy import authorized
import index as media


def table():
    return boto3.resource("dynamodb").Table(os.environ["TRANSCRIPT_SUMMARY_TABLE"])


def public(record):
    return json.loads(
        json.dumps(
            {k: v for k, v in record.items() if k not in {"pk", "sk", "lease", "actor"}},
            default=lambda v: float(v) if isinstance(v, Decimal) else str(v),
        )
    )


def source(game, key):
    if (
        not media._valid_slug(game)
        or not isinstance(key, str)
        or not re.fullmatch(
            rf"games/{re.escape(game)}/assets/[a-z0-9-]+/original/[^/\\]+\.json", key
        )
    ):
        raise ValueError("Choose a structured same-game transcript")
    head = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=key, ChecksumMode="ENABLED")
    if not head.get("ChecksumSHA256") or not 0 < head.get("ContentLength", 0) <= 2 * 1024**2:
        raise ValueError("Transcript requires bounded immutable checksum evidence")
    return {"key": key, "sha256": head["ChecksumSHA256"], "size": head["ContentLength"]}


def load_source(reference):
    data = media.s3.get_object(Bucket=media.BUCKET_NAME, Key=reference["key"])["Body"].read(
        2 * 1024**2 + 1
    )
    if (
        len(data) != reference["size"]
        or base64.b64encode(hashlib.sha256(data).digest()).decode() != reference["sha256"]
    ):
        raise ValueError("Transcript changed")
    doc = json.loads(data)
    if not isinstance(doc, dict):
        raise ValueError("Choose a structured transcript object")
    if doc.get("entityType") == "EditorialArtifact" and doc.get("stage") == "corrected-transcript":
        doc = (
            doc.get("payload", {}).get("transcript", {})
            if isinstance(doc.get("payload"), dict)
            else {}
        )
    if (
        not isinstance(doc, dict)
        or doc.get("entityType") not in {"PlayerTranscript", "BrowserTranscript"}
        or not isinstance(doc.get("segments"), list)
        or not doc["segments"]
        or any(
            not isinstance(segment, dict) or not isinstance(segment.get("text"), str)
            for segment in doc["segments"]
        )
    ):
        raise ValueError("Only structured completed transcripts can be summarized")
    if doc.get("entityType") == "BrowserTranscript" and doc.get("mode") != "final":
        raise ValueError("Live previews are not completed transcript evidence")
    game = reference["key"].split("/")[1]
    if doc.get("gameId") != game:
        raise ValueError("Transcript belongs to another game")
    return doc


def pointer(game, key):
    return {"pk": f"SOURCE#{game}", "sk": hashlib.sha256(key.encode()).hexdigest()}


def read(job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{64}", job_id):
        raise ValueError("Invalid summary job")
    return table().get_item(Key={"pk": "JOBS", "sk": job_id}, ConsistentRead=True).get("Item")


def view(game, key):
    reference = source(game, key)
    pin = table().get_item(Key=pointer(game, key), ConsistentRead=True).get("Item")
    job = read(pin["jobId"]) if pin else None
    if not job or job["source"] != reference:
        return {
            "schemaVersion": 1,
            "gameId": game,
            "key": key,
            "jobId": None,
            "status": "MISSING",
            "source": reference,
            "summary": None,
            "participants": [],
            "recordedAt": None,
            "assetKey": None,
        }
    value = public(job)
    if value["status"] == "GENERATING" and job.get("leaseUntil", 0) < time.time():
        value.update(
            status="ATTENTION", message="The summary worker stopped; source evidence is unchanged."
        )
    if not value.get("summary") and pin.get("readyJobId"):
        previous = read(pin["readyJobId"])
        if previous and previous["source"] == reference:
            value.update(
                summary=public(previous).get("summary"),
                participants=public(previous).get("participants", []),
                recordedAt=previous.get("recordedAt"),
                assetKey=previous.get("assetKey"),
            )
    return value


def submit(body):
    if not isinstance(body, dict) or not {"gameId", "key"} <= set(body) <= {
        "gameId",
        "key",
        "operationId",
    }:
        raise ValueError("Choose a transcript")
    reference = source(body["gameId"], body["key"])
    doc = load_source(reference)
    operation = body.get("operationId", "initial")
    if operation != "initial" and (
        not isinstance(operation, str) or not re.fullmatch(r"[a-f0-9]{32}", operation)
    ):
        raise ValueError("Invalid regeneration operation")
    # Default ensure is idempotent by source checksum; deliberate regeneration makes a new immutable revision.
    job_id = hashlib.sha256(
        json.dumps(
            {"schemaVersion": 1, "source": reference, "operationId": operation}, sort_keys=True
        ).encode()
    ).hexdigest()
    existing = read(job_id)
    if existing:
        return view(body["gameId"], body["key"])
    record = {
        "pk": "JOBS",
        "sk": job_id,
        "schemaVersion": 1,
        "jobId": job_id,
        "gameId": body["gameId"],
        "key": body["key"],
        "source": reference,
        "status": "QUEUED",
        "createdAt": int(time.time()),
        "operationId": operation,
        "summary": None,
        "participants": [],
        "recordedAt": None,
        "assetKey": None,
    }
    # Participants are source player identities, never guessed speaker/character assignments.
    people = doc.get("players", [])
    if isinstance(people, list):
        record["participants"] = [
            {
                "id": p.get("id", p.get("playerId")),
                **({"name": p["name"]} if isinstance(p.get("name"), str) else {}),
            }
            for p in people
            if isinstance(p, dict) and isinstance(p.get("id", p.get("playerId")), str)
        ]
    declared = {p["id"] for p in record["participants"]}
    for segment in doc["segments"]:
        player_id = segment.get("playerId") if isinstance(segment, dict) else None
        if isinstance(player_id, str) and player_id not in declared:
            record["participants"].append({"id": player_id})
            declared.add(player_id)
    record["recordedAt"] = next(
        (doc[k] for k in ("recordedAt", "startedAt", "capturedAt") if isinstance(doc.get(k), str)),
        None,
    )
    previous = (
        table().get_item(Key=pointer(body["gameId"], body["key"]), ConsistentRead=True).get("Item")
        or {}
    )
    previous_ready = read(previous["readyJobId"]) if previous.get("readyJobId") else None
    record["previousSummaryKey"] = (
        previous_ready.get("assetKey")
        if previous_ready and previous_ready["source"] == reference
        else None
    )
    pin = {
        **pointer(body["gameId"], body["key"]),
        "jobId": job_id,
        **({"readyJobId": previous["readyJobId"]} if previous.get("readyJobId") else {}),
    }
    serializer = TypeSerializer()

    def encode(value):
        return {k: serializer.serialize(v) for k, v in value.items()}

    put_pointer = {
        "TableName": table().name,
        "Item": encode(pin),
        "ConditionExpression": "jobId=:old" if previous else "attribute_not_exists(pk)",
    }
    if previous:
        put_pointer["ExpressionAttributeValues"] = encode({":old": previous["jobId"]})
    try:
        boto3.client("dynamodb").transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": table().name,
                        "Item": encode(record),
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {"Put": put_pointer},
            ]
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        if not read(job_id):
            raise ValueError(
                "Summary revision changed; read current state before trying again"
            ) from exc
    return view(body["gameId"], body["key"])


def claim(claims):
    for job in (
        table()
        .query(IndexName="StatusIndex", KeyConditionExpression=Key("status").eq("QUEUED"), Limit=20)
        .get("Items", [])
    ):
        lease = uuid.uuid4().hex
        try:
            value = table().update_item(
                Key={"pk": "JOBS", "sk": job["jobId"]},
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
            )["Attributes"]
            return {"job": public(value), "lease": lease}
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    return {"job": None}


def update(body, claims, action):
    fields = {"jobId", "lease"} | (
        {"assetKey"} if action == "complete" else {"message"} if action == "defer" else set()
    )
    if set(body) != fields:
        raise ValueError("Invalid summary result")
    job = read(body["jobId"])
    if not job or job.get("lease") != body["lease"] or job.get("actor") != claims["sub"]:
        raise ValueError("Summary lease changed")
    if job["status"] == "READY" and action == "complete" and job["assetKey"] == body["assetKey"]:
        return public(job)
    if job["status"] != "GENERATING":
        raise ValueError("Summary is not running")
    values = {"leaseUntil": int(time.time()) + 3600}
    if action == "defer":
        if not isinstance(body["message"], str) or not 1 <= len(body["message"]) <= 500:
            raise ValueError("Invalid summary failure")
        values.update(status="ATTENTION", message=body["message"])
    if action == "complete":
        ref = source(job["gameId"], body["assetKey"])
        data = media.s3.get_object(Bucket=media.BUCKET_NAME, Key=ref["key"])["Body"].read(
            2 * 1024**2 + 1
        )
        if (
            len(data) != ref["size"]
            or base64.b64encode(hashlib.sha256(data).digest()).decode() != ref["sha256"]
        ):
            raise ValueError("Summary asset changed")
        doc = json.loads(data)
        if (
            doc.get("entityType") != "TranscriptSummary"
            or doc.get("schemaVersion") != 1
            or doc.get("summaryPolicyVersion") != 2
            or doc.get("gameId") != job["gameId"]
            or doc.get("jobId") != job["jobId"]
            or doc.get("source") != job["source"]
        ):
            raise ValueError("Summary belongs to different source evidence")
        summary = doc.get("summary")
        if (
            not isinstance(summary, dict)
            or set(summary) != {"title", "summary", "segmentIndexes", "uncertainties"}
            or not isinstance(summary["title"], str)
            or not 1 <= len(summary["title"]) <= 80
            or not isinstance(summary["summary"], str)
            or not 1 <= len(summary["summary"]) <= 600
            or not isinstance(summary["segmentIndexes"], list)
            or not summary["segmentIndexes"]
            or not all(type(i) is int and i >= 0 for i in summary["segmentIndexes"])
            or not isinstance(summary["uncertainties"], list)
            or not all(isinstance(i, str) for i in summary["uncertainties"])
        ):
            raise ValueError("Invalid structured summary")
        if source(job["gameId"], job["key"]) != job["source"]:
            raise ValueError("Original transcript checksum changed")
        original = load_source(job["source"])
        if any(index >= len(original["segments"]) for index in summary["segmentIndexes"]):
            raise ValueError("Summary cites absent source speech")
        if (
            doc.get("sourceKeys") != [job["key"]]
            or doc.get("reviewStatus") != "ai-reviewed-unverified"
        ):
            raise ValueError("Summary requires explicit source lineage and honest review status")
        values.update(status="READY", assetKey=body["assetKey"], summary=summary, summaryPolicyVersion=2)
    names = {f"#n{i}": k for i, k in enumerate(values)}
    parameters = {f":v{i}": v for i, v in enumerate(values.values())}
    result = table().update_item(
        Key={"pk": "JOBS", "sk": job["jobId"]},
        UpdateExpression="SET " + ", ".join(f"#n{i}=:v{i}" for i in range(len(values))),
        ConditionExpression="lease=:lease AND actor=:actor",
        ExpressionAttributeNames=names,
        ExpressionAttributeValues={**parameters, ":lease": body["lease"], ":actor": claims["sub"]},
        ReturnValues="ALL_NEW",
    )["Attributes"]
    if action == "complete":
        try:
            table().update_item(
                Key=pointer(job["gameId"], job["key"]),
                UpdateExpression="SET readyJobId=:job",
                ConditionExpression="jobId=:job",
                ExpressionAttributeValues={":job": job["jobId"]},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    return public(result)


def handler(event, _context):
    route = event.get("routeKey", "")
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    action = route.rsplit("/", 1)[-1]
    worker = action in {"claim", "heartbeat", "defer", "complete"}
    if not authorized(
        claims,
        "MODEL_WORKERS"
        if worker
        else "CATALOG_READERS"
        if route.startswith("GET ")
        else "MODEL_PUBLISHERS",
    ):
        return media._response(403, {"error": "This account cannot use transcript summaries"})
    try:
        body = json.loads(event.get("body") or "{}")
        if route == "GET /transcript-summaries":
            q = event.get("queryStringParameters") or {}
            value = view(q.get("gameId"), q.get("key"))
        elif route == "POST /transcript-summaries":
            value = submit(body)
        elif route == "POST /transcript-summaries/claim":
            value = claim(claims)
        elif worker and route.startswith("POST /transcript-summaries/"):
            value = update(body, claims, action)
        else:
            return media._response(404, {"error": "Route not found"})
        return media._response(200, value)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return media._response(400, {"error": "Choose a valid completed transcript"})
    except ClientError:
        return media._response(503, {"error": "Transcript summaries are temporarily unavailable"})
