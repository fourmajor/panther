"""Leased API image requests; AWS coordinates, laptop workers run inference."""

import hashlib
import base64
import json
import os
import re
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from access_policy import authorized
import index as media

TYPES = {"image", "map", "blueprint", "location", "portrait"}
MODELS = {"gpt-image-1", "gpt-image-1.5", "gpt-image-1-mini"}
STYLES = {"photorealistic", "anime", "illustrated-fantasy", "comic-book", "watercolor", "oil-painting", "stylized-3d", "pixel-art"}

def options(game):
    if not media._valid_slug(game):
        raise ValueError("Choose a game")
    record = boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"]).get_item(Key={"pk":"GAMES","sk":game}, ConsistentRead=True).get("Item")
    if not record:
        raise ValueError("Game not found")
    return {"generationTypes":[{"id":kind,"name":"Image" if kind == "image" else kind.title(),"available":True,"models":[{"id":model,"name":model,"inputs":{}} for model in sorted(MODELS)],"defaultModel":"gpt-image-1","styles":[{"id":style,"name":style.replace("-"," ").title()} for style in sorted(STYLES)],"defaultStyle":record.get("visualStyle","illustrated-fantasy")} for kind in sorted(TYPES)], "renameSupported":False}


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
    required = {"gameId", "type", "prompt", "operationId"}
    allowed = required | {"name", "model", "style", "visualStyle", "characterId", "selectAsPortrait"}
    if not isinstance(body, dict) or not required <= set(body) <= allowed:
        raise ValueError("Choose an asset type and prompt")
    game = body["gameId"]
    if not media._valid_slug(game) or not isinstance(body["type"], str) or body["type"] not in TYPES:
        raise ValueError("Invalid asset type or game")
    if not isinstance(body["operationId"], str) or not re.fullmatch(r"[a-f0-9]{32}", body["operationId"]):
        raise ValueError("Invalid generation operation")
    if not isinstance(body["prompt"], str) or not 1 <= len(body["prompt"].strip()) <= 4000:
        raise ValueError("Describe the asset to generate")
    if "name" in body and (not isinstance(body["name"], str) or not 1 <= len(body["name"].strip()) <= 160):
        raise ValueError("Invalid asset name")
    style = body.get("style", body.get("visualStyle"))
    if (
        "style" in body and "visualStyle" in body
        or not isinstance(body.get("model", "gpt-image-1"), str)
        or body.get("model", "gpt-image-1") not in MODELS
        or style is not None and (not isinstance(style, str) or style not in STYLES)
    ):
        raise ValueError("Choose a supported model and visual style")
    if "selectAsPortrait" in body and (type(body["selectAsPortrait"]) is not bool or body["type"] != "portrait" or not body.get("characterId")):
        raise ValueError("Only a character portrait can become the official portrait")
    game_record = (
        boto3.resource("dynamodb")
        .Table(os.environ["CATALOG_TABLE"])
        .get_item(Key={"pk": "GAMES", "sk": game}, ConsistentRead=True)
        .get("Item")
    )
    if not game_record:
        raise ValueError("Game not found")
    character_reference = None
    if body["type"] == "portrait" or body.get("characterId"):
        character = body.get("characterId")
        if not media._valid_slug(character):
            raise ValueError("Choose a registered character")
        record = (
            boto3.resource("dynamodb")
            .Table(os.environ["CATALOG_TABLE"])
            .get_item(
                Key={"pk": f"GAME#{game}", "sk": f"CHARACTER#{character}"}, ConsistentRead=True
            )
            .get("Item")
        )
        if (
            not record
            or record.get("gameId") != game
            or record.get("id") != character
            or not record.get("detailsRevision")
        ):
            raise ValueError("Choose an initialized same-game character")
        character_reference = {
            "characterId": character,
            "name": record["name"],
            "revision": record["detailsRevision"],
            "details": json.loads(record["detailsJson"]),
        }
        if len(json.dumps(character_reference).encode()) > 64000:
            raise ValueError("Character details exceed the portrait request limit")
    request = {**body, "schemaVersion": 2}
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
        "visualStyle": style or game_record.get("visualStyle", "illustrated-fantasy"),
        "model": body.get("model", "gpt-image-1"),
        "generationAuthorized": True,
        **({"characterReference": character_reference} if character_reference else {}),
    }
    stored = read(job_id)
    if stored:
        if any(stored.get(k) != v for k, v in body.items()):
            raise ValueError("Generation operation was already used with different inputs")
        return public(stored)
    import asset_archive
    from boto3.dynamodb.types import TypeSerializer
    serializer = TypeSerializer()
    source_keys = []
    if character_reference:
        thumbnail = character_reference['details'].get('thumbnailAssetKey')
        if thumbnail:
            source_keys.append(thumbnail)
    try:
        boto3.client('dynamodb').transact_write_items(TransactItems=[{'Put': {
            'TableName': table().name, 'Item': {key: serializer.serialize(value) for key, value in record.items()},
            'ConditionExpression': 'attribute_not_exists(pk)'}},
            *asset_archive.reference_writes(game, 'asset-generation:' + job_id, source_keys,
                active={'table': table().name, 'pk': 'JOBS', 'sk': job_id})])
    except ClientError as exc:
        if exc.response['Error']['Code'] != 'TransactionCanceledException':
            raise
        if not read(job_id):
            raise ValueError('A selected source was archived; choose another source') from exc
    stored = read(job_id)
    if any(stored.get(k) != v for k, v in body.items()):
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


def jobs_page(game, cursor=None, character_id=None):
    if not media._valid_slug(game):
        raise ValueError("Choose a game")
    args = {
        "IndexName": "GameIndex",
        "KeyConditionExpression": Key("gameId").eq(game),
        "Limit": 25,
        "ScanIndexForward": False,
    }
    if character_id:
        if not media._valid_slug(character_id):
            raise ValueError("Choose a registered character")
        args["FilterExpression"] = Attr("characterId").eq(character_id)
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
        if job.get("characterId") and job["characterId"] not in metadata.get("characterIds", []):
            raise ValueError("Portrait must explicitly depict the requested character")
        generation = extra.get("generation")
        cost = generation.get("cost") if isinstance(generation, dict) else None
        if (
            not isinstance(generation, dict)
            or generation.get("provider") != "OpenAI"
            or not isinstance(cost, dict)
            or cost.get("status") not in {"unknown", "billed", "estimated", "subscription"}
            or (job.get("schemaVersion") == 2 and generation.get("model") != job["model"])
            or extra.get("relationshipRole") != "finished"
        ):
            raise ValueError("Output requires honest generation metadata")
        if (
            head.get("ContentType") != "image/png"
            or not 0 < head.get("ContentLength", 0) <= 20 * 1024**2
            or not head.get("ChecksumSHA256")
            or head["ChecksumSHA256"] != extra.get("sha256")
        ):
            raise ValueError("Generated image bytes are unavailable or changed")
        title = metadata.get("title")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
            raise ValueError("Generated output requires its actual title")
        updates.update(status="PUBLISHED", assetKey=key, name=title)
    elif operation == "defer":
        message = body["message"]
        if not isinstance(message, str) or not 1 <= len(message) <= 500:
            raise ValueError("Invalid generation failure")
        updates.update(status="ATTENTION", message=message)
    names = {f"#u{i}": k for i, k in enumerate(updates)}
    values = {f":u{i}": v for i, v in enumerate(updates.values())}
    values.update({":lease": body["lease"], ":actor": claims["sub"]})
    if operation == "complete" and job.get("selectAsPortrait") is True:
        catalog = boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"])
        old = catalog.get_item(Key={"pk": f"GAME#{job['gameId']}", "sk": f"CHARACTER#{job['characterId']}"}, ConsistentRead=True).get("Item")
        if old and old.get("detailsRevision") == job.get("characterReference", {}).get("revision"):
            from boto3.dynamodb.types import TypeSerializer
            from datetime import datetime, timezone
            import asset_archive
            serializer = TypeSerializer()
            def encode(value):
                return {k: serializer.serialize(v) for k, v in value.items()}
            details = json.loads(old["detailsJson"])
            details["thumbnailAssetKey"] = body["assetKey"]
            revision = uuid.uuid4().hex
            revised = {**old, "detailsRevision": revision, "detailsThumbnailKey": body["assetKey"], "detailsJson": json.dumps(details, separators=(",", ":"))}
            history = {"pk": f"CHARACTER_DETAILS_HISTORY#{job['gameId']}#{job['characterId']}", "sk": revision, "revision": revision,
                       "name": old["name"], "previousName": old["name"], "detailsJson": revised["detailsJson"], "previousDetailsJson": old["detailsJson"],
                       "previousRevision": old["detailsRevision"], "recordedAt": datetime.now(timezone.utc).isoformat(), "actor": claims["sub"], "reason": "Selected generated portrait"}
            updates["portraitAssigned"] = True
            revised_job = {**job, **updates}
            writes = [
                {"Put": {"TableName": catalog.name, "Item": encode(revised), "ConditionExpression": "detailsRevision=:revision", "ExpressionAttributeValues": encode({":revision": old["detailsRevision"]})}},
                {"Put": {"TableName": catalog.name, "Item": encode(history), "ConditionExpression": "attribute_not_exists(pk)"}},
                {"Put": {"TableName": table().name, "Item": encode(revised_job), "ConditionExpression": "lease=:lease AND actor=:actor AND #state=:generating", "ExpressionAttributeNames": {"#state": "status"}, "ExpressionAttributeValues": encode({":lease": body["lease"], ":actor": claims["sub"], ":generating": "GENERATING"})}},
            ]
            owner = f"character:{job['characterId']}"
            reference_key = {"pk": f"asset-references-v1#{job['gameId']}", "sk": owner}
            previous_references = asset_archive.db().get_item(Key=reference_key, ConsistentRead=True).get("Item")
            reference_keys = [body["assetKey"], json.loads(old["detailsJson"]).get("thumbnailAssetKey"), *(previous_references or {}).get("keys", [])]
            reference_operations = asset_archive.reference_writes(job["gameId"], owner, reference_keys, active=(previous_references or {}).get("active"))
            for operation in reference_operations:
                put = operation.get("Put")
                if put and put["Item"].get("sk") == encode({"sk": owner})["sk"]:
                    put["ConditionExpression"] = "#keys=:previous" if previous_references else "attribute_not_exists(pk)"
                    if previous_references:
                        put["ExpressionAttributeNames"] = {"#keys": "keys"}
                        put["ExpressionAttributeValues"] = encode({":previous": previous_references["keys"]})
            writes.extend(reference_operations)
            boto3.client("dynamodb").transact_write_items(TransactItems=writes)
            return public(revised_job)
        updates.update(portraitAssigned=False, assignmentMessage="The profile changed during generation. The portrait is available in Assets.")
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
            if q.get("view") == "options":
                return media._response(200, options(q.get("gameId")))
            if not q.get("jobId"):
                return media._response(200, jobs_page(q.get("gameId"), q.get("cursor"), q.get("characterId")))
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
        return media._response(400, {"error": "Choose a valid asset type and prompt"})
    except ClientError:
        return media._response(503, {"error": "Asset generation is temporarily unavailable"})
