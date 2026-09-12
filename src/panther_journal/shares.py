"""Explicit unlisted shares, managed with Panther login rather than AWS credentials."""

import json
import secrets
from urllib.parse import urlsplit
import click
from panther_journal import cloud


@click.group()
def share():
    """Create or revoke permanent anyone-with-link access to one asset."""


@share.command("create")
@click.argument("key")
@click.option(
    "--preview-key",
    help="Required for video: an uploaded frame derived from this exact video version.",
)
@click.option(
    "--confirm-public",
    is_flag=True,
    required=True,
    help="Anyone with the link may view/download this asset.",
)
def create(key, confirm_public, preview_key):
    if not confirm_public:
        raise click.ClickException("Explicit anyone-with-link approval is required.")
    token = secrets.token_hex(32)
    try:
        result = cloud.api(
            cloud.configuration(),
            "POST",
            "/asset-shares",
            json={"key": key, "token": token, "confirmPublic": True, "previewKey": preview_key},
        )
    except click.ClickException:
        click.echo(
            "Creation outcome uncertain. Keep this URL to revoke a possibly created share: "
            + cloud.SITE
            + "/s/"
            + token,
            err=True,
        )
        raise
    click.echo(json.dumps(result, indent=2))


@share.command("revoke")
@click.argument("url")
def revoke(url):
    result = cloud.api(
        cloud.configuration(), "POST", "/asset-shares/revoke", json={"token": share_token(url)}
    )
    click.echo(json.dumps(result, indent=2))


def share_token(url):
    parsed = urlsplit(url)
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "panther.place"
        or len(parts) not in (2, 3)
        or parts[0] != "s"
    ):
        raise click.ClickException("Supply the Panther sharing URL.")
    return parts[1]


@share.command("set-preview")
@click.argument("url")
@click.argument("preview_key")
def set_preview(url, preview_key):
    """Attach a video-derived frame without changing an existing share URL."""
    result = cloud.api(
        cloud.configuration(),
        "POST",
        "/asset-shares/preview",
        json={"token": share_token(url), "previewKey": preview_key},
    )
    click.echo(json.dumps(result, indent=2))
