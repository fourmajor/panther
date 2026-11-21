"""Counts and durations for workshop pipeline runs.

One series per pipeline kind. No session, job, or game dimension: each extra value
is another billed CloudWatch metric. Samples use one-minute resolution.
"""

import re
import time
from datetime import datetime, timezone
from decimal import Decimal

NAMESPACE = "Panther/Pipelines"
MAX_AGE = 14 * 24 * 3600 - 3600
MAX_DURATION_MS = 40 * 24 * 3600 * 1000
RECENT = 30 * 60


def _kind(item):
    kind = item.get("kind") if isinstance(item, dict) else None
    if isinstance(kind, str) and re.fullmatch(r"[a-z0-9-]{1,64}", kind.strip().lower()):
        return kind.strip().lower()
    return "other"


_RAW_STATUS = {
    "SUBMITTED": "queued", "QUEUED": "queued", "RUNNING": "running", "PROCESSING": "running",
    "DONE": "done", "NOVEL_READY": "done", "READY_FOR_VIDEO_DISCUSSION": "done",
    "FAILED": "failed", "BLOCKED": "paused", "DEFERRED": "paused", "IN_QUEUE": "queued",
    "IN_PROGRESS": "running", "PUBLISHED": "done", "ATTENTION": "failed", "UNKNOWN": "unknown",
    "GENERATING": "running", "COMPOSING": "running",
}


def _num(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text).timestamp()
        except ValueError:
            return None
    if isinstance(value, (int, float, Decimal)):
        number = float(value)
        if number > 0 and number == number:
            return number
    return None


def _status(value):
    if isinstance(value, str) and value in {"pending", "queued", "running", "done", "failed", "paused", "unknown", "started"}:
        return value
    if isinstance(value, str):
        return _RAW_STATUS.get(value, value.strip().lower() or "unknown")
    return "unknown"


def _end(item):
    # observedAt is when a projection ran, so it is only a last resort.
    for field in ("completedAt", "endedAt", "reportedAt", "updatedAt", "observedAt"):
        value = _num(item.get(field))
        if value:
            return value
    return None


def _duration_ms(item):
    start = _num(item.get("createdAt"))
    end = _end(item)
    if not start or not end or end < start:
        return None
    duration = int((end - start) * 1000)
    if duration > MAX_DURATION_MS:
        return None
    return duration


def _point(name, kind, timestamp, value, unit):
    return {
        "MetricName": name,
        "Dimensions": [{"Name": "Pipeline", "Value": kind}],
        "Timestamp": float(timestamp),
        "Value": float(value),
        "Unit": unit,
    }


def points_for_transition(previous, current, now=None):
    """Samples for one status change. Repeating the same status emits nothing."""
    if not isinstance(current, dict):
        return []
    now = float(now if now is not None else time.time())
    kind = _kind(current)
    new = _status(current.get("status"))
    old = _status(previous.get("status")) if isinstance(previous, dict) else None
    points = []
    if not isinstance(previous, dict):
        points.append(_point("RunsStarted", kind, _num(current.get("createdAt")) or now, 1, "Count"))
    end = _end(current) or now
    if new == "done" and old != "done":
        points.append(_point("RunsSucceeded", kind, end, 1, "Count"))
    elif new == "failed" and old != "failed":
        points.append(_point("RunsFailed", kind, end, 1, "Count"))
    else:
        return points
    duration = _duration_ms(current)
    if duration is not None:
        points.append(_point("RunDuration", kind, end, duration, "Milliseconds"))
    return points


def points_for_backfill(item, now):
    """Historical samples whose own timestamp CloudWatch will accept.

    A run that started before the 14-day window can still publish its finish
    when that finish is inside the window. The start sample is kept only when
    its own timestamp is inside the window.
    """
    if not isinstance(item, dict) or not str(item.get("pk", "")).startswith("GAME#"):
        return []
    now = float(now)
    created = _num(item.get("createdAt"))
    end = _end(item)
    activity = end or created
    if not activity or activity > now - RECENT:
        return []
    current = {**item, "status": _status(item.get("status"))}
    if current["status"] in {"done", "failed"}:
        points = points_for_transition(None, current, now)
        if not created:
            points = [point for point in points if point["MetricName"] != "RunsStarted"]
    elif created:
        points = [_point("RunsStarted", _kind(item), created, 1, "Count")]
    else:
        return []
    return [
        point for point in points
        if now - MAX_AGE < point["Timestamp"] <= now + 120
    ]


def publish(points, client, now=None):
    now = float(now if now is not None else time.time())
    fresh = [
        point for point in points
        if isinstance(point.get("Timestamp"), (int, float)) and now - MAX_AGE < point["Timestamp"] <= now + 120
    ]
    if not fresh or client is None:
        return 0
    sent = 0
    for offset in range(0, len(fresh), 20):
        batch = fresh[offset:offset + 20]
        client.put_metric_data(Namespace=NAMESPACE, MetricData=[{
            "MetricName": point["MetricName"],
            "Dimensions": point["Dimensions"],
            "Timestamp": datetime.fromtimestamp(point["Timestamp"], timezone.utc),
            "Value": point["Value"],
            "Unit": point["Unit"],
        } for point in batch])
        sent += len(batch)
    return sent
