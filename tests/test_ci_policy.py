from pathlib import Path

import yaml


def test_playwright_runs_only_in_manually_dispatched_self_hosted_job():
    workflow = yaml.load(
        (Path(__file__).parents[1] / ".github/workflows/ci.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"workflow_dispatch"}
    job = workflow["jobs"]["test"]
    assert job["runs-on"] == ["self-hosted", "Linux", "panther-local"]
    assert "github.repository == 'fourmajor/panther'" in job["if"]
    assert "github.actor == 'fourmajor'" in job["if"]
    assert "github.triggering_actor == 'fourmajor'" in job["if"]
    assert "refs/heads/main" in job["if"]
    assert "startsWith(github.ref, 'refs/heads/codex/')" in job["if"]
    assert workflow["permissions"] == {"contents": "read"}
    browser_step = next(step for step in job["steps"] if step.get("run") == "npm run test:browser")
    assert browser_step["name"] == "Playwright browser tests (self-hosted)"
    assert browser_step["working-directory"] == "infra"
