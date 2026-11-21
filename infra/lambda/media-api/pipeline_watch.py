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


def _backfill_log(scanned, sent, counts, seeded, stored):
    kinds = ",".join(f"{name}={count}" for name, count in sorted(counts.items())) or "none"
    # print reaches the Lambda log. The root logger drops INFO.
    print(f"pipeline backfill: scanned {scanned} runs, published {sent} samples by pipeline {kinds}, ledger seeded={seeded} stored={stored}", flush=True)


def backfill_metrics(now):
    """Record each sample key once. History already in CloudWatch is claimed, not sent again."""
    from pipeline_metrics import LEDGER_SK, claim_samples, points_for_backfill, publish, with_sample_keys
    import boto3
    marker = INDEX.get_item(Key={"pk": "SYSTEM", "sk": LEDGER_SK}, ConsistentRead=True).get("Item") or {}
    seeded = bool(marker.get("seeded"))
    started = float(marker.get("startedAt") or now)
    stored = int(marker.get("samples") or 0)
    cursor = marker.get("cursor")
    points = []
    scanned = 0
    finished = False
    for _ in range(8):
        args = {"Limit": 100, "ProjectionExpression": "pk, sk, kind, #s, createdAt, completedAt, reportedAt, observedAt, updatedAt",
                "ExpressionAttributeNames": {"#s": "status"}}
        if cursor:
            args["ExclusiveStartKey"] = cursor
        page = INDEX.scan(**args)
        for item in page.get("Items", []):
            if not str(item.get("pk", "")).startswith("GAME#"):
                continue
            scanned += 1
            points.extend(with_sample_keys(points_for_backfill(item, now), item["pk"], item.get("sk") or item.get("id") or ""))
        cursor = page.get("LastEvaluatedKey")
        if not cursor:
            finished = True
            break
    if seeded:
        chosen = points
        publish_now = True
    else:
        # The v2 scan already sent these. Claiming them keeps the next pass from sending them again.
        chosen = [point for point in points if point.get("Timestamp", 0) < started]
        publish_now = False
    claimed = claim_samples(INDEX, chosen, publish=publish_now)
    counts = {}
    for point in claimed:
        kind = point["Dimensions"][0]["Value"]
        counts[kind] = counts.get(kind, 0) + 1
    sent = publish(claimed, boto3.client("cloudwatch"), now) if publish_now else 0
    saved = {"pk": "SYSTEM", "sk": LEDGER_SK, "seenAt": int(now), "startedAt": int(started),
             "samples": stored + sent, "seeded": seeded or finished}
    if cursor and not (finished and not seeded):
        saved["cursor"] = cursor
    INDEX.put_item(Item=saved)
    _backfill_log(scanned, sent, counts, bool(saved["seeded"]), stored + sent)
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
