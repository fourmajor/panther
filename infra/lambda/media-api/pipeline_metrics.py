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


def _num(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        number = float(value)
        if number > 0 and number == number:
            return number
    return None


def _end(item):
    for field in ("completedAt", "reportedAt", "observedAt", "updatedAt"):
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
    new = current.get("status") or "unknown"
    old = previous.get("status") if isinstance(previous, dict) else None
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
    """Historical samples for a run the new emitter did not see change."""
    if not isinstance(item, dict) or not str(item.get("pk", "")).startswith("GAME#"):
        return []
    now = float(now)
    created = _num(item.get("createdAt"))
    if not created or created < now - MAX_AGE:
        return []
    status = item.get("status") or "unknown"
    activity = _end(item) or created
    if activity > now - RECENT:
        return []
    if status in {"done", "failed"}:
        return points_for_transition(None, item, now)
    return [_point("RunsStarted", _kind(item), created, 1, "Count")]


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
