"""Account-authenticated Panther commands. No AWS credentials are needed."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import time
import uuid
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

import boto3
import click
import keyring
import requests
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

SITE = "https://panther.place"
SERVICE = "panther.place/cli"
ACCOUNT = "session"
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024


def credential_store():
    backend = keyring.get_keyring()
    candidates = getattr(backend, "backends", [backend])
    approved = {
        "keyring.backends.macOS",
        "keyring.backends.Windows",
        "keyring.backends.SecretService",
        "keyring.backends.kwallet",
        "keyring.backends.libsecret",
    }
    for candidate in candidates:
        if type(candidate).__module__ in approved:
            return candidate
    raise click.ClickException(
        "No supported OS credential store. Enable macOS Keychain, Windows Credential Manager, "
        "or Linux Secret Service. Panther will not save tokens in plaintext."
    )


def saved_session():
    try:
        return json.loads(credential_store().get_password(SERVICE, ACCOUNT) or "null")
    except (keyring.errors.KeyringError, ValueError):
        raise click.ClickException("Cannot read Panther credentials. Run panther login again.")


def save_session(session):
    try:
        credential_store().set_password(SERVICE, ACCOUNT, json.dumps(session))
    except keyring.errors.KeyringError:
        raise click.ClickException("Cannot save the session in your OS credential store.")


def configuration():
    try:
        response = requests.get(f"{SITE}/cli-config.json", timeout=20, allow_redirects=False)
        response.raise_for_status()
        config = response.json()
        parsed = urlparse(config["apiUrl"])
        if (
            parsed.scheme != "https"
            or not (parsed.hostname or "").endswith(".execute-api.us-west-2.amazonaws.com")
            or config["region"] != "us-west-2"
            or not config["clientId"]
        ):
            raise ValueError()
        return config
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise click.ClickException(
            "Cannot load Panther's CLI configuration. Check your connection."
        )


def cognito(config):
    return boto3.client(
        "cognito-idp",
        region_name=config["region"],
        config=Config(
            signature_version=UNSIGNED,
            connect_timeout=10,
            read_timeout=20,
            retries={"max_attempts": 1},
        ),
    )


def remember(result, username, config, refresh_token=None):
    session = {
        "username": username,
        "clientId": config["clientId"],
        "idToken": result["IdToken"],
        "refreshToken": result.get("RefreshToken", refresh_token),
        "expiresAt": time.time() + result["ExpiresIn"],
    }
    save_session(session)
    return session


def token(config):
    session = saved_session()
    if not session or session.get("clientId") != config["clientId"]:
        raise click.ClickException("Sign in first: panther login --username other_stu")
    if session["expiresAt"] <= time.time() + 60:
        try:
            result = cognito(config).initiate_auth(
                ClientId=config["clientId"],
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={"REFRESH_TOKEN": session["refreshToken"]},
            )["AuthenticationResult"]
            session = remember(result, session["username"], config, session["refreshToken"])
        except (BotoCoreError, ClientError, KeyError):
            raise click.ClickException("Your session expired. Run panther login again.")
    return session["idToken"]


def api(config, method, route, **kwargs):
    try:
        response = requests.request(
            method,
            config["apiUrl"].rstrip("/") + route,
            headers={"Authorization": f"Bearer {token(config)}"},
            timeout=30,
            allow_redirects=False,
            **kwargs,
        )
        if response.status_code in (401, 403):
            raise click.ClickException("Access denied or session expired. Run panther login again.")
        if response.status_code >= 400:
            try:
                message = response.json().get("error", "Request failed")
            except ValueError:
                message = "Request failed"
            raise click.ClickException(f"Panther: {message}")
        if response.status_code != 200:
            raise click.ClickException("Unexpected Panther response.")
        return response.json()
    except (requests.RequestException, ValueError):
        raise click.ClickException("Could not reach Panther. Check your connection and retry.")


@click.command()
@click.option("--username", prompt=True, help="Your existing Panther username.")
def login(username):
    """Sign in; keep session tokens in the OS credential store, never your password."""
    credential_store()  # Fail before asking for a password if secure storage is unavailable.
    config = configuration()
    password = click.prompt("Password", hide_input=True)
    try:
        client = cognito(config)
        result = client.initiate_auth(
            ClientId=config["clientId"],
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )
        del password
        for _ in range(3):
            challenge = result.get("ChallengeName")
            if not challenge:
                break
            answers = {
                "USERNAME": result.get("ChallengeParameters", {}).get("USER_ID_FOR_SRP", username)
            }
            if challenge == "SOFTWARE_TOKEN_MFA":
                answers["SOFTWARE_TOKEN_MFA_CODE"] = click.prompt(
                    "Authenticator code", hide_input=True
                )
            elif challenge == "NEW_PASSWORD_REQUIRED":
                answers["NEW_PASSWORD"] = click.prompt(
                    "New password", hide_input=True, confirmation_prompt=True
                )
            else:
                raise click.ClickException(
                    "Finish account or MFA setup at https://panther.place, then sign in again."
                )
            result = client.respond_to_auth_challenge(
                ClientId=config["clientId"],
                ChallengeName=challenge,
                Session=result["Session"],
                ChallengeResponses=answers,
            )
        remember(result["AuthenticationResult"], username, config)
    except (BotoCoreError, ClientError, KeyError):
        raise click.ClickException("Sign-in failed. Check your username, password, and MFA code.")
    click.echo(f"Signed in to Panther as {username}.")


@click.command()
def logout():
    """Remove this CLI's saved session and revoke its refresh token."""
    session = saved_session()
    if session:
        try:
            credential_store().delete_password(SERVICE, ACCOUNT)
        except keyring.errors.KeyringError:
            raise click.ClickException("Could not remove the session from your credential store.")
        try:
            config = configuration()
            cognito(config).revoke_token(
                ClientId=session["clientId"], Token=session["refreshToken"]
            )
        except (BotoCoreError, ClientError, click.ClickException):
            click.echo(
                "Saved session removed; remote revocation failed. Tokens may remain valid "
                "until expiry.",
                err=True,
            )
    click.echo("Signed out of the Panther CLI.")


@click.command()
def instructions():
    """Print the bundled agent guide for organization, categories, and metadata."""
    click.echo(files("panther_journal").joinpath("agent-instructions.md").read_text("utf-8"))


def slug(value):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) or len(value) > 96:
        raise click.BadParameter(
            "Use lowercase words separated by hyphens (at most 96 characters)."
        )
    return value


@click.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--game", required=True, help="Stable game ID.")
@click.option(
    "--asset", help="Stable asset ID; generated if omitted. Existing files cannot be replaced."
)
@click.option(
    "--kind", required=True, help="Open-ended kind, e.g. portrait, map, music, video, transcript."
)
@click.option(
    "--metadata",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Structured metadata JSON; see panther instructions.",
)
@click.option(
    "--json", "as_json", is_flag=True, help="Machine-readable result without signed URLs."
)
def upload(file, game, asset, kind, metadata, as_json):
    """Upload one private asset (up to 1 GiB), with checksum verification and no overwrites."""
    game, kind = slug(game), slug(kind)
    asset = slug(asset) if asset else f"asset-{uuid.uuid4().hex}"
    details = {"title": file.stem, "category": "unclassified"}
    if metadata:
        try:
            if metadata.stat().st_size > 16 * 1024:
                raise ValueError()
            provided = json.loads(metadata.read_text("utf-8"))
            if not isinstance(provided, dict):
                raise ValueError()
            details.update(provided)
        except (OSError, ValueError):
            raise click.ClickException("Metadata must be a small UTF-8 JSON object.")
    content_type = {".glb": "model/gltf-binary", ".md": "text/markdown"}.get(
        file.suffix.lower(), mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    )
    config = configuration()
    try:
        with file.open("rb") as source:
            size = source.seek(0, 2)
            if size > MAX_UPLOAD_BYTES:
                raise click.ClickException(
                    "This version supports files up to 1 GiB; no multipart yet."
                )
            source.seek(0)
            digest = hashlib.file_digest(source, "sha256").digest()
            source.seek(0)
            checksum = base64.b64encode(digest).decode("ascii")
            request = api(
                config,
                "POST",
                "/uploads",
                json={
                    "gameId": game,
                    "assetId": asset,
                    "kind": kind,
                    "filename": file.name,
                    "size": size,
                    "contentType": content_type,
                    "sha256": checksum,
                    "metadata": details,
                },
            )
            target = urlparse(request["url"])
            if target.scheme != "https" or not (target.hostname or "").endswith(".amazonaws.com"):
                raise click.ClickException("Panther returned an invalid upload destination.")
            response = requests.put(
                request["url"],
                data=source,
                headers=request["headers"],
                timeout=(15, 300),
                allow_redirects=False,
            )
            if response.status_code in (409, 412):
                raise click.ClickException(
                    "That file already exists or another upload conflicted. "
                    "Nothing was overwritten; choose a new asset ID."
                )
            if response.status_code != 200:
                raise click.ClickException(
                    f"Storage rejected the upload (HTTP {response.status_code}). "
                    "Check the file and retry for a fresh upload link."
                )
    except OSError:
        raise click.ClickException(
            "Cannot read the file or upload it. Check panther info before "
            "retrying: a disconnected upload might have completed."
        )
    result = {
        "key": request["key"],
        "assetId": asset,
        "gameId": game,
        "kind": kind,
        "bytes": size,
        "sha256": checksum,
    }
    click.echo(json.dumps(result) if as_json else f"Uploaded privately: {request['key']}")


@click.command("ls")
@click.argument("prefix", default="games/")
@click.option("--json", "as_json", is_flag=True)
def list_assets(prefix, as_json):
    """List a private folder; use game/asset prefixes to drill down."""
    config = configuration()
    folders, objects, cursor = [], [], None
    while True:
        page = api(config, "GET", "/objects", params={"prefix": prefix, "cursor": cursor})
        folders.extend(page["prefixes"])
        objects.extend(page["objects"])
        cursor = page.get("nextCursor")
        if not cursor:
            break
    if as_json:
        click.echo(json.dumps({"prefix": prefix, "prefixes": folders, "objects": objects}))
    else:
        for folder in folders:
            click.echo(folder)
        for item in objects:
            click.echo(f"{item['size']:>12}  {item['key']}")


@click.command()
@click.argument("key")
def info(key):
    """Show private asset metadata as JSON, without exposing signed URLs."""
    result = api(configuration(), "GET", "/object-url", params={"key": key})
    result.pop("url", None)
    result.pop("expiresIn", None)
    click.echo(json.dumps(result, indent=2))


def register(group):
    for command in (login, logout, upload, list_assets, info, instructions):
        group.add_command(command)
