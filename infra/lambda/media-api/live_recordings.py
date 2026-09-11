"""Authenticated, short-lived live preview/presence. No S3 assets or workflow events."""

import base64
import json
import math
import os
import re
import time

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

table = boto3.resource("dynamodb").Table(os.environ["LIVE_RECORDINGS_TABLE"])
PUBLISHERS = set(os.environ.get("LIVE_RECORDING_PUBLISHERS", "").split(","))
TTL = 7 * 86400
STALE_SECONDS = 75


def response(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "body": json.dumps(body, allow_nan=False)}


def slug(value):
    return isinstance(value, str) and len(value) <= 96 and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value)


def validate(body, now, *, max_segments=60, max_text=500):
    if not isinstance(body, dict) or set(body) != {
        "schemaVersion", "gameId", "sessionId", "recordingId", "previewId", "observedAt",
        "captureState", "captureSeconds", "segments", "previewState", "omittedChunks",
    }:
        raise ValueError("Invalid live preview fields")
    if body["schemaVersion"] != 1 or not all(slug(body[k]) for k in ("gameId", "sessionId", "previewId")):
        raise ValueError("Invalid live preview identity")
    if not isinstance(body["recordingId"], str) or not re.fullmatch(r"recording-[a-f0-9]{32}", body["recordingId"]):
        raise ValueError("Invalid recording identity")
    if type(body["observedAt"]) is not int or abs(body["observedAt"] / 1000 - now) > 90:
        raise ValueError("Preview observation expired; check laptop clock")
    if body["captureState"] not in {"recording", "stalled", "stopped"}:
        raise ValueError("Invalid capture state")
    if body["previewState"] not in {"starting", "transcribing", "catching-up", "waiting-for-chunk", "stopped", "preview-stopped", "preview-error"}:
        raise ValueError("Invalid preview state")
    if type(body["omittedChunks"]) is not int or not 0 <= body["omittedChunks"] <= 100000:
        raise ValueError("Invalid omitted chunk count")
    seconds = body["captureSeconds"]
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= 7 * 86400:
        raise ValueError("Invalid capture time")
    if not isinstance(body["segments"], list) or len(body["segments"]) > max_segments:
        raise ValueError("Preview segment limit exceeded")
    previous = -1
    for segment in body["segments"]:
        if not isinstance(segment, dict) or not {"start", "end", "text"} <= set(segment) or set(segment) - {"start", "end", "text", "approximateTiming", "kind"}:
            raise ValueError("Invalid preview segment; speakers remain unassigned")
        if "kind" in segment and (segment["kind"] != "preview-gap" or "approximateTiming" in segment):
            raise ValueError("Invalid preview notice")
        if "approximateTiming" in segment and type(segment["approximateTiming"]) is not bool:
            raise ValueError("Invalid timing annotation")
        a, b = segment["start"], segment["end"]
        if any(type(n) not in (int, float) or not math.isfinite(n) for n in (a, b)) or not 0 <= a <= b <= seconds + 1 or a < previous:
            raise ValueError("Invalid preview timestamps")
        previous = a
        if not isinstance(segment["text"], str) or not 1 <= len(segment["text"]) <= max_text:
            raise ValueError("Invalid preview text")


def handle(event, now):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    actor = claims.get("sub")
    if not isinstance(actor, str) or not actor:
        return response(401, {"error": "Sign in required"})
    if event.get("routeKey") in {"GET /recordings/live/history", "POST /recordings/live/history"}:
        from live_history import handle as history_handle
        return history_handle(event, now, table, actor, PUBLISHERS)
    if event.get("routeKey") == "POST /recordings/live":
        if claims.get("cognito:username", claims.get("username")) not in PUBLISHERS:
            return response(403, {"error": "Recording publisher required"})
        raw = event.get("body", "")
        if len(raw) > 50000:
            return response(413, {"error": "Live preview too large"})
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw, validate=True).decode()
        if len(raw.encode()) > 36000:
            return response(413, {"error": "Live preview too large"})
        body = json.loads(raw)
        validate(body, now)
        try:
            table.put_item(Item={"gameId": body["gameId"], "recordingId": body["recordingId"],
                "owner": actor, "observedAt": body["observedAt"], "receivedAt": int(now),
                "expiresAt": int(now) + TTL, "payload": json.dumps(body, allow_nan=False)},
                ConditionExpression="attribute_not_exists(#r) OR (#o = :owner AND #t < :observed)",
                ExpressionAttributeNames={"#r": "recordingId", "#o": "owner", "#t": "observedAt"},
                ExpressionAttributeValues={":owner": actor, ":observed": body["observedAt"]})
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return response(409, {"error": "Outdated update or recording belongs to another publisher"})
            raise
        return response(200, {"accepted": True})
    if event.get("routeKey") == "GET /recordings/live":
        game = (event.get("queryStringParameters") or {}).get("gameId")
        if not slug(game):
            raise ValueError("Invalid game identifier")
        records, args = [], {"KeyConditionExpression": Key("gameId").eq(game), "ConsistentRead": True, "Limit": 100}
        while True:
            page = table.query(**args)
            for item in page.get("Items", []):
                if int(item["expiresAt"]) <= now:
                    continue
                body = json.loads(item["payload"])
                age = max(0, now - int(item["receivedAt"]), now - body["observedAt"] / 1000)
                records.append({**body, "heartbeatAgeSeconds": int(age),
                    "connectionStale": age > STALE_SECONDS, "expiresAt": int(item["expiresAt"]),
                    "reviewStatus": "provisional", "speakerMethod": "unassigned"})
            if "LastEvaluatedKey" not in page or len(records) >= 100:
                break
            args["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        records.sort(key=lambda r: r["observedAt"], reverse=True)
        return response(200, {"recordings": records[:10], "truncated": len(records) > 10 or "LastEvaluatedKey" in page,
                              "staleAfterSeconds": STALE_SECONDS})
    return response(404, {"error": "Not found"})


def handler(event, _context):
    try:
        return handle(event, time.time())
    except (ValueError, TypeError, KeyError, UnicodeError):
        return response(400, {"error": "Invalid live preview request"})
    except ClientError:
        # Never log private transcript text, requests or credentials.
        return response(502, {"error": "Live feed temporarily unavailable"})
