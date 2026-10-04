from click.testing import CliRunner
from panther_journal import asset_archive as commands


def test_archive_uses_authenticated_api_with_exact_checksum_and_operation(monkeypatch):
    calls = []
    monkeypatch.setattr(commands, "configuration", lambda: {"apiUrl": "https://example.invalid"})
    monkeypatch.setattr(
        commands,
        "api",
        lambda config, method, route, **kwargs: (
            calls.append((method, route, kwargs["json"])) or {"deleted": True}
        ),
    )
    result = CliRunner().invoke(
        commands.archive,
        [
            "--game",
            "example",
            "--key",
            "games/example/assets/map/original/map.png",
            "--sha256",
            "checksum",
            "--operation-id",
            "a" * 32,
        ],
    )
    assert result.exit_code == 0
    assert calls == [
        (
            "POST",
            "/assets/delete",
            {
                "gameId": "example",
                "key": "games/example/assets/map/original/map.png",
                "sha256": "checksum",
                "operationId": "a" * 32,
            },
        )
    ]


def test_migration_visits_every_authenticated_game_and_activates_separately(monkeypatch):
    calls = []
    monkeypatch.setattr(commands, "configuration", lambda: {})

    def api(config, method, route, **kwargs):
        calls.append((method, route, kwargs.get("json")))
        return (
            {"games": [{"id": "example-a"}, {"id": "example-b"}]}
            if route == "/games"
            else {"references": 2, "status": "verified"}
        )

    monkeypatch.setattr(commands, "api", api)
    result = CliRunner().invoke(commands.archive_migrate, ["--all-games", "--mode", "verify"])
    assert result.exit_code == 0
    assert [call[2]["gameId"] for call in calls[1:]] == ["example-a", "example-b"]
    assert all(call[2]["mode"] == "verify" for call in calls[1:])
    assert (
        CliRunner()
        .invoke(commands.archive_migrate, ["--game", "example-a", "--mode", "activate"])
        .exit_code
        != 0
    )
