"""Scheduled notice when a worker stops checking in or a callback sits unclaimed."""

import json
import logging
import os
import time

import boto3
from boto3.dynamodb.conditions import Key

INDEX = boto3.resource("dynamodb").Table(os.environ["WORKSHOP_TABLE"])
SNS = boto3.client("sns")
TABLES = json.loads(os.environ["JOB_TABLES"])
STALE = int(os.environ.get("STALE_SECONDS", "1200"))
WORKERS = ("editorial", "playback", "model")
PARTITIONS = {"editorial": "TASKS", "model": "JOBS", "playback": "SETS"}


def publish(message):
    SNS.publish(
        TopicArn=os.environ["TOPIC_ARN"],
        Subject="Panther pipeline needs a worker",
        Message=message[:2000],
    )


def worker_alerts(now):
    alerts = []
    for name in WORKERS:
        item = INDEX.get_item(Key={"pk": "SYSTEM", "sk": "worker#" + name}, ConsistentRead=True).get("Item") or {}
        seen = int(item.get("seenAt") or 0)
        fresh = bool(seen) and now - seen < STALE
        if fresh or item.get("status") == "offline":
            continue
        INDEX.put_item(Item={
            "pk": "SYSTEM", "sk": "worker#" + name, "worker": name, "seenAt": seen, "status": "offline",
        })
        when = "never" if not seen else str(seen)
        alerts.append(f"{name} worker offline or its Panther sign-in expired. Last heartbeat: {when}.")
    return alerts


def stalled_alerts(now):
    alerts = []
    resource = boto3.resource("dynamodb")
    for kind, name in TABLES.items():
        partition = PARTITIONS.get(kind)
        if not partition:
            continue
        page = resource.Table(name).query(
            KeyConditionExpression=Key("pk").eq(partition), Limit=100, ConsistentRead=True,
        )
        for item in page.get("Items", []):
            state = item.get("status")
            if state not in {"QUEUED", "RUNNING"} or int(item.get("notBefore") or 0) > now:
                continue
            if state == "RUNNING" and int(item.get("leaseUntil") or 0) > now:
                continue
            queued = int(item.get("queuedAt") or item.get("createdAt") or 0)
            if not queued or now - queued < STALE:
                continue
            identity = str(item.get("jobId") or item.get("sk") or "")[:16]
            alerts.append(
                f"{kind} {identity} has been {state} without an active worker for more than "
                f"{STALE // 60} minutes."
            )
            if len(alerts) >= 20:
                return alerts
    return alerts


def backfill_metrics(now):
    """Recent workshop runs, a few pages per visit. CloudWatch only accepts 14 days of history."""
    marker = INDEX.get_item(Key={"pk": "SYSTEM", "sk": "pipeline-metrics-v2"}, ConsistentRead=True).get("Item") or {}
    if marker.get("done"):
        return 0
    from pipeline_metrics import points_for_backfill, publish
    import boto3
    points = []
    cursor = marker.get("cursor")
    finished = False
    for _ in range(8):
        args = {"Limit": 100, "ProjectionExpression": "pk, sk, kind, #s, createdAt, completedAt, reportedAt, observedAt, updatedAt",
                "ExpressionAttributeNames": {"#s": "status"}}
        if cursor:
            args["ExclusiveStartKey"] = cursor
        page = INDEX.scan(**args)
        for item in page.get("Items", []):
            points.extend(points_for_backfill(item, now))
        cursor = page.get("LastEvaluatedKey")
        if not cursor:
            finished = True
            break
    sent = publish(points, boto3.client("cloudwatch"), now)
    saved = {"pk": "SYSTEM", "sk": "pipeline-metrics-v2", "seenAt": int(now),
             "samples": int(marker.get("samples", 0)) + sent, "done": finished}
    if cursor and not finished:
        saved["cursor"] = cursor
    INDEX.put_item(Item=saved)
    return sent


def handler(_event, _context):
    now = int(time.time())
    try:
        backfill_metrics(now)
    except Exception:
        logging.getLogger("pipeline_watch").exception("pipeline metric backfill failed")
    alerts = worker_alerts(now) + stalled_alerts(now)
    message = "\n".join(alerts)
    previous = INDEX.get_item(Key={"pk": "SYSTEM", "sk": "watch-alert"}, ConsistentRead=True).get("Item") or {}
    if message != previous.get("message", ""):
        if message:
            publish(message)
        INDEX.put_item(Item={"pk": "SYSTEM", "sk": "watch-alert", "message": message[:2000], "seenAt": now})
    return {"alerts": len(alerts)}
