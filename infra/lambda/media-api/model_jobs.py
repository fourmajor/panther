"""Durable reference-set outbox and leased local jobs. Never log tokens or request bodies."""

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
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError
import index as media

db = boto3.resource("dynamodb")
raw_db = boto3.client("dynamodb")
table = db.Table(os.environ["JOB_TABLE"])
states = boto3.client("stepfunctions")
VIEWS = {"front", "front-right", "right", "back-right", "back", "back-left", "left", "front-left"}
TERMINAL = {"PUBLISHED", "FAILED", "SUPERSEDED", "CONFLICT", "EXPIRED"}
WORKERS = set(os.environ.get("MODEL_WORKERS", "").split(","))
serializer = TypeSerializer()
deserializer = TypeDeserializer()


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(body, default=lambda v: int(v) if isinstance(v, Decimal) else str(v)),
    }


def job_key(job_id):
    return {"pk": "JOBS", "sk": job_id}


def get_job(job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{64}", job_id):
        raise ValueError("Invalid job ID")
    return table.get_item(Key=job_key(job_id), ConsistentRead=True).get("Item")


def public(job):
    return {
        k: v for k, v in job.items() if k not in {"pk", "sk", "taskToken", "lease", "leaseActor"}
    }


def wire(item):
    return {k: serializer.serialize(v) for k, v in item.items()}


def head_key(game, character):
    return {"pk": f"CHAR#{game}#{character}", "sk": "HEAD"}


def asset(key, game, *, image=False):
    if (
        not isinstance(key, str)
        or not re.fullmatch(rf"games/{re.escape(game)}/assets/[a-z0-9-]+/original/[^/\\]+", key)
        or not media._valid_key(key)
    ):
        raise ValueError("References and outputs must be immutable assets in this game")
    record = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=key, ChecksumMode="ENABLED")
    if not 0 < record["ContentLength"] <= (8 * 1024 * 1024 if image else 1024**3):
        raise ValueError("Asset size is invalid")
    if image and record.get("ContentType") not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError("Turnaround views must be PNG, JPEG, or WebP images")
    checksum = record.get("ChecksumSHA256")
    if not checksum:
        raise ValueError("Upload references with the current Panther CLI to record SHA-256")
    return {"key": key, "sha256": checksum, "size": record["ContentLength"]}


def submit(body, claims):
    required = {
        "kind",
        "gameId",
        "characterId",
        "appearanceId",
        "revisionId",
        "views",
        "expectedRevision",
    }
    if set(body) != required or body["kind"] != "character-turnaround":
        raise ValueError("A complete character-turnaround manifest is required")
    for field in ("gameId", "characterId", "appearanceId", "revisionId"):
        if not media._valid_slug(body[field]) or len(body[field]) > 96:
            raise ValueError("Invalid reference-set identifier")
    views = body["views"]
    if not isinstance(views, dict) or set(views) != VIEWS or len(set(views.values())) != 8:
        raise ValueError("Eight distinct labeled views are required")
    game, character = body["gameId"], body["characterId"]
    refs = {view: asset(key, game, image=True) for view, key in sorted(views.items())}
    identity = {**body, "views": refs, "workflowVersion": 1}
    job_id = hashlib.sha256(
        json.dumps(
            {k: v for k, v in identity.items() if k != "expectedRevision"}, sort_keys=True
        ).encode()
    ).hexdigest()
    existing = get_job(job_id)
    if existing:
        return response(200, public(existing))
    record = media._profile_record(game, character)
    if not record or record[3] != body["expectedRevision"]:
        return response(
            409, {"error": "Inspect the current character before registering references"}
        )
    # Until appearance timelines ship, only the profile's current look can be auto-published.
    if body["appearanceId"] != record[2].get("appearanceId", "original"):
        raise ValueError("Only the current appearance is supported; do not mix alternate looks")
    job = {
        **job_key(job_id),
        **identity,
        "jobId": job_id,
        "status": "SUBMITTED",
        "createdAt": int(time.time()),
        "attempts": 0,
        "submittedBy": claims["sub"],
    }
    head = table.get_item(Key=head_key(game, character), ConsistentRead=True).get("Item", {})
    if head.get("publishing"):
        return response(
            409, {"error": "A publication is finishing; retry this reference set shortly"}
        )
    update = {
        "TableName": table.name,
        "Key": wire(head_key(game, character)),
        "UpdateExpression": "SET jobId = :job",
        "ConditionExpression": "attribute_not_exists(publishing) AND "
        + ("jobId = :old" if head else "attribute_not_exists(jobId)"),
        "ExpressionAttributeValues": wire(
            {":job": job_id, **({":old": head["jobId"]} if head else {})}
        ),
    }
    # The stream is the durable outbox: no lost job if the HTTP response or StartExecution fails.
    raw_db.transact_write_items(
        TransactItems=[
            {
                "Put": {
                    "TableName": table.name,
                    "Item": wire(job),
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            },
            {"Update": update},
        ]
    )
    return response(200, public(job))


def jobs_page(cursor=None):
    args = {"KeyConditionExpression": Key("pk").eq("JOBS"), "Limit": 100, "ConsistentRead": True}
    if cursor:
        args["ExclusiveStartKey"] = job_key(cursor)
    return table.query(**args)


def claim(claims):
    now = int(time.time())
    cursor = None
    # Small private installation; paginate instead of silently starving jobs beyond page one.
    while True:
        page = jobs_page(cursor)
        for job in page.get("Items", []):
            if (
                job["status"] not in {"QUEUED", "RUNNING", "PUBLISHING"}
                or job.get("leaseUntil", 0) > now
                or job.get("notBefore", 0) > now
            ):
                continue
            head = table.get_item(
                Key=head_key(job["gameId"], job["characterId"]), ConsistentRead=True
            ).get("Item", {})
            if job["status"] != "PUBLISHING" and head.get("jobId") != job["jobId"]:
                table.update_item(
                    Key=job_key(job["jobId"]),
                    UpdateExpression="SET #s = :s",
                    ConditionExpression="#s = :old AND leaseUntil <= :now",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={
                        ":s": "SUPERSEDED",
                        ":old": job["status"],
                        ":now": now,
                    },
                )
                continue
            if job.get("attempts", 0) >= 3 and job["status"] != "PUBLISHING":
                table.update_item(
                    Key=job_key(job["jobId"]),
                    UpdateExpression="SET #s = :failed",
                    ConditionExpression="#s = :old AND leaseUntil <= :now",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={
                        ":failed": "FAILED",
                        ":old": job["status"],
                        ":now": now,
                    },
                )
                continue
            lease = uuid.uuid4().hex
            try:
                result = table.update_item(
                    Key=job_key(job["jobId"]),
                    UpdateExpression="SET #s = :running, leaseUntil = :until, leaseActor = :actor, lease = :lease ADD attempts :one",
                    ConditionExpression="#s = :old AND leaseUntil <= :now",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={
                        ":running": "PUBLISHING" if job["status"] == "PUBLISHING" else "RUNNING",
                        ":old": job["status"],
                        ":until": now + 600,
                        ":actor": claims["sub"],
                        ":lease": lease,
                        ":now": now,
                        ":one": 1,
                    },
                    ReturnValues="ALL_NEW",
                )
                return response(200, {"job": public(result["Attributes"]), "lease": lease})
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
        cursor = page.get("LastEvaluatedKey", {}).get("sk")
        if not cursor:
            return response(200, {"job": None})


def owned_job(body, claims):
    job = get_job(body.get("jobId"))
    if not job or job.get("leaseActor") != claims["sub"] or job.get("lease") != body.get("lease"):
        raise ValueError("Job lease does not belong to this worker")
    return job


def update_lease(job, body, *, defer=False):
    now = int(time.time())
    table.update_item(
        Key=job_key(job["jobId"]),
        UpdateExpression="SET leaseUntil = :until, #s = :state, notBefore = :next"
        + (" ADD attempts :refund" if defer else ""),
        ConditionExpression="#s = :running AND lease = :lease AND leaseUntil > :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":until": 0 if defer else now + 600,
            ":state": "QUEUED" if defer else "RUNNING",
            ":next": now + 3600 if defer else 0,
            ":running": "RUNNING",
            ":lease": body["lease"],
            ":now": now,
            **({":refund": -1} if defer else {}),
        },
    )
    return response(200, {"status": "QUEUED" if defer else "RUNNING"})


def finish(job, body, claims):
    if job["status"] in TERMINAL:
        return response(200, public(job))
    if job["status"] not in {"RUNNING", "PUBLISHING"} or job["leaseUntil"] <= int(time.time()):
        return response(409, {"error": "Lease expired; this worker must stop"})
    result = body.get("result")
    if not isinstance(result, dict) or set(result) != {
        "passed",
        "webKey",
        "sourceKey",
        "provenanceKey",
        "evidenceKey",
    }:
        raise ValueError("A complete validation result is required")
    if not isinstance(result["passed"], bool):
        raise ValueError("Invalid quality result")
    if not result["passed"]:
        table.update_item(
            Key=job_key(job["jobId"]),
            UpdateExpression="SET #s = :s",
            ConditionExpression="lease = :lease AND #s = :running",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "FAILED",
                ":lease": body["lease"],
                ":running": "RUNNING",
            },
        )
        return response(200, {"status": "FAILED"})
    records = {}
    for name in ("webKey", "sourceKey", "provenanceKey", "evidenceKey"):
        records[name] = asset(result[name], job["gameId"])
        if f"/assets/model-job-{job['jobId'][:32]}-" not in result[name]:
            raise ValueError("Outputs must belong to this job's immutable asset group")
    if not result["sourceKey"].endswith(".blend") or records["evidenceKey"]["size"] > 64000:
        raise ValueError("Editable Blender source and bounded evidence are required")
    evidence = json.loads(
        media.s3.get_object(Bucket=media.BUCKET_NAME, Key=result["evidenceKey"])["Body"].read(64001)
    )
    review = evidence.get("visualReview", {})
    checks = evidence.get("blender", {})
    if (
        evidence.get("jobId") != job["jobId"]
        or evidence.get("browserPassed") is not True
        or review.get("passed") is not True
        or not review.get("assessment")
        or checks.get("freshSourceOpen") is not True
        or checks.get("freshGlbImport") is not True
        or set(checks.get("views", [])) != VIEWS
        or evidence.get("modelSha256") != base64.b64decode(records["webKey"]["sha256"]).hex()
    ):
        raise ValueError("Validation evidence does not match this candidate")
    if job["status"] == "PUBLISHING" and job.get("result") != result:
        raise ValueError("An in-progress publication cannot change outputs")
    head = head_key(job["gameId"], job["characterId"])
    current = table.get_item(Key=head, ConsistentRead=True).get("Item", {})
    if current.get("jobId") != job["jobId"]:
        table.update_item(
            Key=job_key(job["jobId"]),
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "SUPERSEDED"},
        )
        return response(200, {"status": "SUPERSEDED"})
    # Hold reference-set advancement while publishing. Retries recover this same job/lease;
    # an unknown storage result is reconciled against exact keys, never blindly overwritten.
    raw_db.transact_write_items(
        TransactItems=[
            {
                "Update": {
                    "TableName": table.name,
                    "Key": wire(head),
                    "UpdateExpression": "SET publishing = :job",
                    "ConditionExpression": "jobId = :job AND (attribute_not_exists(publishing) OR publishing = :job)",
                    "ExpressionAttributeValues": wire({":job": job["jobId"]}),
                }
            },
            {
                "Update": {
                    "TableName": table.name,
                    "Key": wire(job_key(job["jobId"])),
                    "UpdateExpression": "SET #s = :s, #r = :r",
                    "ConditionExpression": "lease = :lease AND leaseUntil > :now AND (#s = :running OR #s = :s)",
                    "ExpressionAttributeNames": {"#s": "status", "#r": "result"},
                    "ExpressionAttributeValues": wire(
                        {
                            ":s": "PUBLISHING",
                            ":r": result,
                            ":lease": body["lease"],
                            ":now": int(time.time()),
                            ":running": "RUNNING",
                        }
                    ),
                }
            },
        ]
    )
    record = media._profile_record(job["gameId"], job["characterId"])
    old_model = record[2].get("model", {}) if record else {}
    if all(old_model.get(k) == result[k] for k in ("webKey", "sourceKey", "provenanceKey")):
        status = "PUBLISHED"
    else:
        published = media._publish_model(
            {
                "requestContext": {"authorizer": {"jwt": {"claims": claims}}},
                "body": json.dumps(
                    {
                        "gameId": job["gameId"],
                        "characterId": job["characterId"],
                        "expectedRevision": job["expectedRevision"],
                        **{k: result[k] for k in ("webKey", "sourceKey", "provenanceKey")},
                        "reason": f"Validated local subscription-backed model job {job['jobId']}",
                    }
                ),
            }
        )
        status = (
            "PUBLISHED"
            if published["statusCode"] == 200
            else "CONFLICT"
            if published["statusCode"] == 409
            else "FAILED"
        )
        if status == "CONFLICT":
            reconciled = media._profile_record(job["gameId"], job["characterId"])
            if reconciled and all(
                reconciled[2].get("model", {}).get(k) == result[k]
                for k in ("webKey", "sourceKey", "provenanceKey")
            ):
                status = "PUBLISHED"
    raw_db.transact_write_items(
        TransactItems=[
            {
                "Update": {
                    "TableName": table.name,
                    "Key": wire(head),
                    "UpdateExpression": "REMOVE publishing",
                    "ConditionExpression": "publishing = :job",
                    "ExpressionAttributeValues": wire({":job": job["jobId"]}),
                }
            },
            {
                "Update": {
                    "TableName": table.name,
                    "Key": wire(job_key(job["jobId"])),
                    "UpdateExpression": "SET #s = :s",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": wire({":s": status}),
                }
            },
        ]
    )
    return response(200, {"status": status})


def handler(event, _context):
    # Internal invocations require Lambda IAM; these operations are not HTTP routes.
    if "requestContext" not in event:
        job_id = event["jobId"]
        if event["operation"] == "dispatch":
            table.update_item(
                Key=job_key(job_id),
                UpdateExpression="SET #s = :s, taskToken = :token, leaseUntil = :zero",
                ConditionExpression="#s = :submitted OR (#s = :s AND taskToken = :token)",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":s": "QUEUED",
                    ":submitted": "SUBMITTED",
                    ":token": event["taskToken"],
                    ":zero": 0,
                },
            )
        elif event["operation"] == "expire":
            job = get_job(job_id)
            if job and job["status"] not in TERMINAL:
                table.update_item(
                    Key=job_key(job_id),
                    UpdateExpression="SET #s = :s",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": "EXPIRED"},
                )
                try:
                    table.update_item(
                        Key=head_key(job["gameId"], job["characterId"]),
                        UpdateExpression="REMOVE publishing",
                        ConditionExpression="publishing = :job",
                        ExpressionAttributeValues={":job": job_id},
                    )
                except ClientError as exc:
                    if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                        raise
        return {}
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not claims.get("sub") or claims.get("cognito:username") not in media.MODEL_PUBLISHERS:
        return response(403, {"error": "Model jobs require an owner or DM account"})
    try:
        route = event.get("routeKey")
        if route == "GET /model-jobs":
            query = event.get("queryStringParameters") or {}
            if query.get("jobId"):
                job = get_job(query["jobId"])
                return (
                    response(200, public(job)) if job else response(404, {"error": "Job not found"})
                )
            page = jobs_page(query.get("cursor"))
            return response(
                200,
                {
                    "jobs": [public(j) for j in page.get("Items", [])],
                    "nextCursor": page.get("LastEvaluatedKey", {}).get("sk"),
                },
            )
        raw = event.get("body") or "{}"
        if len(raw) > 20000:
            raise ValueError("Request too large")
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw, validate=True)
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("Expected a JSON object")
        if route == "POST /model-reference-sets":
            return submit(body, claims)
        if claims.get("cognito:username") not in WORKERS:
            return response(403, {"error": "This account cannot claim laptop jobs"})
        if route == "POST /model-jobs/claim":
            return claim(claims)
        job = owned_job(body, claims)
        if route == "POST /model-jobs/heartbeat":
            return update_lease(job, body)
        if route == "POST /model-jobs/defer":
            return update_lease(job, body, defer=True)
        if route == "POST /model-jobs/complete":
            return finish(job, body, claims)
        return response(404, {"error": "Unknown job operation"})
    except (ValueError, TypeError, KeyError):
        return response(400, {"error": "Invalid reference set, missing asset, or job lease"})
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        return response(
            409
            if code in {"ConditionalCheckFailedException", "TransactionCanceledException"}
            else 503,
            {"error": "Job changed or storage unavailable; inspect before retrying"},
        )


def stream(event, _context):
    failures = []
    for record in event.get("Records", []):
        try:
            job = {
                k: deserializer.deserialize(v)
                for k, v in record["dynamodb"].get("NewImage", {}).items()
            }
            old = {
                k: deserializer.deserialize(v)
                for k, v in record["dynamodb"].get("OldImage", {}).items()
            }
            if job.get("pk") != "JOBS" or old.get("status") == job.get("status"):
                continue
            if job["status"] == "SUBMITTED":
                try:
                    states.start_execution(
                        stateMachineArn=os.environ["STATE_MACHINE_ARN"],
                        name=job["jobId"],
                        input=json.dumps({"jobId": job["jobId"]}),
                    )
                except ClientError as exc:
                    if exc.response["Error"]["Code"] != "ExecutionAlreadyExists":
                        raise
            elif job["status"] in TERMINAL and job.get("taskToken"):
                try:
                    states.send_task_success(
                        taskToken=job["taskToken"], output=json.dumps({"status": job["status"]})
                    )
                except ClientError as exc:
                    if exc.response["Error"]["Code"] not in {
                        "TaskDoesNotExist",
                        "TaskTimedOut",
                        "InvalidToken",
                    }:
                        raise
        except Exception:
            # Partial batch retries; never leak the stream's callback token into logs.
            failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})
    return {"batchItemFailures": failures}
