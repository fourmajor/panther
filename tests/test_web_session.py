import base64
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError


@pytest.fixture
def session(monkeypatch):
    import boto3

    calls = []

    def refresh(**kwargs):
        calls.append(("refresh", kwargs))
        return {
            "AuthenticationResult": {
                "IdToken": "short-id",
                "ExpiresIn": 3600,
                "RefreshToken": "rotated-secret",
            }
        }

    def revoke(**kwargs):
        calls.append(("revoke", kwargs))

    client = SimpleNamespace(get_tokens_from_refresh_token=refresh, revoke_token=revoke)
    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: client)
    monkeypatch.setenv("WEB_CLIENT_ID", "web-test-client")
    monkeypatch.setenv("SITE_ORIGIN", "https://panther.place")
    monkeypatch.setenv("COGNITO_DOMAIN", "https://test.amazoncognito.com")
    spec = importlib.util.spec_from_file_location(
        "web_session_test", Path(__file__).parents[1] / "infra/lambda/web-session/index.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, client, calls


def event(route="refresh", token="remembered-secret", body=None):
    return {
        "routeKey": "POST /auth/" + route,
        "headers": {"origin": "https://panther.place", "content-type": "application/json"},
        "cookies": []
        if token is None
        else ["__Host-panther-refresh=" + base64.urlsafe_b64encode(token.encode()).decode()],
        "body": json.dumps(body or {}),
    }


def test_refresh_rotates_httponly_cookie_never_returns_long_credential(session):
    module, _, calls = session
    result = module.handler(event(), None)
    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"id_token": "short-id", "expires_in": 3600}
    assert "secret" not in result["body"]
    cookie = result["cookies"][0]
    assert all(
        v in cookie
        for v in [
            "__Host-panther-refresh=",
            "Secure",
            "HttpOnly",
            "SameSite=Strict",
            "Path=/",
            "Max-Age=34560000",
        ]
    )
    assert "Domain=" not in cookie
    assert module.read_cookie({"cookies": [cookie]}) == "rotated-secret"
    assert calls == [
        ("refresh", {"ClientId": "web-test-client", "RefreshToken": "remembered-secret"})
    ]
    assert "no-store" in result["headers"]["cache-control"]


def test_code_exchange_is_server_side_with_fixed_client_redirect_and_pkce(session, monkeypatch):
    module, _, calls = session

    def exchange(request, **kwargs):
        assert request.full_url == "https://test.amazoncognito.com/oauth2/token"
        assert parse_qs(request.data.decode()) == {
            "grant_type": ["authorization_code"],
            "client_id": ["web-test-client"],
            "code": ["code"],
            "code_verifier": ["x" * 43],
            "redirect_uri": ["https://panther.place/"],
        }
        return io.BytesIO(
            json.dumps(
                {"id_token": "short-id", "expires_in": 3600, "refresh_token": "never-in-js"}
            ).encode()
        )

    monkeypatch.setattr(module, "urlopen", exchange)
    result = module.handler(
        event("session", None, {"code": "code", "codeVerifier": "x" * 43}), None
    )
    assert result["statusCode"] == 200
    assert "never-in-js" not in result["body"]
    assert module.read_cookie({"cookies": result["cookies"]}) == "never-in-js"
    assert calls == []


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"origin": "https://evil.example", "content-type": "application/json"},
        {"origin": "https://panther.place", "content-type": "text/plain"},
    ],
)
def test_csrf_rejected_without_cookie_changes_or_cognito_calls(session, headers):
    module, _, calls = session
    request = event()
    request["headers"] = headers
    result = module.handler(request, None)
    assert result["statusCode"] == 400
    assert "cookies" not in result
    assert not calls


@pytest.mark.parametrize(
    "cookies",
    [
        [],
        ["__Host-panther-refresh=bad!"],
        ["__Host-panther-refresh=YQ==", "__Host-panther-refresh=Yg=="],
    ],
)
def test_missing_malformed_duplicate_credentials_fail_closed(session, cookies):
    module, _, calls = session
    request = event()
    request["cookies"] = cookies
    assert module.handler(request, None)["statusCode"] == 401
    assert not calls


def test_logout_revokes_and_expires_cookie(session):
    module, _, calls = session
    result = module.handler(event("logout"), None)
    assert result["statusCode"] == 200
    assert "Max-Age=0" in result["cookies"][0]
    assert calls == [("revoke", {"ClientId": "web-test-client", "Token": "remembered-secret"})]


@pytest.mark.parametrize(
    "code,status,cleared",
    [
        ("NotAuthorizedException", 401, True),
        ("TooManyRequestsException", 503, False),
        ("InternalErrorException", 503, False),
    ],
)
def test_invalid_credentials_clear_but_temporary_errors_preserve_cookie(
    session, code, status, cleared
):
    module, client, _ = session

    def fail(**_kwargs):
        raise ClientError({"Error": {"Code": code, "Message": "do-not-log-secret"}}, "Refresh")

    client.get_tokens_from_refresh_token = fail
    result = module.handler(event(), None)
    assert result["statusCode"] == status
    assert ("cookies" in result) is cleared
    assert "do-not-log-secret" not in json.dumps(result)


def test_failed_logout_retains_cookie_for_retry(session):
    module, client, _ = session

    def fail(**_kwargs):
        raise EndpointConnectionError(endpoint_url="https://test.invalid")

    client.revoke_token = fail
    result = module.handler(event("logout"), None)
    assert result["statusCode"] == 503
    assert "cookies" not in result


def test_migrates_legacy_refresh_and_rejects_malformed_requests(session):
    module, _, calls = session
    result = module.handler(event("session", None, {"refreshToken": "legacy-secret"}), None)
    assert result["statusCode"] == 200
    assert calls[-1][1]["RefreshToken"] == "legacy-secret"
    for body in [
        [],
        None,
        {"refreshToken": "x" * 4000},
        {"code": "code", "codeVerifier": "short"},
        {"refreshToken": 1},
        {"refreshToken": "secret", "clientId": "evil"},
    ]:
        assert module.handler(event("session", None, body), None)["statusCode"] == 400
