"""The Grafana dashboard reads workshop pipeline metrics, not Step Functions executions."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "infra/grafana/pipeline-runs.json"
DOC = ROOT / "docs/pipeline-grafana.md"


def test_grafana_dashboard_uses_workshop_metrics():
    board = json.loads(DASHBOARD.read_text())
    variables = {item["name"]: item for item in board["templating"]["list"]}
    assert variables["datasource"]["type"] == "datasource"
    assert variables["datasource"]["query"] == "cloudwatch"
    assert variables["region"]["current"]["value"] == "us-west-2"
    assert "editorial" not in variables
    assert board["time"]["from"] == "now-30d"
    titles = [panel["title"] for panel in board["panels"]]
    assert "Runs by status" in titles
    assert "Failures" in titles
    assert "Duration" in titles
    assert any(title.startswith("Runs started, last 24") for title in titles)
    assert any(title.startswith("Runs failed, last 7") for title in titles)
    targets = [target for panel in board["panels"] for target in panel["targets"]]
    search = [target for target in targets if str(target.get("expression", "")).startswith("SEARCH(")]
    assert len(search) == 12
    for target in search:
        assert target["metricQueryType"] == 0
        assert target["metricEditorMode"] == 1
        assert target["queryMode"] == "Metrics"
        assert target["period"] == "3600"
        assert target["statistic"]
    expressions = [target.get("expression", "") for target in search]
    blob = "\n".join(expressions)
    assert "Panther/Pipelines" in blob
    for name in ("RunsStarted", "RunsSucceeded", "RunsFailed", "RunDuration"):
        assert name in blob
    assert "AWS/States" not in blob
    assert "StateMachineArn" not in blob
    assert "AKIA" not in DASHBOARD.read_text()


def test_grafana_doc_lists_read_only_permissions_and_no_new_user():
    text = DOC.read_text()
    assert "infra/grafana/pipeline-runs.json" in text
    assert "Panther/Pipelines" in text
    for action in (
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics",
        "cloudwatch:GetMetricStatistics",
        "ec2:DescribeRegions",
        "tag:GetResources",
        "logs:DescribeLogGroups",
    ):
        assert action in text
    assert "GetLogEvents" not in text
    assert "Do not create another" in text
    assert "panther-grafana-readonly" in text
    assert "do not print the secret value" in text
    assert "states:StartExecution" in text
