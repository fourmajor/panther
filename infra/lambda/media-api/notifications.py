"""Durable per-account workflow notices and read receipts; never dispatch work."""

import base64
import hashlib
import json
import os
import re
import time

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

from access_policy import authorized


def event_for(workflow):
    game, identity, kind = (workflow.get(k, "") for k in ("gameId", "id", "kind"))
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", game) or not re.fullmatch(
        r"[a-z-]+~[a-z0-9-]{1,80}", identity
    ) or identity.split("~")[0] != kind:
        return None
    failed = workflow.get("status") == "failed" or workflow.get("sourceStatus") in {"FAILED", "CONFLICT", "ATTENTION", "CANCELLED", "ABORTED"}
    review = workflow.get("sourceStatus") == "READY_FOR_VIDEO_DISCUSSION" or any(
        s.get("id") in {"storyboard-approval", "human-review", "owner-approval"}
        and s.get("status") in {"paused", "queued"}
        for s in workflow.get("stages", [])
    )
    if not failed and not review:
        return None
    category = "failure" if failed else "review"
    notice_id = hashlib.sha256(f"v1:{game}:{identity}:{category}".encode()).hexdigest()
    return {"id": notice_id, "gameId": game, "workflowId": identity, "workflowKind": kind,
            "type": category, "title": "Workflow did not complete successfully" if failed else "Storyboard review requested" if workflow.get("sourceStatus") == "READY_FOR_VIDEO_DISCUSSION" else "Workflow review requested",
            "description": str(workflow.get("title") or "Workflow")[:240],
            "target": {"type": "workflow", "gameId": game, "kind": kind, "id": identity},
            "createdAt": int(time.time()), "schemaVersion": 1}


def db():
    return boto3.resource("dynamodb").Table(os.environ["NOTIFICATIONS_TABLE"])


def partition(username):
    return "USER#" + hashlib.sha256(username.encode()).hexdigest()


def publish(workflow):
    notice = event_for(workflow)
    if not notice:
        return
    table, serializer = db(), TypeSerializer()
    for username in sorted(set(filter(None, os.environ.get("CATALOG_READERS", "").split(",")))):
        pk = partition(username)
        suffix = f'{notice["createdAt"]:020d}#{notice["id"]}'
        marker = {"pk": pk, "sk": "N#" + notice["id"], "suffix": suffix}
        row = {**notice, "pk": pk, "sk": "A#" + suffix}
        unread = {**row, "sk": "U#" + suffix}
        writes = []
        for item in (marker, row, unread):
            put = {"TableName": table.name, "Item": serializer.serialize(item)["M"]}
            if item is marker:
                put["ConditionExpression"] = "attribute_not_exists(pk)"
            writes.append({"Put": put})
        try:
            boto3.client("dynamodb").transact_write_items(TransactItems=writes)
        except ClientError as exc:
            reasons = exc.response.get("CancellationReasons", [])
            if exc.response["Error"]["Code"] == "TransactionCanceledException" and reasons and reasons[0].get("Code") == "ConditionalCheckFailed" and all(r.get("Code") in {"None", "ConditionalCheckFailed"} for r in reasons):
                continue  # Duplicate delivery/backfill never resurrects an already read notice.
            raise


def reply(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "body": json.dumps(body, default=lambda value: int(value))}


def public(row):
    return {**{k: v for k, v in row.items() if k not in {"pk", "sk"}}, "readAt": row.get("readAt")}


def handler(event, _context):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "CATALOG_READERS"):
        return reply(403, {"error": "Notification access denied"})
    pk = partition(claims.get("cognito:username", claims.get("username")))
    table = db()
    try:
        if event.get("routeKey") == "POST /notifications/read":
            if len(event.get("body") or "") > 1024:
                raise ValueError("Invalid request")
            body = json.loads(event.get("body") or "{}")
            if set(body) != {"id"} or not isinstance(body["id"], str) or not re.fullmatch(r"[a-f0-9]{64}", body["id"]):
                raise ValueError("Invalid notification")
            marker = table.get_item(Key={"pk": pk, "sk": "N#" + body["id"]}, ConsistentRead=True).get("Item")
            if not marker:
                return reply(404, {"error": "Notification not found"})
            serializer = TypeSerializer()
            def key(sk):
                return serializer.serialize({"pk": pk, "sk": sk})["M"]
            boto3.client("dynamodb").transact_write_items(TransactItems=[
                {"Update": {"TableName": table.name, "Key": key("A#" + marker["suffix"]),
                            "UpdateExpression": "SET readAt = if_not_exists(readAt, :now)",
                            "ExpressionAttributeValues": {":now": {"N": str(int(time.time()))}},
                            "ConditionExpression": "attribute_exists(pk)"}},
                {"Delete": {"TableName": table.name, "Key": key("U#" + marker["suffix"])}}
            ])
            return reply(200, {"read": True, "id": body["id"]})
        if event.get("routeKey") != "GET /notifications":
            return reply(404, {"error": "Unknown notification route"})
        if not table.get_item(Key={"pk": "SYSTEM", "sk": "notifications-v1"}, ConsistentRead=True).get("Item", {}).get("ready"):
            return reply(503, {"error": "Notification history is being prepared. Please try again shortly."})
        q = event.get("queryStringParameters") or {}
        if len(q.get("cursor", "")) > 4096:
            raise ValueError("Invalid cursor")
        prefix = "U#" if q.get("view") == "unread" else "A#"
        if q.get("view", "all") not in {"unread", "all"}:
            raise ValueError("Unknown view")
        args = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix),
                "Limit": 10 if prefix == "U#" else 30, "ScanIndexForward": False, "ConsistentRead": True}
        if q.get("cursor"):
            pointer = json.loads(base64.urlsafe_b64decode(q["cursor"]))
            if set(pointer) != {"pk", "sk"} or pointer["pk"] != pk or not isinstance(pointer["sk"], str) or not pointer["sk"].startswith(prefix):
                raise ValueError("Foreign cursor")
            args["ExclusiveStartKey"] = pointer
        page = table.query(**args)
        cursor = base64.urlsafe_b64encode(json.dumps(page["LastEvaluatedKey"]).encode()).decode() if page.get("LastEvaluatedKey") else None
        return reply(200, {"notifications": [public(row) for row in page.get("Items", [])], "cursor": cursor, "schemaVersion": 1})
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return reply(400, {"error": "Invalid notification request"})


def project_handler(event, _context):
    if "Records" in event:
        failures = []
        for record in event["Records"]:
            try:
                item = TypeDeserializer().deserialize({"M": record.get("dynamodb", {}).get("NewImage", {})})
                if item.get("pk", "").startswith("GAME#"):
                    publish(item)
            except Exception:
                failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})
        return {"batchItemFailures": failures}
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "MODEL_WORKERS"):
        return reply(403, {"error": "Notification rebuild requires worker access"})
    try:
        if len(event.get("body") or "") > 8192:
            raise ValueError("Invalid rebuild request")
        body = json.loads(event.get("body") or "{}")
        workshop = boto3.resource("dynamodb").Table(os.environ["WORKSHOP_TABLE"])
        marker = workshop.get_item(Key={"pk": "SYSTEM", "sk": "workshop-v1"}, ConsistentRead=True).get("Item", {})
        if set(marker.get("sources", [])) != set(json.loads(os.environ["WORKSHOP_SOURCES"])) or marker.get("hierarchyVersion") != 1:
            return reply(503, {"error": "Complete the workflow-history rebuild before notifications."})
        args = {"Limit": 25, "ConsistentRead": True}
        if body.get("cursor"):
            pointer = json.loads(base64.urlsafe_b64decode(body["cursor"]))
            if not isinstance(pointer, dict) or set(pointer) != {"pk", "sk"} or not all(isinstance(value, str) and 0 < len(value) <= 1024 for value in pointer.values()):
                raise ValueError("Invalid rebuild cursor")
            args["ExclusiveStartKey"] = pointer
        page = workshop.scan(**args)
        for item in page.get("Items", []):
            if item.get("pk", "").startswith("GAME#"):
                publish(item)
        pointer = page.get("LastEvaluatedKey")
        if not pointer:
            db().put_item(Item={"pk": "SYSTEM", "sk": "notifications-v1", "ready": True, "verifiedAt": int(time.time())})
        return reply(200, {"inspected": len(page.get("Items", [])), "complete": not bool(pointer),
                           "cursor": base64.urlsafe_b64encode(json.dumps(pointer).encode()).decode() if pointer else None})
    except (ValueError, TypeError, KeyError):
        return reply(400, {"error": "Invalid rebuild request"})
