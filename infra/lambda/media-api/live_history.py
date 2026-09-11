"""Immutable, paginated provisional chunks. Not a finished transcript or editorial input."""

import hashlib
import json
import os
import re

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

history = boto3.resource("dynamodb").Table(os.environ["LIVE_HISTORY_TABLE"])
PAGE_SIZE = 10


def handle(event, now, presence, actor, publishers):
    from live_recordings import response, slug, validate

    posting = event["routeKey"] == "POST /recordings/live/history"
    if posting:
        claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
        if claims.get("cognito:username", claims.get("username")) not in publishers:
            return response(403, {"error": "Recording publisher required"})
        if event.get("isBase64Encoded") or len(event.get("body", "").encode()) > 250000:
            return response(413, {"error": "History chunk too large"})
        value = json.loads(event["body"])
    else:
        value = event.get("queryStringParameters") or {}
    game, recording, preview = (value[k] for k in ("gameId", "recordingId", "previewId"))
    if not slug(game) or not slug(preview) or not isinstance(recording, str) or not re.fullmatch(r"recording-[a-f0-9]{32}", recording):
        raise ValueError("Invalid history identity")
    parent = presence.get_item(Key={"gameId": game, "recordingId": recording}, ConsistentRead=True).get("Item")
    if not parent or int(parent["expiresAt"]) <= now:
        return response(404, {"error": "Live recording unavailable"})
    header = json.loads(parent["payload"])
    if header["previewId"] != preview:
        return response(409, {"error": "Live preview changed; refresh the recording"})
    feed = f"{game}#{recording}#{preview}"
    if posting:
        if parent["owner"] != actor:
            return response(403, {"error": "Recording belongs to another publisher"})
        if set(value) != {"schemaVersion", "gameId", "recordingId", "previewId", "partIndex",
                          "start", "end", "sourceSha256", "modelSha256", "recognizerSha256", "segments"}:
            raise ValueError("Invalid history fields")
        index = value["partIndex"]
        if value["schemaVersion"] != 1 or type(index) is not int or not 0 <= index < 100000:
            raise ValueError("Invalid history index")
        for field in ("sourceSha256", "modelSha256", "recognizerSha256"):
            if not isinstance(value[field], str) or not re.fullmatch(r"[a-f0-9]{64}", value[field]):
                raise ValueError("Invalid input pin")
        start, end = value["start"], value["end"]
        # Reuse the strict finite timestamps/text/typed-notice contract without accepting a
        # separate heartbeat or advancing recording presence from a history upload.
        validate({**header, "observedAt": int(now * 1000), "segments": value["segments"]}, now,
                 max_segments=1000, max_text=10000)
        bounds = {"start": start, "end": end, "text": "Source bounds"}
        validate({**header, "observedAt": int(now * 1000), "segments": [bounds]}, now)
        if start >= end or any(s["start"] < start or s["end"] > end for s in value["segments"]):
            raise ValueError("History text is outside its source chunk")
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        try:
            history.put_item(Item={"feedId": feed, "partIndex": index, "contentHash": digest,
                "expiresAt": int(parent["expiresAt"]), "payload": encoded},
                ConditionExpression="attribute_not_exists(#i) OR #h = :hash",
                ExpressionAttributeNames={"#i": "partIndex", "#h": "contentHash"},
                ExpressionAttributeValues={":hash": digest})
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return response(409, {"error": "History chunk already exists with different content"})
            raise
        return response(200, {"accepted": True})

    if set(value) - {"gameId", "recordingId", "previewId", "position", "cursor"}:
        raise ValueError("Unknown history query")
    position = value.get("position", "live")
    if position not in {"live", "beginning", "before", "after"}:
        raise ValueError("Invalid history position")
    condition = Key("feedId").eq(feed)
    if position in {"before", "after"}:
        cursor = value.get("cursor", "")
        if not isinstance(cursor, str) or not re.fullmatch(r"\d{1,5}", cursor):
            raise ValueError("Invalid history cursor")
        condition &= Key("partIndex").lt(int(cursor)) if position == "before" else Key("partIndex").gt(int(cursor))
    elif "cursor" in value:
        raise ValueError("Unexpected history cursor")
    args = {"KeyConditionExpression": condition, "ScanIndexForward": position in {"beginning", "after"},
            "ConsistentRead": True, "Limit": PAGE_SIZE}
    chunks = []
    # TTL deletion is asynchronous: never expose expired chunks, including on a full expired page.
    while len(chunks) < PAGE_SIZE:
        args["Limit"] = PAGE_SIZE - len(chunks)
        page = history.query(**args)
        chunks.extend(json.loads(row["payload"]) for row in page.get("Items", []) if int(row["expiresAt"]) > now)
        if "LastEvaluatedKey" not in page:
            break
        args["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    chunks.sort(key=lambda c: c["partIndex"])
    return response(200, {"chunks": chunks, "position": position, "pageSize": PAGE_SIZE,
                          "reviewStatus": "provisional", "retentionDays": 7})
