from pathlib import Path

import yaml


def test_playwright_runs_only_on_reviewed_scheduled_or_dispatched_owned_compute():
    workflow = yaml.load(
        (Path(__file__).parents[1] / ".github/workflows/ci.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"workflow_dispatch", "schedule"}
    assert workflow["on"]["schedule"] == [{"cron": "0 12 * * *"}]
    assert workflow["on"]["workflow_dispatch"]["inputs"]["suite"]["default"] == "full"
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    job = workflow["jobs"]["test"]
    assert job["runs-on"] == ["self-hosted", "Linux", "panther-local"]
    assert "github.repository == 'fourmajor/panther'" in job["if"]
    assert "github.event_name == 'workflow_dispatch'" in job["if"]
    assert "github.event_name == 'schedule' && github.ref == 'refs/heads/main'" in job["if"]
    assert "github.actor" not in job["if"]
    assert "github.triggering_actor" not in job["if"]
    assert "refs/heads/main" in job["if"]
    assert "startsWith(github.ref, 'refs/heads/codex/')" in job["if"]
    assert workflow["permissions"] == {"contents": "read"}
    deployed = workflow["jobs"]["deployed-journeys"]
    assert deployed["runs-on"] == job["runs-on"]
    assert deployed["needs"] == "test"
    assert "!cancelled()" in deployed["if"]
    assert "github.repository == 'fourmajor/panther'" in deployed["if"]
    assert "github.event_name == 'schedule' && github.ref == 'refs/heads/main'" in deployed["if"]
    assert "inputs.suite == 'deployed'" in deployed["if"]
    browser_step = next(
        step for step in job["steps"]
        if step.get("name") == "Playwright browser tests (self-hosted)"
    )
    assert browser_step["run"] == "npm run test:browser -- --reporter=line"
    assert browser_step["name"] == "Playwright browser tests (self-hosted)"
    assert browser_step["working-directory"] == "infra"
