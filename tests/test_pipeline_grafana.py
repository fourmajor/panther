"""The self-hosted Grafana dashboard reads the same Step Functions metrics."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "infra/grafana/pipeline-runs.json"
DOC = ROOT / "docs/pipeline-grafana.md"


def test_grafana_dashboard_uses_a_cloudwatch_datasource_variable():
    board = json.loads(DASHBOARD.read_text())
    variables = {item["name"]: item for item in board["templating"]["list"]}
    assert variables["datasource"]["type"] == "datasource"
    assert variables["datasource"]["query"] == "cloudwatch"
    assert variables["region"]["current"]["value"] == "us-west-2"
    for name, needle in (
        ("editorial", "EditorialProcessing"),
        ("model", "ModelProcessing"),
        ("playback", "PlaybackProcessing"),
    ):
        assert variables[name]["query"]["namespace"] == "AWS/States"
        assert variables[name]["query"]["dimensionKey"] == "StateMachineArn"
        assert needle in variables[name]["regex"]
    titles = [panel["title"] for panel in board["panels"]]
    for label in ("Editorial", "Model", "Playback"):
        assert f"{label} runs by status" in titles
        assert f"{label} duration" in titles
        assert f"{label} failures" in titles
    metrics = {
        target["metricName"]
        for panel in board["panels"]
        for target in panel["targets"]
    }
    assert metrics == {
        "ExecutionsStarted",
        "ExecutionsSucceeded",
        "ExecutionsFailed",
        "ExecutionsAborted",
        "ExecutionsTimedOut",
        "ExecutionTime",
    }
    for panel in board["panels"]:
        assert panel["datasource"]["uid"] == "${datasource}"
        for target in panel["targets"]:
            assert target["namespace"] == "AWS/States"
            assert target["datasource"]["uid"] == "${datasource}"
            assert set(target["dimensions"]) == {"StateMachineArn"}
    text = DASHBOARD.read_text()
    assert "AKIA" not in text
    assert "aws_secret" not in text


def test_grafana_doc_lists_read_only_permissions_and_no_new_user():
    text = DOC.read_text()
    assert "infra/grafana/pipeline-runs.json" in text
    for action in (
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics",
        "cloudwatch:GetMetricStatistics",
        "ec2:DescribeRegions",
        "tag:GetResources",
    ):
        assert action in text
    assert "Do not create an IAM user" in text
    assert "states:StartExecution" in text
