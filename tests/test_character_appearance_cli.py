import json
from unittest.mock import Mock

from click.testing import CliRunner

from panther_journal import cloud
from panther_journal.cli import main


def test_character_appearance_commands_send_exact_guarded_requests(tmp_path, monkeypatch):
    api = Mock(return_value={"record": {"revision": "a" * 32}})
    monkeypatch.setattr(cloud, "configuration", lambda: {})
    monkeypatch.setattr(cloud, "api", api)
    runner = CliRunner()
    body = {
        "operationId": "b" * 32,
        "expectedRevision": "a" * 32,
        "id": "current",
        "gameId": "test-game",
        "characterId": "hero",
    }
    manifest = tmp_path / "selection.json"
    manifest.write_text(json.dumps(body))
    result = runner.invoke(main, ["character", "save-appearance-current", str(manifest)])
    assert result.exit_code == 0, result.output
    assert api.call_args.args == ({}, "POST", "/character-appearance-current")
    assert api.call_args.kwargs["json"] == body
    result = runner.invoke(
        main, ["character", "appearance-current", "--game", "test-game", "--character", "hero"]
    )
    assert result.exit_code == 0
    assert api.call_args.kwargs["params"]["id"] == "current"
    before = api.call_count
    result = runner.invoke(
        main, ["character", "appearance-assets", "--game", "test-game", "--character", "hero"]
    )
    assert result.exit_code != 0 and api.call_count == before


def test_prepare_checks_every_game_and_keeps_private_report_outside_git(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud, "configuration", lambda: {})

    def api(_config, method, endpoint, **kwargs):
        assert method == "GET"
        if endpoint == "/games":
            return {"games": [{"id": "game-one"}, {"id": "game-two"}]}
        if endpoint == "/characters":
            return {"characters": [{"id": "hero"}], "cursor": None}
        if endpoint.endswith("game-inventory"):
            return {
                "characters": ["hero", "orphan"]
                if kwargs["params"]["gameId"] == "game-two"
                else [],
                "cursor": None,
            }
        assert endpoint.endswith("/inventory")
        return {"sourceKeys": []}

    monkeypatch.setattr(cloud, "api", api)
    plan = tmp_path / "plan.json"
    result = CliRunner().invoke(
        main, ["character", "prepare-appearance-migration", "--plan", str(plan)]
    )
    assert result.exit_code == 0, result.output
    document = json.loads(plan.read_text())
    assert len(document["characters"]) == 2 and len(document["blockers"]) == 1
    assert plan.stat().st_mode & 0o777 == 0o600
    assert (
        CliRunner()
        .invoke(main, ["character", "prepare-appearance-migration", "--plan", str(plan)])
        .exit_code
        != 0
    )
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").mkdir()
    result = CliRunner().invoke(
        main, ["character", "prepare-appearance-migration", "--plan", str(checkout / "plan.json")]
    )
    assert result.exit_code != 0 and not (checkout / "plan.json").exists()


def test_legacy_header_with_registered_character_can_be_inventoried(monkeypatch):
    from panther_journal.character_appearances import inventory

    monkeypatch.setattr(cloud, "api", lambda _config, _method, endpoint, **_kwargs: {
        "/games": {"games": [{"id": "fictional-game", "legacy": True}]},
        "/characters": {"characters": [{"id": "hero"}], "cursor": None},
        "/character-appearance-migration/game-inventory": {
            "characters": ["hero"], "cursor": None
        },
    }[endpoint])
    registered, blockers = inventory({})
    assert registered == [{"gameId": "fictional-game", "characterId": "hero"}]
    assert blockers == []


def test_legacy_header_without_roster_still_blocks_appearance_migration(monkeypatch):
    from panther_journal.character_appearances import inventory

    monkeypatch.setattr(cloud, "api", lambda _config, _method, endpoint, **_kwargs: {
        "/games": {"games": [{"id": "fictional-game", "legacy": True}]},
        "/characters": {"characters": [], "cursor": None},
    }[endpoint])
    registered, blockers = inventory({})
    assert registered == []
    assert len(blockers) == 1


def test_apply_rejects_cross_character_plan_before_any_request(tmp_path, monkeypatch):
    api = Mock()
    monkeypatch.setattr(cloud, "api", api)
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "blockers": [],
                "characters": [
                    {
                        "gameId": "test-game",
                        "characterId": "hero",
                        "operationId": "a" * 32,
                        "sources": [{"gameId": "different-game", "characterId": "hero"}],
                    }
                ],
            }
        )
    )
    result = CliRunner().invoke(
        main,
        [
            "character",
            "apply-appearance-migration",
            str(plan),
            "--report",
            str(tmp_path / "report.jsonl"),
        ],
    )
    assert result.exit_code != 0 and "enclosing character" in result.output
    api.assert_not_called()


def test_listing_never_returns_incomplete_repeated_page(monkeypatch):
    monkeypatch.setattr(cloud, "configuration", lambda: {})
    api = Mock(return_value={"records": [{"id": "ordinary"}], "cursor": "repeated"})
    monkeypatch.setattr(cloud, "api", api)
    result = CliRunner().invoke(
        main, ["character", "appearances", "--game", "test-game", "--character", "hero"]
    )
    assert result.exit_code != 0 and "inventory is incomplete" in result.output
    assert api.call_count == 2
