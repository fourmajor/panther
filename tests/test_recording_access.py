"""Browser recording is its own capability, separate from catalog reading."""

import importlib
import json
import os
import sys
import time
from pathlib import Path

import boto3
from moto import mock_aws

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "infra/lambda/media-api"))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("ASSET_BUCKET_NAME", "panther-recording-test")
os.environ.setdefault("PLAYBACK_TABLE", "playback")
os.environ.setdefault("BROWSER_TRANSCRIPTION_TABLE", "browser-transcription")


def _event(username, route, body=None):
    return {
        "routeKey": route,
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": f"sub-{username}", "cognito:username": username}}}},
        "body": json.dumps(body or {}),
        "isBase64Encoded": False,
    }


def _load(secret_arn):
    os.environ["CATALOG_READERS"] = "penelope-viewer,example-editor,example-reader"
    os.environ["MODEL_PUBLISHERS"] = "example-editor"
    os.environ["RECORDING_STARTERS"] = "example-editor"
    os.environ["OPENAI_TRANSCRIPTION_SECRET_ARN"] = secret_arn
    os.environ["BROWSER_TRANSCRIPTION_TABLE"] = "browser-transcription"
    module = importlib.import_module("browser_transcription")
    return importlib.reload(module)


def _mint(key, record, opener=None):
    return {
        "clientSecret": "ek_testsecret",
        "expiresAt": int(time.time()) + 60,
        "sessionId": record["operationId"],
        "model": "gpt-live-transcribe",
        "session": {},
    }


START = {
    "gameId": "harbor",
    "recordingId": "recording-" + "a" * 32,
    "operationId": "b" * 32,
}


@mock_aws
def test_viewer_cannot_start_and_an_existing_recorder_can(monkeypatch):
    boto3.resource("dynamodb", region_name="us-west-2").create_table(
        TableName="browser-transcription",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    secret = boto3.client("secretsmanager", region_name="us-west-2").create_secret(
        Name="openai-test", SecretString="sk-testkey"
    )
    transcription = _load(secret["ARN"])
    monkeypatch.setattr("live_transcription.mint", _mint)

    viewer = transcription.handler(_event("penelope-viewer", "POST /browser-recording/live-session", START), None)
    assert viewer["statusCode"] == 403
    assert "Recording access is required" in viewer["body"]

    reader = transcription.handler(_event("example-reader", "POST /browser-recording/live-session", START), None)
    assert reader["statusCode"] == 403

    started = transcription.handler(_event("example-editor", "POST /browser-recording/live-session", START), None)
    assert started["statusCode"] == 200
    assert json.loads(started["body"])["clientSecret"] == "ek_testsecret"

    viewer_caps = json.loads(transcription.handler(_event("penelope-viewer", "GET /browser-recording/capabilities"), None)["body"])
    editor_caps = json.loads(transcription.handler(_event("example-editor", "GET /browser-recording/capabilities"), None)["body"])
    assert viewer_caps["canRecord"] is False
    assert editor_caps["canRecord"] is True

    app = (ROOT / "web/media-explorer/app.js").read_text()
    assert "if(!this.capabilities.canRecord || !this.capabilities.transcriptionAvailable)" in app
    assert "canCreateGame !== true" in app
