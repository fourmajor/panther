import base64
import importlib
import json
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
import boto3
import pytest
from click.testing import CliRunner
from test_model_jobs import broker  # noqa: F401

TOKEN = "a" * 64
KEY = "games/test-game/assets/film/original/film.mp4"
PREVIEW = "games/test-game/assets/film-preview/original/frame.jpg"


@pytest.fixture
def shares(broker, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ASSET_SHARES_TABLE", "test-shares")
    monkeypatch.setenv("SITE_ORIGIN", "https://panther.place")
    boto3.client("dynamodb").create_table(
        TableName="test-shares",
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
    )
    monkeypatch.delitem(__import__("sys").modules, "asset_shares", raising=False)
    m = importlib.import_module("asset_shares")
    raw = m.media.raw_s3
    raw.put_bucket_versioning(
        Bucket=m.media.BUCKET_NAME, VersioningConfiguration={"Status": "Enabled"}
    )
    m.media.s3 = Mock(wraps=raw)
    m.media.s3.resolve = lambda key: key
    raw.put_object(
        Bucket=m.media.BUCKET_NAME,
        Key=KEY,
        Body=b"video",
        ContentType="video/mp4",
        Metadata={
            "panther": base64.b64encode(
                json.dumps({"title": "Film <script>attack()</script>"}).encode()
            ).decode()
        },
    )
    return m


def manage(m, route="POST /asset-shares", **data):
    if route == "POST /asset-shares" and "previewKey" not in data:
        version = m.media.raw_s3.head_object(Bucket=m.media.BUCKET_NAME, Key=KEY)["VersionId"]
        m.media.raw_s3.put_object(
            Bucket=m.media.BUCKET_NAME,
            Key=PREVIEW,
            Body=b"frame",
            ContentType="image/jpeg",
            Metadata={
                "panther": base64.b64encode(
                    json.dumps(
                        {"sourceKeys": [KEY], "extra": {"sourceVersionId": version}}
                    ).encode()
                ).decode()
            },
        )
        data["previewKey"] = PREVIEW
    return m.manage(
        {
            "routeKey": route,
            "body": json.dumps({"key": KEY, "token": TOKEN, "confirmPublic": True, **data}),
            "requestContext": {
                "authorizer": {
                    "jwt": {
                        "claims": {"sub": "fictional-id", "cognito:username": "example-operator"}
                    }
                }
            },
        },
        None,
    )


def public(m, suffix="", token=TOKEN):
    return m.public(
        {
            "routeKey": "GET /s/{token}" + suffix,
            "pathParameters": {"token": token},
            "queryStringParameters": {"key": "unrelated-secret"},
        },
        None,
    )


def test_share_pinned_download_revoke(shares):
    m = shares
    assert manage(m)["statusCode"] == 200
    assert manage(m)["statusCode"] == 200
    page = public(m)
    assert page["statusCode"] == 200
    assert "<script>" not in page["body"] and "&lt;script&gt;" in page["body"]
    assert "Download file" in page["body"] and "no-store" in page["headers"]["cache-control"]
    assert 'property="og:video:type" content="video/mp4"' in page["body"]
    assert (
        'property="og:video" content="https://panther.place/s/' + TOKEN + '/watch"' in page["body"]
    )
    assert "X-Amz-" not in page["body"]
    first = public(m, "/download")
    assert first["statusCode"] == 302
    query = parse_qs(urlsplit(first["headers"]["location"]).query)
    assert query["response-content-disposition"][0].startswith("attachment;")
    pinned = query["versionId"]
    m.media.raw_s3.put_object(Bucket=m.media.BUCKET_NAME, Key=KEY, Body=b"new bytes")
    assert (
        parse_qs(urlsplit(public(m, "/watch")["headers"]["location"]).query)["versionId"] == pinned
    )
    item = m.table().scan()["Items"][0]
    assert TOKEN not in json.dumps(item, default=str)
    assert manage(m, "POST /asset-shares/revoke")["statusCode"] == 200
    assert public(m)["statusCode"] == 410 and public(m, "/download")["statusCode"] == 410
    assert manage(m)["statusCode"] == 409


def test_closed_boundaries(shares):
    assert shares.manage({"body": "{}"}, None)["statusCode"] == 403
    assert manage(shares, confirmPublic=False)["statusCode"] == 400
    assert manage(shares, previewKey=None)["statusCode"] == 400
    assert manage(shares, key="games/test-game/characters/hero/profile.json")["statusCode"] == 400
    for token in ["../secret", "b" * 64, "invalid"]:
        assert public(shares, token=token)["statusCode"] == 410
    assert (
        shares.public({"routeKey": "POST /asset-shares", "pathParameters": {"token": TOKEN}}, None)[
            "statusCode"
        ]
        == 410
    )


def test_title_placeholders_are_not_expanded_and_malformed_body_fails(shares):
    shares.media.raw_s3.put_object(
        Bucket=shares.media.BUCKET_NAME,
        Key=KEY,
        Body=b"video",
        ContentType="video/mp4",
        Metadata={
            "panther": base64.b64encode(json.dumps({"title": '{{player}} " & <'}).encode()).decode()
        },
    )
    assert manage(shares)["statusCode"] == 200
    page = public(shares)["body"]
    assert 'content="{{player}} &quot; &amp; &lt;"' in page
    assert page.count("<video ") == 1
    event = {
        "body": "[]",
        "requestContext": {
            "authorizer": {
                "jwt": {"claims": {"sub": "fictional-id", "cognito:username": "example-operator"}}
            }
        },
    }
    assert shares.manage(event, None)["statusCode"] == 400


def test_active_content_attachment_only(shares):
    shares.media.raw_s3.put_object(
        Bucket=shares.media.BUCKET_NAME, Key=KEY, Body=b"<script>", ContentType="text/html"
    )
    assert manage(shares)["statusCode"] == 200
    assert "<video" not in public(shares)["body"]
    query = parse_qs(urlsplit(public(shares, "/watch")["headers"]["location"]).query)
    assert query["response-content-type"] == ["application/octet-stream"]
    assert query["response-content-disposition"][0].startswith("attachment")


def test_cli_explicit_confirmation_and_revoke(monkeypatch):
    from panther_journal import shares as cli

    calls = []
    monkeypatch.setattr(cli.cloud, "configuration", lambda: {})
    monkeypatch.setattr(cli.cloud, "api", lambda *a, **kw: calls.append(kw["json"]) or {"ok": True})
    runner = CliRunner()
    assert runner.invoke(cli.share, ["create", KEY]).exit_code != 0
    assert not calls
    assert runner.invoke(cli.share, ["create", KEY, "--confirm-public"]).exit_code == 0
    assert len(calls[-1]["token"]) == 64
    assert runner.invoke(cli.share, ["revoke", "https://panther.place/s/" + TOKEN]).exit_code == 0
    assert calls[-1] == {"token": TOKEN}
    assert runner.invoke(cli.share, ["revoke", "https://evil.example/s/" + TOKEN]).exit_code != 0
    assert (
        runner.invoke(
            cli.share, ["set-preview", "https://panther.place/s/" + TOKEN, PREVIEW]
        ).exit_code
        == 0
    )
    assert calls[-1] == {"token": TOKEN, "previewKey": PREVIEW}


def test_video_preview_is_pinned_private_and_revocable(shares):
    assert manage(shares)["statusCode"] == 200
    page = public(shares)["body"]
    assert 'poster="/s/' + TOKEN + '/preview"' in page
    assert 'property="og:image" content="https://panther.place/s/' + TOKEN + '/preview"' in page
    assert "share-preview.png" not in page
    first = public(shares, "/preview")
    assert first["statusCode"] == 302
    version = parse_qs(urlsplit(first["headers"]["location"]).query)["versionId"]
    shares.media.raw_s3.put_object(Bucket=shares.media.BUCKET_NAME, Key=PREVIEW, Body=b"new bytes")
    assert (
        parse_qs(urlsplit(public(shares, "/preview")["headers"]["location"]).query)["versionId"]
        == version
    )
    assert manage(shares, "POST /asset-shares/revoke")["statusCode"] == 200
    assert public(shares, "/preview")["statusCode"] == 410


def test_backfill_preserves_link_and_refuses_unrelated_preview(shares):
    assert manage(shares)["statusCode"] == 200
    shares.table().update_item(
        Key={"pk": shares.token_hash(TOKEN)}, UpdateExpression="REMOVE preview"
    )
    assert (
        manage(
            shares,
            "POST /asset-shares/preview",
            previewKey="games/another-game/assets/a/original/b.jpg",
        )["statusCode"]
        == 400
    )
    assert manage(shares, "POST /asset-shares/preview", previewKey=PREVIEW)["statusCode"] == 200
    assert manage(shares, "POST /asset-shares/preview", previewKey=PREVIEW)["statusCode"] == 200
    original = shares.table().get_item(Key={"pk": shares.token_hash(TOKEN)})["Item"]["preview"]
    shares.media.raw_s3.put_object(
        Bucket=shares.media.BUCKET_NAME, Key=PREVIEW, Body=b"bad", ContentType="image/jpeg"
    )
    assert manage(shares, "POST /asset-shares/preview", previewKey=PREVIEW)["statusCode"] == 400
    assert (
        shares.table().get_item(Key={"pk": shares.token_hash(TOKEN)})["Item"]["preview"] == original
    )
