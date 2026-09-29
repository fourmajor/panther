"""First-party remembered sign-in. Never log requests, cookies, or Cognito tokens."""

import base64
import binascii
import json
import os
import re
from http.cookies import SimpleCookie, CookieError
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

CLIENT_ID = os.environ["WEB_CLIENT_ID"]
SITE_ORIGIN = os.environ["SITE_ORIGIN"]
COGNITO_DOMAIN = os.environ["COGNITO_DOMAIN"]
COOKIE = "__Host-panther-refresh"
# Browsers cap persistent cookies; each successful renewal extends the cookie,
# but never extends Cognito's original refresh-token lifetime (3650 days).
COOKIE_DAYS = 400
client = boto3.client(
    "cognito-idp",
    config=Config(
        signature_version=UNSIGNED,
        connect_timeout=2,
        read_timeout=5,
        retries={"total_max_attempts": 1},
    ),
)


def cookie(token=None):
    value = base64.urlsafe_b64encode(token.encode()).decode() if token else ""
    if len(value) > 3600:
        raise ValueError("Refresh credential exceeds cookie budget")
    age = COOKIE_DAYS * 86400 if token else 0
    return f"{COOKIE}={value}; Path=/; Max-Age={age}; Secure; HttpOnly; SameSite=Strict"


def response(status, body, remembered=None):
    result = {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store, private",
            "pragma": "no-cache",
            "vary": "Origin, Cookie",
        },
        "body": json.dumps(body),
    }
    if remembered is not None:
        result["cookies"] = [cookie(remembered)]
    return result


def read_cookie(event):
    raw = "; ".join(event.get("cookies") or [])
    if not raw:
        raw = event.get("headers", {}).get("cookie", "")
    if len(raw) > 16000 or raw.count(f"{COOKIE}=") != 1:
        return None
    try:
        cookies = SimpleCookie(raw)
        value = cookies[COOKIE].value
        if not re.fullmatch(r"[A-Za-z0-9_=-]{1,3600}", value):
            return None
        token = base64.b64decode(value, altchars=b"-_", validate=True).decode()
        return token or None
    except (CookieError, KeyError, ValueError, UnicodeDecodeError, binascii.Error):
        return None


def exchange_code(code, verifier):
    if not isinstance(code, str) or not 1 <= len(code) <= 2048:
        raise ValueError()
    if not isinstance(verifier, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
        raise ValueError()
    request = Request(
        COGNITO_DOMAIN + "/oauth2/token",
        data=urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": SITE_ORIGIN + "/",
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(request, timeout=8) as result:
        return json.loads(result.read(32768))


ACCOUNT_FIELDS = {
    "get": set(),
    "profile": {"name", "picture"},
    "email": {"email"},
    "verify-email": {"code"},
    "resend-email": set(),
    "password": {"previousPassword", "proposedPassword"},
    "mfa-start": set(),
    "mfa-confirm": {"code"},
    "mfa-disable": set(),
    "sign-out-everywhere": set(),
}


def request_body(event):
    raw = event.get("body") or "{}"
    if len(raw) > 8000:
        raise ValueError()
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw, validate=True).decode()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError()
    return value


def text(value, maximum, minimum=1):
    if (
        not isinstance(value, str)
        or not minimum <= len(value) <= maximum
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError()
    return value


def account_operation(body, access):
    action = body.get("action")
    if action not in ACCOUNT_FIELDS or set(body) != ACCOUNT_FIELDS[action] | {"action"}:
        raise ValueError()
    if action == "get":
        user = client.get_user(AccessToken=access)
        attrs = {v["Name"]: v["Value"] for v in user.get("UserAttributes", [])}
        return {
            "username": user["Username"],
            "name": attrs.get("name", ""),
            "picture": attrs.get("picture", ""),
            "email": attrs.get("email", ""),
            "emailVerified": attrs.get("email_verified") == "true",
            "totpEnabled": "SOFTWARE_TOKEN_MFA" in user.get("UserMFASettingList", []),
        }
    if action == "profile":
        name = text(body["name"], 120, 0)
        picture = None if body["picture"] is None else text(body["picture"], 1000, 0)
        if picture and picture not in {
            f"{SITE_ORIGIN}/avatars/{name}.svg" for name in ("panther", "moon", "star")
        }:
            raise ValueError()
        client.update_user_attributes(
            AccessToken=access,
            UserAttributes=[{"Name": "name", "Value": name}]
            + ([{"Name": "picture", "Value": picture}] if picture is not None else []),
        )
    elif action == "email":
        email = text(body["email"], 254)
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError()
        client.update_user_attributes(
            AccessToken=access, UserAttributes=[{"Name": "email", "Value": email}]
        )
    elif action == "verify-email":
        client.verify_user_attribute(
            AccessToken=access, AttributeName="email", Code=text(body["code"], 32)
        )
    elif action == "resend-email":
        client.get_user_attribute_verification_code(AccessToken=access, AttributeName="email")
    elif action == "password":
        client.change_password(
            AccessToken=access,
            PreviousPassword=text(body["previousPassword"], 256),
            ProposedPassword=text(body["proposedPassword"], 256, 16),
        )
    elif action == "mfa-start":
        result = client.associate_software_token(AccessToken=access)
        return {"secretCode": result["SecretCode"]}
    elif action == "mfa-confirm":
        code = text(body["code"], 6, 6)
        if not code.isascii() or not code.isdecimal():
            raise ValueError()
        result = client.verify_software_token(
            AccessToken=access, UserCode=code, FriendlyDeviceName="Panther"
        )
        if result.get("Status") != "SUCCESS":
            return {"verified": False}
        client.set_user_mfa_preference(
            AccessToken=access, SoftwareTokenMfaSettings={"Enabled": True, "PreferredMfa": True}
        )
    elif action == "mfa-disable":
        client.set_user_mfa_preference(
            AccessToken=access, SoftwareTokenMfaSettings={"Enabled": False, "PreferredMfa": False}
        )
    elif action == "sign-out-everywhere":
        client.global_sign_out(AccessToken=access)
        return {"signedOut": True}
    return {"saved": True}


def service_error(error, remembered=None):
    code = error.response.get("Error", {}).get("Code")
    messages = {
        "CodeMismatchException": "The verification code is incorrect. Try again.",
        "ExpiredCodeException": "The verification code expired. Request a new code.",
        "InvalidPasswordException": "Use at least 16 characters, including upper/lowercase, a number and a symbol.",
        "PasswordHistoryPolicyViolationException": "Choose a password you have not used recently.",
        "EnableSoftwareTokenMFAException": "Authenticator verification failed. Start setup again.",
        "SoftwareTokenMFANotFoundException": "Authenticator setup is unavailable. Start setup again.",
        "NotAuthorizedException": "The current password or account credential was not accepted. Sign in again if necessary.",
        "LimitExceededException": "Too many attempts. Wait before trying again.",
        "TooManyRequestsException": "Too many attempts. Wait before trying again.",
        "InvalidParameterException": "The account details could not be accepted. Check your fields.",
    }
    return response(
        400 if code in messages else 503,
        {"error": messages.get(code, "Account service temporarily unavailable. Try again.")},
        remembered=remembered,
    )


def recovery(event):
    try:
        body = request_body(event)
        action = body.get("action")
        fields = {
            "forgot": {"action", "username"},
            "confirm": {"action", "username", "code", "password"},
        }
        if action not in fields or set(body) != fields[action]:
            raise ValueError()
        username = text(body["username"], 128)
        if action == "forgot":
            try:
                client.forgot_password(ClientId=CLIENT_ID, Username=username)
            except ClientError as error:
                if error.response.get("Error", {}).get("Code") not in {
                    "UserNotFoundException",
                    "InvalidParameterException",
                    "NotAuthorizedException",
                }:
                    raise
            return response(
                200, {"sent": True}
            )  # Never disclose account existence or delivery target.
        client.confirm_forgot_password(
            ClientId=CLIENT_ID,
            Username=username,
            ConfirmationCode=text(body["code"], 32),
            Password=text(body["password"], 256, 16),
        )
        return response(200, {"saved": True})
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {
            "UserNotFoundException",
            "NotAuthorizedException",
            "CodeMismatchException",
        }:
            return response(
                400,
                {
                    "error": "The recovery code or account was not accepted. Request a fresh code if needed."
                },
            )
        return service_error(error)
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, binascii.Error):
        return response(400, {"error": "Invalid recovery request"})
    except BotoCoreError:
        return response(503, {"error": "Account service temporarily unavailable. Try again."})


def handler(event, _context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    # Exact Origin + JSON POST + SameSite protect the cookie endpoints from CSRF.
    # Use 400 rather than 403, which static-host CloudFront SPA fallback rewrites.
    if headers.get("origin") != SITE_ORIGIN:
        return response(400, {"error": "Untrusted request origin"})
    if headers.get("content-type", "").split(";")[0].strip() != "application/json":
        return response(400, {"error": "JSON requests are required"})
    route = event.get("routeKey")
    if route not in {
        "POST /auth/session",
        "POST /auth/refresh",
        "POST /auth/logout",
        "POST /auth/account",
        "POST /auth/recovery",
    }:
        return response(400, {"error": "Unknown session operation"})
    if route == "POST /auth/recovery":
        return recovery(event)
    token = read_cookie(event)
    if route == "POST /auth/session":
        try:
            raw = event.get("body") or ""
            if len(raw) > 8000:
                raise ValueError()
            if event.get("isBase64Encoded"):
                raw = base64.b64decode(raw, validate=True).decode()
            body = json.loads(raw)
            if set(body) == {"code", "codeVerifier"}:
                result = exchange_code(body["code"], body["codeVerifier"])
                return response(
                    200,
                    {"id_token": result["id_token"], "expires_in": result["expires_in"]},
                    remembered=result["refresh_token"],
                )
            if set(body) != {"refreshToken"}:
                raise ValueError()
            token = body["refreshToken"]
            if not isinstance(token, str) or not token:
                raise ValueError()
            cookie(token)  # Fail explicitly rather than silently losing a large cookie.
        except (ValueError, KeyError, TypeError, UnicodeDecodeError, binascii.Error):
            return response(400, {"error": "Invalid remembered sign-in request"})
        except HTTPError as error:
            return response(
                401 if error.code == 400 else 503, {"error": "Sign-in could not complete; retry"}
            )
        except (URLError, TimeoutError):
            return response(
                503, {"error": "Sign-in service temporarily unavailable; retry shortly"}
            )
    if not token:
        return response(
            200 if route == "POST /auth/logout" else 401, {"signedOut": True}, remembered=""
        )
    try:
        if route == "POST /auth/logout":
            client.revoke_token(ClientId=CLIENT_ID, Token=token)
            return response(200, {"signedOut": True}, remembered="")
        result = client.get_tokens_from_refresh_token(
            ClientId=CLIENT_ID,
            RefreshToken=token,
        )["AuthenticationResult"]
        if route == "POST /auth/account":
            remembered = result.get("RefreshToken", token)
            try:
                body = account_operation(request_body(event), result["AccessToken"])
                return response(200, body, remembered="" if body.get("signedOut") else remembered)
            except ClientError as error:
                return service_error(error, remembered)
            except BotoCoreError:
                return response(
                    503,
                    {
                        "error": "Account service temporarily unavailable. Reopen settings before retrying."
                    },
                    remembered=remembered,
                )
            except (ValueError, KeyError, TypeError, UnicodeDecodeError, binascii.Error):
                return response(
                    400,
                    {
                        "error": "Invalid account request or outdated sign-in. Sign in again if needed."
                    },
                    remembered=remembered,
                )
        # The long-lived credential is only in Set-Cookie, never JSON. Hourly ID
        # credentials stay in per-tab storage; rotation is persisted atomically
        # with the response by the browser.
        return response(
            200,
            {"id_token": result["IdToken"], "expires_in": result["ExpiresIn"]},
            remembered=result.get("RefreshToken", token),
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {
            "NotAuthorizedException",
            "UserNotFoundException",
            "InvalidParameterException",
        }:
            return response(401, {"error": "Sign in again"}, remembered="")
        # A temporary failure must not destroy the remembered credential. On
        # logout retain it for a revocation retry, while the UI clears access.
        return response(503, {"error": "Sign-in service temporarily unavailable; retry shortly"})
    except (BotoCoreError, KeyError, ValueError):
        return response(503, {"error": "Sign-in service temporarily unavailable; retry shortly"})
