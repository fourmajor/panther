import importlib
import json
import sys
from pathlib import Path

import boto3
from moto import mock_aws
import pytest


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("LIVE_RECORDINGS_TABLE", "test-live")
    monkeypatch.setenv("LIVE_RECORDING_PUBLISHERS", "stu,other_stu")
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "infra/lambda/media-api"))
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="test-live",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "gameId", "KeyType": "HASH"},
                {"AttributeName": "recordingId", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": k, "AttributeType": "S"} for k in ("gameId", "recordingId")
            ],
        )
        monkeypatch.delitem(sys.modules, "live_recordings", raising=False)
        yield importlib.import_module("live_recordings")


def payload(now=1000):
    return {
        "schemaVersion": 1,
        "gameId": "test-game",
        "sessionId": "test-session",
        "recordingId": "recording-" + "a" * 32,
        "previewId": "v1-" + "b" * 24,
        "observedAt": now * 1000,
        "captureState": "recording",
        "captureSeconds": 30.5,
        "segments": [{"start": 1.1, "end": 2.8, "text": "Synthetic speech"}],
        "previewState": "waiting-for-chunk",
        "omittedChunks": 0,
    }


def event(body=None, *, game="test-game", actor="owner", username="stu"):
    return {
        "routeKey": "POST /recordings/live" if body is not None else "GET /recordings/live",
        "requestContext": {
            "authorizer": {"jwt": {"claims": {"sub": actor, "cognito:username": username}}}
        },
        "queryStringParameters": {"gameId": game},
        "body": json.dumps(body),
    }


def test_authenticated_scoped_preview_freshness_and_expiration(service):
    assert service.handle(event(payload()), 1000)["statusCode"] == 200
    records = json.loads(service.handle(event(), 1001)["body"])["recordings"]
    assert records[0]["segments"][0]["start"] == 1.1
    assert records[0]["reviewStatus"] == "provisional" and not records[0]["connectionStale"]
    assert "owner" not in records[0]
    assert json.loads(service.handle(event(game="other-game"), 1001)["body"])["recordings"] == []
    assert json.loads(service.handle(event(), 1080)["body"])["recordings"][0]["connectionStale"]
    assert json.loads(service.handle(event(), 1000 + service.TTL)["body"])["recordings"] == []
    assert service.handle({"routeKey": "GET /recordings/live"}, 1000)["statusCode"] == 401
    assert service.handle(event(payload(), username="viewer"), 1000)["statusCode"] == 403


def test_old_updates_or_other_publisher_cannot_overwrite(service):
    assert service.handle(event(payload()), 1000)["statusCode"] == 200
    assert service.handle(event(payload()), 1000)["statusCode"] == 409
    assert service.handle(event(payload(1001), actor="another"), 1001)["statusCode"] == 409
    newer = payload(1001)
    newer["captureState"] = "stopped"
    assert service.handle(event(newer), 1001)["statusCode"] == 200
    assert (
        json.loads(service.handle(event(), 1001)["body"])["recordings"][0]["captureState"]
        == "stopped"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("segments", [{"start": 1, "end": 40, "text": "Out of bounds"}]),
        ("segments", [{"start": 1, "end": 2, "text": "Unapproved identity", "playerId": "person"}]),
        ("segments", [{"start": float("nan"), "end": 2, "text": "Bad time"}]),
        ("segments", [{"start": 1, "end": 2, "text": "x" * 501}]),
        ("segments", [{"start": 1, "end": 2, "text": "x", "kind": "invented"}]),
        ("segments", [{"start": 1, "end": 2, "text": "x", "kind": "preview-gap", "approximateTiming": True}]),
        ("observedAt", 1),
        ("captureState", "maybe"),
        ("captureSeconds", -1),
        ("gameId", "../other"),
        ("recordingId", "anything"),
        ("previewState", "final"),
    ],
)
def test_invalid_inputs(service, field, value):
    body = payload()
    body[field] = value
    with pytest.raises(ValueError):
        service.validate(body, 1000)


def test_payload_size_and_invalid_json(service):
    e = event(payload())
    e["body"] = "x" * 50001
    assert service.handle(e, 1000)["statusCode"] == 413
    e["body"] = "not json"
    assert service.handler(e, None)["statusCode"] == 400


def test_gap_notice_preserved_as_notice_not_speech(service):
    body = payload()
    body["segments"] = [{"start": 0, "end": 30, "kind": "preview-gap", "text": "Preview gap"}]
    assert service.handle(event(body), 1000)["statusCode"] == 200
    feed = json.loads(service.handle(event(), 1001)["body"])["recordings"][0]
    assert feed["segments"][0]["kind"] == "preview-gap"
    assert feed["captureState"] == "recording" and not feed["connectionStale"]
