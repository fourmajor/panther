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
        connect_timeout=3,
        read_timeout=8,
        retries={"max_attempts": 1},
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


def handler(event, _context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    # Exact Origin + JSON POST + SameSite protect the cookie endpoints from CSRF.
    # Use 400 rather than 403, which static-host CloudFront SPA fallback rewrites.
    if headers.get("origin") != SITE_ORIGIN:
        return response(400, {"error": "Untrusted request origin"})
    if headers.get("content-type", "").split(";")[0].strip() != "application/json":
        return response(400, {"error": "JSON requests are required"})
    route = event.get("routeKey")
    if route not in {"POST /auth/session", "POST /auth/refresh", "POST /auth/logout"}:
        return response(400, {"error": "Unknown session operation"})
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
