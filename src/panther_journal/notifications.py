"""Authenticated persistent workflow notices; no worker execution."""
import json

import click

from panther_journal import cloud


@click.group()
def notifications():
    """Read notifications or backfill existing workflow observations."""


@notifications.command("list")
@click.option("--unread", is_flag=True)
@click.option("--cursor")
def listing(unread, cursor):
    click.echo(json.dumps(cloud.api(cloud.configuration(), "GET", "/notifications", params={"view": "unread" if unread else "all", **({"cursor": cursor} if cursor else {})}), indent=2))


@notifications.command("read")
@click.argument("identity")
def read(identity):
    click.echo(json.dumps(cloud.api(cloud.configuration(), "POST", "/notifications/read", json={"id": identity})))


@notifications.command("rebuild")
def rebuild():
    """Backfill every observed workflow; preserve all notices and read receipts."""
    config, cursor = cloud.configuration(), None
    while True:
        result = cloud.api(config, "POST", "/notifications/rebuild", json={"cursor": cursor})
        click.echo(json.dumps(result))
        cursor = result["cursor"]
        if not cursor:
            break
