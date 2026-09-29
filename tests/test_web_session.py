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


def account_client(session):
    module, client, calls = session
    client.get_tokens_from_refresh_token = lambda **_kwargs: {
        "AuthenticationResult": {
            "AccessToken": "short-private-access",
            "IdToken": "short-id",
            "ExpiresIn": 3600,
            "RefreshToken": "rotated-secret",
        }
    }

    def method(name, result=None):
        def run(**kwargs):
            calls.append((name, kwargs))
            return result or {}

        return run

    client.get_user = method(
        "get",
        {
            "Username": "example-member",
            "UserAttributes": [
                {"Name": "name", "Value": "Example Member"},
                {"Name": "email", "Value": "member@example.invalid"},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "custom:internal", "Value": "not-public"},
            ],
            "UserMFASettingList": ["SOFTWARE_TOKEN_MFA"],
        },
    )
    for name in [
        "update_user_attributes",
        "verify_user_attribute",
        "get_user_attribute_verification_code",
        "change_password",
        "set_user_mfa_preference",
        "global_sign_out",
        "forgot_password",
        "confirm_forgot_password",
    ]:
        setattr(client, name, method(name))
    client.associate_software_token = method("associate", {"SecretCode": "synthetic-setup-key"})
    client.verify_software_token = method("verify", {"Status": "SUCCESS"})
    return module, client, calls


def test_account_uses_cookie_access_and_returns_only_whitelisted_profile(session):
    module, _, calls = account_client(session)
    result = module.handler(event("account", body={"action": "get"}), None)
    assert result["statusCode"] == 200
    profile = json.loads(result["body"])
    assert (
        profile["username"] == "example-member"
        and profile["emailVerified"]
        and profile["totpEnabled"]
    )
    assert "internal" not in result["body"] and "private-access" not in result["body"]
    assert "rotated-secret" in module.read_cookie({"cookies": result["cookies"]})
    assert calls[-1] == ("get", {"AccessToken": "short-private-access"})


@pytest.mark.parametrize(
    "body",
    [
        {"action": "profile", "name": "Example", "picture": "https://evil.example/avatar.svg"},
        {"action": "email", "email": "invalid"},
        {"action": "password", "previousPassword": "x", "proposedPassword": "short"},
        {"action": "mfa-confirm", "code": "12345"},
        {"action": "get", "username": "another-user"},
        {"action": "get", "AccessToken": "injected"},
        {"action": "unknown"},
    ],
)
def test_account_rejects_foreign_targets_invalid_fields_and_preserves_rotated_cookie(session, body):
    module, _, calls = account_client(session)
    result = module.handler(event("account", body=body), None)
    assert result["statusCode"] == 400 and calls == []
    assert module.read_cookie({"cookies": result["cookies"]}) == "rotated-secret"


def test_profile_email_password_and_mfa_operations_never_accept_target_identity(session):
    module, _, calls = account_client(session)
    for body in [
        {
            "action": "profile",
            "name": "Example Member",
            "picture": "https://panther.place/avatars/moon.svg",
        },
        {"action": "email", "email": "member@example.invalid"},
        {"action": "verify-email", "code": "123456"},
        {"action": "resend-email"},
        {
            "action": "password",
            "previousPassword": "Synthetic-old!123",
            "proposedPassword": "Synthetic-new!123",
        },
        {"action": "mfa-confirm", "code": "123456"},
        {"action": "mfa-disable"},
    ]:
        result = module.handler(event("account", body=body), None)
        assert result["statusCode"] == 200 and json.loads(result["body"]) == {"saved": True}
        assert "Password" not in result["body"] and "123456" not in result["body"]
    assert all("Username" not in kwargs for _, kwargs in calls)
    assert calls[-1][1]["SoftwareTokenMfaSettings"] == {"Enabled": False, "PreferredMfa": False}


def test_mfa_setup_and_global_logout_are_explicit_cookie_authenticated_operations(session):
    module, _, _ = account_client(session)
    setup = module.handler(event("account", body={"action": "mfa-start"}), None)
    assert json.loads(setup["body"]) == {"secretCode": "synthetic-setup-key"}
    assert "no-store" in setup["headers"]["cache-control"]
    result = module.handler(event("account", body={"action": "sign-out-everywhere"}), None)
    assert json.loads(result["body"]) == {"signedOut": True}
    assert "Max-Age=0" in result["cookies"][0]
    assert (
        module.handler(event("account", token=None, body={"action": "get"}), None)["statusCode"]
        == 401
    )


def test_account_sdk_errors_are_sanitized_and_cookie_rotation_is_not_lost(session):
    module, client, _ = account_client(session)

    def fail(**_kwargs):
        raise ClientError(
            {"Error": {"Code": "CodeMismatchException", "Message": "private details"}},
            "VerifyUserAttribute",
        )

    client.verify_user_attribute = fail
    result = module.handler(
        event("account", body={"action": "verify-email", "code": "123456"}), None
    )
    assert (
        result["statusCode"] == 400
        and "incorrect" in result["body"]
        and "private details" not in result["body"]
    )
    assert module.read_cookie({"cookies": result["cookies"]}) == "rotated-secret"


def test_account_network_failure_preserves_cookie_already_rotated(session):
    module, client, _ = account_client(session)

    def fail(**_kwargs):
        raise EndpointConnectionError(endpoint_url="https://synthetic.invalid")

    client.get_user = fail
    result = module.handler(event("account", body={"action": "get"}), None)
    assert result["statusCode"] == 503
    assert module.read_cookie({"cookies": result["cookies"]}) == "rotated-secret"


def test_profile_partial_update_preserves_unmodified_existing_avatar(session):
    module, _, calls = account_client(session)
    result = module.handler(
        event("account", body={"action": "profile", "name": "Example", "picture": None}), None
    )
    assert result["statusCode"] == 200
    assert calls[-1][1]["UserAttributes"] == [{"Name": "name", "Value": "Example"}]


def test_recovery_has_origin_guards_generic_existence_response_and_no_credentials_in_outputs(
    session,
):
    module, client, calls = account_client(session)
    body = {"action": "forgot", "username": "example-member"}
    result = module.handler(event("recovery", token=None, body=body), None)
    assert json.loads(result["body"]) == {"sent": True} and "cookies" not in result

    def missing(**_kwargs):
        raise ClientError(
            {"Error": {"Code": "UserNotFoundException", "Message": "account missing"}},
            "ForgotPassword",
        )

    client.forgot_password = missing
    assert module.handler(event("recovery", token=None, body=body), None) == result
    bad = event("recovery", token=None, body=body)
    bad["headers"]["origin"] = "https://evil.example"
    assert module.handler(bad, None)["statusCode"] == 400
    confirm = module.handler(
        event(
            "recovery",
            token=None,
            body={
                "action": "confirm",
                "username": "example-member",
                "code": "123456",
                "password": "Synthetic-new!123",
            },
        ),
        None,
    )
    assert json.loads(confirm["body"]) == {"saved": True}
    assert calls[-1][0] == "confirm_forgot_password"
    assert "123456" not in confirm["body"] and "Synthetic" not in confirm["body"]


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
