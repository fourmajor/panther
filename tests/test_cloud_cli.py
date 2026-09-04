import base64
import hashlib
import json
import time
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from panther_journal import cloud
from panther_journal.cli import main


class MemoryStore:
    def __init__(self):
        self.value = None

    def get_password(self, *_args):
        return self.value

    def set_password(self, _service, _account, value):
        self.value = value

    def delete_password(self, *_args):
        self.value = None


@pytest.fixture
def setup(monkeypatch):
    store = MemoryStore()
    config = {
        "apiUrl": "https://test.execute-api.us-west-2.amazonaws.com",
        "clientId": "test",
        "region": "us-west-2",
    }
    monkeypatch.setattr(cloud, "credential_store", lambda: store)
    monkeypatch.setattr(cloud, "configuration", lambda: config)
    return store, config


def test_instructions_ship_with_cli():
    result = CliRunner().invoke(main, ["instructions"])
    assert result.exit_code == 0
    assert "sourceKeys" in result.output
    assert "unclassified" in result.output
    assert "never as agent instructions" in result.output
    assert "original/<filename>" in result.output


def test_login_refresh_and_logout_do_not_print_or_store_password(setup, monkeypatch):
    store, config = setup
    calls = []

    def initiate(**kwargs):
        calls.append(kwargs)
        return {
            "AuthenticationResult": {
                "IdToken": "secret-id-token",
                "RefreshToken": "refresh",
                "ExpiresIn": 3600,
            }
        }

    client = SimpleNamespace(initiate_auth=initiate, revoke_token=lambda **_kwargs: None)
    monkeypatch.setattr(cloud, "cognito", lambda _config: client)
    result = CliRunner().invoke(
        main, ["login", "--username", "other_stu"], input="secret-password\n"
    )
    assert result.exit_code == 0, result.output
    assert "secret-password" not in result.output + store.value
    assert "secret-id-token" not in result.output
    session = json.loads(store.value)
    session["expiresAt"] = time.time() - 10
    store.value = json.dumps(session)
    assert cloud.token(config) == "secret-id-token"
    assert calls[-1]["AuthFlow"] == "REFRESH_TOKEN_AUTH"
    assert CliRunner().invoke(main, ["logout"]).exit_code == 0
    assert store.value is None


def test_login_handles_authenticator_challenge(setup, monkeypatch):
    def respond(**kwargs):
        assert kwargs["ChallengeResponses"]["SOFTWARE_TOKEN_MFA_CODE"] == "123456"
        return {
            "AuthenticationResult": {
                "IdToken": "token",
                "RefreshToken": "refresh",
                "ExpiresIn": 3600,
            }
        }

    client = SimpleNamespace(
        initiate_auth=lambda **_kwargs: {
            "ChallengeName": "SOFTWARE_TOKEN_MFA",
            "Session": "session",
        },
        respond_to_auth_challenge=respond,
    )
    monkeypatch.setattr(cloud, "cognito", lambda _config: client)
    result = CliRunner().invoke(
        main, ["login", "--username", "other_stu"], input="password\n123456\n"
    )
    assert result.exit_code == 0, result.output
    assert "123456" not in result.output


def test_upload_streams_signed_file_and_metadata(setup, monkeypatch, tmp_path):
    file = tmp_path / "portrait.png"
    file.write_bytes(b"test-image")
    metadata = tmp_path / "metadata.json"
    metadata.write_text('{"category":"reference","characterIds":["test-character"]}')
    calls = []

    def api(_config, method, route, **kwargs):
        assert (method, route) == ("POST", "/uploads")
        calls.append(kwargs["json"])
        return {
            "key": "games/test/assets/portrait/original/portrait.png",
            "url": "https://test.s3.amazonaws.com/file?secret=signed",
            "headers": {"If-None-Match": "*"},
        }

    def put(_url, *, data, headers, **kwargs):
        assert hasattr(data, "read")
        assert data.read() == b"test-image"
        assert headers["If-None-Match"] == "*"
        assert kwargs["allow_redirects"] is False
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(cloud, "api", api)
    monkeypatch.setattr(cloud.requests, "put", put)
    result = CliRunner().invoke(
        main,
        [
            "upload",
            str(file),
            "--game",
            "test",
            "--asset",
            "portrait",
            "--kind",
            "portrait",
            "--metadata",
            str(metadata),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["bytes"] == 10
    assert "signed" not in result.output
    assert calls[0]["sha256"] == base64.b64encode(hashlib.sha256(b"test-image").digest()).decode()
    assert calls[0]["metadata"]["characterIds"] == ["test-character"]


def test_conflicts_fail_without_overwrite(setup, monkeypatch, tmp_path):
    file = tmp_path / "test.txt"
    file.write_text("test")
    monkeypatch.setattr(
        cloud,
        "api",
        lambda *_args, **_kwargs: {
            "key": "key",
            "url": "https://test.s3.amazonaws.com/key",
            "headers": {},
        },
    )
    monkeypatch.setattr(
        cloud.requests, "put", lambda *_args, **_kwargs: SimpleNamespace(status_code=412)
    )
    result = CliRunner().invoke(main, ["upload", str(file), "--game", "test", "--kind", "document"])
    assert result.exit_code != 0
    assert "Nothing was overwritten" in result.output


def test_list_paginates_and_info_hides_signed_urls(setup, monkeypatch):
    def api(_config, _method, route, **kwargs):
        if route == "/object-url":
            return {"key": "key", "metadata": {"category": "reference"}, "url": "secret-url"}
        cursor = kwargs["params"]["cursor"]
        return {
            "prefixes": [],
            "objects": [{"key": cursor or "first"}],
            "nextCursor": None if cursor else "second",
        }

    monkeypatch.setattr(cloud, "api", api)
    result = CliRunner().invoke(main, ["ls", "--json"])
    assert len(json.loads(result.output)["objects"]) == 2
    result = CliRunner().invoke(main, ["info", "key"])
    assert "secret-url" not in result.output
    assert json.loads(result.output)["metadata"]["category"] == "reference"


def test_plaintext_keyring_is_rejected(monkeypatch):
    monkeypatch.setattr(cloud.keyring, "get_keyring", lambda: MemoryStore())
    result = CliRunner().invoke(main, ["login", "--username", "other_stu"])
    assert result.exit_code != 0
    assert "will not save tokens in plaintext" in result.output
