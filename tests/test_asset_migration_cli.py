import json

from click.testing import CliRunner
import click

from panther_journal.cli import main
from panther_journal import cloud


def test_migration_defaults_to_dry_run_and_keeps_create_only_reports(tmp_path, monkeypatch):
    entry = {"key": "games/test/assets/a/original/a.png", "expectedVersionId": "one"}
    plan, report = tmp_path / "plan.json", tmp_path / "report.jsonl"
    plan.write_text(json.dumps({"schemaVersion": 1, "migrations": [entry]}))
    calls = []
    monkeypatch.setattr(cloud, "configuration", lambda: {})
    monkeypatch.setattr(cloud, "api", lambda *args, **kwargs: calls.append(kwargs["json"]) or {"status": "ready"})
    runner = CliRunner()
    assert runner.invoke(main, ["assets", "migrate", str(plan), "--report", str(report)]).exit_code == 0
    assert calls == [{**entry, "dryRun": True}]
    assert json.loads(report.read_text())["request"] == entry
    assert report.stat().st_mode & 0o777 == 0o600
    assert runner.invoke(main, ["assets", "migrate", str(plan), "--apply", "--report", str(report)]).exit_code != 0
    assert len(calls) == 1


def test_batch_stops_on_conflict_without_rewriting_expected_version(tmp_path, monkeypatch):
    entries = [{"key": f"games/test/assets/a/original/{i}.png", "expectedVersionId": "pinned"} for i in range(2)]
    plan, report = tmp_path / "plan.json", tmp_path / "report.jsonl"
    plan.write_text(json.dumps({"schemaVersion": 1, "migrations": entries}))
    calls = []
    monkeypatch.setattr(cloud, "configuration", lambda: {})

    def conflict(*args, **kwargs):
        calls.append(kwargs["json"])
        raise click.ClickException("Asset changed")

    monkeypatch.setattr(cloud, "api", conflict)
    result = CliRunner().invoke(main, ["assets", "migrate", str(plan), "--apply", "--report", str(report)])
    assert result.exit_code != 0 and len(calls) == 1
    assert calls[0]["expectedVersionId"] == "pinned" and calls[0]["dryRun"] is False
    assert json.loads(report.read_text())["status"] == "interrupted-inspect-before-retry"
