import json

import click
from click.testing import CliRunner

from panther_journal import cloud
from panther_journal.character_details import pages, private_file
from panther_journal.cli import main


def test_pages_follow_cursor_and_reject_repeated_cursor(monkeypatch):
    responses = iter([{"characters": [1], "cursor": "next"}, {"characters": [2], "cursor": None}])
    calls = []
    monkeypatch.setattr(
        cloud, "api", lambda *args, **kwargs: calls.append(kwargs["params"]) or next(responses)
    )
    assert pages({}, "/characters", {"gameId": "example"}, "characters") == [1, 2]
    assert calls[1] == {"gameId": "example", "cursor": "next"}
    monkeypatch.setattr(
        cloud, "api", lambda *args, **kwargs: {"characters": [], "cursor": "repeat"}
    )
    import pytest

    with pytest.raises(click.ClickException, match="incomplete"):
        pages({}, "/characters", {}, "characters")


def test_private_plan_rejects_repo_and_overwrite(tmp_path):
    import pytest

    path = tmp_path / "plan.json"
    private_file(path, {"private": "synthetic"})
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(click.ClickException):
        private_file(path, {})
    (tmp_path / ".git").mkdir()
    with pytest.raises(click.ClickException, match="checkout"):
        private_file(tmp_path / "another.json", {})


def test_apply_is_durable_and_stops_on_unknown_result(tmp_path, monkeypatch):
    plan, report = tmp_path / "plan.json", tmp_path / "report.jsonl"
    body = {"mode": "migrate", "dryRun": False, "operationId": "a" * 32}
    private_file(plan, {"schemaVersion": 1, "blockers": [], "operations": [body, body]})
    monkeypatch.setattr(cloud, "configuration", lambda: {})
    calls = []

    def failure(*args, **kwargs):
        calls.append(kwargs["json"])
        assert json.loads(report.read_text())["status"] == "pending"
        raise click.ClickException("Unknown request outcome")

    monkeypatch.setattr(cloud, "api", failure)
    result = CliRunner().invoke(
        main, ["character", "apply-details-migration", str(plan), "--report", str(report)]
    )
    assert result.exit_code != 0 and calls == [body]
    assert [json.loads(line)["status"] for line in report.read_text().splitlines()] == [
        "pending",
        "unconfirmed",
    ]
    result = CliRunner().invoke(
        main, ["character", "apply-details-migration", str(plan), "--report", str(report)]
    )
    assert result.exit_code != 0 and calls == [body]


def test_prepare_flags_orphan_profiles_without_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud, "configuration", lambda: {})
    calls = []

    def api(config, method, route, **kwargs):
        calls.append((method, route))
        if route == "/games":
            return {"games": [{"id": "example"}]}
        if route == "/character-details/inventory":
            return {"profiles": [{"characterId": "orphan", "registered": False}], "cursor": None}
        return {"characters": [], "cursor": None}

    monkeypatch.setattr(cloud, "api", api)
    plan = tmp_path / "plan.json"
    result = CliRunner().invoke(
        main, ["character", "prepare-details-migration", "--plan", str(plan)]
    )
    assert result.exit_code == 0, result.output
    assert len(json.loads(plan.read_text())["blockers"]) == 1
    assert all(method == "GET" for method, route in calls)
