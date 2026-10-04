from click.testing import CliRunner

from panther_journal import cloud
from panther_journal.cli import main


def test_notification_cli_uses_authenticated_api(monkeypatch):
    calls = []
    monkeypatch.setattr(cloud, "configuration", lambda: {"test": True})

    def api(config, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"notifications": [], "cursor": None}

    monkeypatch.setattr(cloud, "api", api)
    runner = CliRunner()
    for args in (["list", "--unread"], ["read", "example"], ["rebuild"]):
        result = runner.invoke(main, ["notifications", *args])
        assert result.exit_code == 0, result.output
    assert calls == [
        ("GET", "/notifications", {"params": {"view": "unread"}}),
        ("POST", "/notifications/read", {"json": {"id": "example"}}),
        ("POST", "/notifications/rebuild", {"json": {"cursor": None}}),
    ]
