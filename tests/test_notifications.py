import importlib
import json
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def notices(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("NOTIFICATIONS_TABLE", "test-notifications")
    monkeypatch.setenv("WORKSHOP_TABLE", "test-workshop")
    monkeypatch.setenv("WORKSHOP_SOURCES", '{"editorial":{}}')
    monkeypatch.setenv("CATALOG_READERS", "example-one,example-two")
    monkeypatch.setenv("MODEL_WORKERS", "example-one")
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "infra/lambda/media-api"))
    with mock_aws():
        for name in ("test-notifications", "test-workshop"):
            boto3.client("dynamodb").create_table(TableName=name, BillingMode="PAY_PER_REQUEST", KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}], AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}])
        sys.modules.pop("notifications", None)
        yield importlib.import_module("notifications")


def event(name="example-one", route="GET /notifications", body=None, **query):
    return {"routeKey": route, "requestContext": {"authorizer": {"jwt": {"claims": {"sub": name + "-sub", "cognito:username": name}}}}, "body": json.dumps(body or {}), "queryStringParameters": query}


def workflow(**changes):
    return {"pk": "GAME#fictional-game", "sk": "editorial~run-one", "gameId": "fictional-game", "kind": "editorial", "id": "editorial~run-one", "status": "failed", "sourceStatus": "FAILED", "title": "A fictional session", "stages": [], **changes}


def ready(m):
    m.db().put_item(Item={"pk": "SYSTEM", "sk": "notifications-v1", "ready": True})


def result(m, request):
    reply = m.handler(request, None)
    assert reply["statusCode"] == 200, reply
    return json.loads(reply["body"])


def test_retained_per_account_read_receipts_and_duplicate_delivery(notices):
    m = notices
    ready(m)
    m.publish(workflow())
    item = result(m, event(view="unread"))["notifications"][0]
    assert item["type"] == "failure" and item["readAt"] is None
    assert "pk" not in item and "example" not in json.dumps(item)
    result(m, event(route="POST /notifications/read", body={"id": item["id"]}))
    m.publish(workflow())
    assert result(m, event(view="unread"))["notifications"] == []
    history = result(m, event())["notifications"]
    assert len(history) == 1 and history[0]["readAt"] > 0
    assert result(m, event(name="example-two", view="unread"))["notifications"][0]["readAt"] is None
    assert m.handler(event(name="stranger"), None)["statusCode"] == 403


def test_bounded_unread_pagination_and_foreign_cursor(notices):
    m = notices
    ready(m)
    for index in range(12):
        m.publish(workflow(id=f"editorial~run-{index}"))
    first = result(m, event(view="unread"))
    assert len(first["notifications"]) == 10 and first["cursor"]
    assert len(result(m, event(view="unread", cursor=first["cursor"]))["notifications"]) == 2
    assert m.handler(event(name="example-two", view="unread", cursor=first["cursor"]), None)["statusCode"] == 400
    assert m.handler(event(route="POST /notifications/read", body={"id": "a" * 64}), None)["statusCode"] == 404
    assert m.handler(event(route="POST /notifications/read", body={"id": first["notifications"][0]["id"], "username": "example-two"}), None)["statusCode"] == 400


def test_review_is_explicit_and_failed_history_survives_recovery(notices):
    m = notices
    assert m.event_for(workflow(status="paused", sourceStatus="UNKNOWN")) is None
    assert m.event_for(workflow(status="done", sourceStatus="NOVEL_READY")) is None
    review = m.event_for(workflow(status="done", sourceStatus="READY_FOR_VIDEO_DISCUSSION"))
    assert review["type"] == "review" and review["target"]["type"] == "workflow"
    m.publish(workflow())
    m.publish(workflow(status="done", sourceStatus="READY_FOR_VIDEO_DISCUSSION"))
    ready(m)
    assert len(result(m, event())["notifications"]) == 2


def test_backfill_requires_complete_source_projection_and_preserves_reads(notices):
    m = notices
    assert m.handler(event(), None)["statusCode"] == 503
    request = event(route="POST /notifications/rebuild")
    assert m.project_handler(request, None)["statusCode"] == 503
    table = boto3.resource("dynamodb").Table("test-workshop")
    table.put_item(Item={"pk": "SYSTEM", "sk": "workshop-v1", "sources": ["editorial"], "hierarchyVersion": 1})
    table.put_item(Item=workflow())
    assert m.project_handler(event(name="example-two", route="POST /notifications/rebuild"), None)["statusCode"] == 403
    assert m.project_handler(request, None)["statusCode"] == 200
    item = result(m, event())["notifications"][0]
    result(m, event(route="POST /notifications/read", body={"id": item["id"]}))
    m.project_handler(request, None)
    assert result(m, event(view="unread"))["notifications"] == []


def test_stream_retries_failed_delivery_and_deduplicates(notices, monkeypatch):
    m = notices
    from boto3.dynamodb.types import TypeSerializer
    record = {"dynamodb": {"SequenceNumber": "1", "NewImage": TypeSerializer().serialize(workflow())["M"]}}
    assert m.project_handler({"Records": [record, record]}, None) == {"batchItemFailures": []}
    monkeypatch.setattr(m, "publish", lambda _: (_ for _ in ()).throw(RuntimeError("Unavailable")))
    assert m.project_handler({"Records": [record]}, None) == {"batchItemFailures": [{"itemIdentifier": "1"}]}
