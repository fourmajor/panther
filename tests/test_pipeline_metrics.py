"""Workshop run transitions become low-cardinality CloudWatch samples."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "infra/lambda/media-api"))

import pipeline_metrics as metrics  # noqa: E402

NOW = 1_700_000_000


def _names(points):
    return [point["MetricName"] for point in points]


def test_a_new_run_counts_once_and_a_repeat_does_not():
    current = {"kind": "narration", "status": "running", "createdAt": NOW - 100}
    started = metrics.points_for_transition(None, current, NOW)
    assert _names(started) == ["RunsStarted"]
    assert started[0]["Dimensions"] == [{"Name": "Pipeline", "Value": "narration"}]
    assert metrics.points_for_transition({"status": "running"}, {**current, "status": "running"}, NOW) == []


def test_terminal_transitions_emit_status_and_duration_without_ids():
    current = {"kind": "Scene-Render", "status": "done", "createdAt": NOW - 90, "completedAt": NOW - 30}
    done = metrics.points_for_transition({"status": "running"}, current, NOW)
    assert _names(done) == ["RunsSucceeded", "RunDuration"]
    assert done[0]["Dimensions"][0]["Value"] == "scene-render"
    assert done[1]["Value"] == 60_000
    assert done[1]["Unit"] == "Milliseconds"
    failed = metrics.points_for_transition({"status": "running"}, {**current, "kind": "playback", "status": "failed"}, NOW)
    assert _names(failed) == ["RunsFailed", "RunDuration"]
    assert metrics.points_for_transition({"status": "done"}, current, NOW) == []
    blob = str(done)
    assert "session" not in blob and "job" not in blob.lower()


def test_backfill_skips_recent_and_ancient_runs():
    fresh = {"pk": "GAME#example", "kind": "editorial", "status": "done", "createdAt": NOW - 100, "completedAt": NOW - 10}
    assert metrics.points_for_backfill(fresh, NOW) == []
    old = {"pk": "GAME#example", "kind": "model", "status": "done", "createdAt": NOW - 3 * 86400, "completedAt": NOW - 2 * 86400}
    assert _names(metrics.points_for_backfill(old, NOW)) == ["RunsStarted", "RunsSucceeded", "RunDuration"]
    ancient = {"pk": "GAME#example", "kind": "model", "status": "failed", "createdAt": NOW - 40 * 86400, "completedAt": NOW - 39 * 86400}
    assert metrics.points_for_backfill(ancient, NOW) == []
    assert metrics.points_for_backfill({"pk": "TYPES#example", "kind": "model", "status": "done", "createdAt": NOW - 86400}, NOW) == []


class Clock:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, Namespace, MetricData):
        self.calls.append((Namespace, MetricData))


def test_publish_drops_stale_samples_and_keeps_the_namespace():
    client = Clock()
    sent = metrics.publish([
        {"MetricName": "RunsStarted", "Dimensions": [{"Name": "Pipeline", "Value": "model"}], "Timestamp": NOW - 100, "Value": 1, "Unit": "Count"},
        {"MetricName": "RunsStarted", "Dimensions": [{"Name": "Pipeline", "Value": "model"}], "Timestamp": NOW - 20 * 86400, "Value": 1, "Unit": "Count"},
    ], client, NOW)
    assert sent == 1
    assert client.calls[0][0] == "Panther/Pipelines"
    assert client.calls[0][1][0]["Dimensions"] == [{"Name": "Pipeline", "Value": "model"}]
