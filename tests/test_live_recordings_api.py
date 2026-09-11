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
    monkeypatch.setenv("LIVE_RECORDING_PUBLISHERS", "example-operator,example-editor")
    monkeypatch.setenv("LIVE_HISTORY_TABLE", "test-history")
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
        boto3.client("dynamodb").create_table(
            TableName="test-history", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName":"feedId","KeyType":"HASH"},{"AttributeName":"partIndex","KeyType":"RANGE"}],
            AttributeDefinitions=[{"AttributeName":"feedId","AttributeType":"S"},{"AttributeName":"partIndex","AttributeType":"N"}],
        )
        monkeypatch.delitem(sys.modules, "live_history", raising=False)
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


def event(body=None, *, game="test-game", actor="owner", username="example-operator"):
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


def history_payload(index):
    return {"schemaVersion":1,"gameId":"test-game","recordingId":"recording-"+"a"*32,
            "previewId":"v1-"+"b"*24,"partIndex":index,"start":index*30,"end":(index+1)*30,
            "sourceSha256":"c"*64,"modelSha256":"d"*64,"recognizerSha256":"e"*64,
            "segments":[{"start":index*30,"end":index*30+2,"text":f"Synthetic chunk {index}"}]}


def history_event(body=None, **query):
    e = event(body)
    e["routeKey"] += "/history"
    e["queryStringParameters"] = {"gameId":"test-game","recordingId":"recording-"+"a"*32,
                                   "previewId":"v1-"+"b"*24,**query}
    return e


def test_full_history_pagination_and_immutable_owner_pins(service):
    parent = payload()
    parent["captureSeconds"] = 1000
    assert service.handle(event(parent),1000)["statusCode"] == 200
    for index in range(31):
        assert service.handle(history_event(history_payload(index)),1000)["statusCode"] == 200
    for query, expected in [({},range(21,31)), ({"position":"beginning"},range(10)),
                            ({"position":"before","cursor":"21"},range(11,21)),
                            ({"position":"after","cursor":"9"},range(10,20))]:
        result = json.loads(service.handle(history_event(**query),1001)["body"])
        assert [c["partIndex"] for c in result["chunks"]] == list(expected)
    assert service.handle(history_event(history_payload(0)),1001)["statusCode"] == 200
    changed = history_payload(0)
    changed["segments"][0]["text"] = "Changed"
    assert service.handle(history_event(changed),1001)["statusCode"] == 409
    other = history_event(history_payload(1))
    other["requestContext"]["authorizer"]["jwt"]["claims"]["sub"] = "other-owner"
    assert service.handle(other,1001)["statusCode"] == 403
    assert service.handle(history_event(gameId="other-game"),1001)["statusCode"] == 404
    assert service.handle(history_event(previewId="different-preview"),1001)["statusCode"] == 409
    assert service.handle(history_event(),1000+service.TTL)["statusCode"] == 404


@pytest.mark.parametrize("change", [
    {"partIndex":-1}, {"sourceSha256":"made-up"}, {"start":float("nan")},
    {"start":2,"end":1}, {"end":100},
    {"segments":[{"start":-1,"end":2,"text":"Invalid"}]},
    {"segments":[{"start":1,"end":2,"text":"Invalid","playerId":"invented"}]},
])
def test_history_rejects_unpinned_or_out_of_bounds_chunks(service, change):
    service.handle(event(payload()),1000)
    with pytest.raises(ValueError):
        service.handle(history_event({**history_payload(0),**change}),1000)


def test_history_does_not_truncate_long_speech_or_refresh_presence(service):
    service.handle(event(payload()),1000)
    value = history_payload(0)
    value["segments"][0]["text"] = "x"*600
    assert service.handle(history_event(value),1060)["statusCode"] == 200
    result = json.loads(service.handle(history_event(),1080)["body"])
    assert len(result["chunks"][0]["segments"][0]["text"]) == 600
    assert json.loads(service.handle(event(),1080)["body"])["recordings"][0]["connectionStale"]


def test_history_filters_expired_rows_before_serving_a_full_page(service):
    import live_history

    parent = payload()
    parent["captureSeconds"] = 1000
    service.handle(event(parent),1000)
    for index in range(15):
        service.handle(history_event(history_payload(index)),1000)
    for index in range(11):
        live_history.history.update_item(Key={"feedId":"test-game#recording-"+"a"*32+"#v1-"+"b"*24,"partIndex":index},
                                         UpdateExpression="SET expiresAt = :t",ExpressionAttributeValues={":t":1001})
    result = json.loads(service.handle(history_event(position="beginning"),1002)["body"])
    assert [c["partIndex"] for c in result["chunks"]] == [11,12,13,14]
