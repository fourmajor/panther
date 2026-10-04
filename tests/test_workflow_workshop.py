import importlib
import json
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def workshop(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("WORKSHOP_TABLE", "test-workshop")
    monkeypatch.setenv("CATALOG_READERS", "example-reader,example-worker")
    monkeypatch.setenv("MODEL_WORKERS", "example-worker")
    monkeypatch.setenv("WORKSHOP_PLAN", json.dumps({"correction": ["context", "corrected-transcript"], "novel": ["novel-draft"], "video": ["video-screenplay", "video-preflight"]}))
    monkeypatch.setenv("WORKSHOP_SOURCES", json.dumps({k: {"name": "test-" + k, "arn": "arn:test:" + k} for k in ("editorial", "model", "playback", "transcription")}))
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "infra/lambda/media-api"))
    with mock_aws():
        client = boto3.client("dynamodb")
        for name in ("workshop", "editorial", "model", "playback", "transcription"):
            client.create_table(TableName="test-" + name, BillingMode="PAY_PER_REQUEST", KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}], AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}])
        monkeypatch.delitem(sys.modules, "workflow_workshop", raising=False)
        yield importlib.import_module("workflow_workshop")


def request(m, route="GET /workflows", query=None, body=None, username="example-reader", rebuild=False):
    event = {"routeKey": route, "queryStringParameters": query or {"gameId": "synthetic-game"}, "body": json.dumps(body or {}), "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "synthetic-sub", "cognito:username": username}}}}}
    return (m.project_handler if rebuild else m.handler)(event, None)


def unpack(response):
    assert response["statusCode"] == 200, response
    return json.loads(response["body"])


def ready(m):
    for kind in m.SOURCES:
        cursor = None
        while True:
            result = unpack(request(m, "POST /workflows/rebuild", body={"kind": kind, "cursor": cursor}, username="example-worker", rebuild=True))
            cursor = result["cursor"]
            if not cursor:
                break


def seed(m, kind="editorial", identity="a" * 64, game="synthetic-game"):
    key = {"pk": "RUNS" if kind == "editorial" else "JOBS" if kind == "model" else "SETS", "sk": identity}
    table = m.DB.Table(m.SOURCES[kind]["name"])
    table.put_item(Item={**key, "jobId": identity, "gameId": game, "status": "RUNNING", "createdAt": 12, "leaseUntil": int(time.time()) + 600, "taskToken": "do-not-expose", "lease": "private-lease", "actor": "private-actor", "submittedBy": "private-account", "creation": {"target": "video", "title": "The Lantern Expedition"}})
    return table, key


def test_history_fail_closed_and_readers_cannot_mutate(workshop):
    m = workshop
    assert request(m)["statusCode"] == 503
    assert request(m, username="outsider")["statusCode"] == 403
    assert request(m, "POST /workflow-progress")["statusCode"] == 403
    assert request(m, "POST /workflows/rebuild", rebuild=True)["statusCode"] == 403
    ready(m)
    assert unpack(request(m))["workflows"] == []


def test_editorial_real_stages_no_secrets_no_foreign_game(workshop):
    m = workshop
    table, key = seed(m)
    table.put_item(Item={"pk": "TASKS", "sk": "a" * 64 + ":context", "jobId": "a" * 64, "stage": "context", "status": "DONE", "taskToken": "secret", "output": {"key": "games/synthetic-game/assets/context/original/context.json"}})
    table.put_item(Item={"pk": "TASKS", "sk": "a" * 64 + ":corrected-transcript", "jobId": "a" * 64, "stage": "corrected-transcript", "status": "RUNNING", "leaseUntil": int(time.time()) - 30, "notBefore": 0, "lease": "private"})
    ready(m)
    view = unpack(request(m))["workflows"][0]
    assert view["completedStages"] == 1 and view["totalStages"] == 4
    assert view["activeStages"][0]["leaseUntil"] < time.time()
    assert "stages" not in view
    detail = unpack(request(m, query={"gameId": "synthetic-game", "id": view["id"]}))["workflow"]
    assert detail["stages"][0]["status"] == "done"
    assert detail["stages"][2]["status"] == "pending"
    assert detail["flow"]["mode"] == "branched"
    assert {"from": "corrected-transcript", "to": "video-screenplay"} in detail["flow"]["edges"]
    assert "secret" not in json.dumps(detail) and "private" not in json.dumps(detail)
    assert request(m, query={"gameId": "other-game", "id": view["id"]})["statusCode"] == 404
    # Projection is re-read from current source, not the old stream image.
    table.update_item(Key=key, UpdateExpression="SET #s=:s", ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": "READY_FOR_VIDEO_DISCUSSION"})
    m.project("editorial", key)
    assert unpack(request(m))["workflows"][0]["status"] == "done"


def test_bounded_pagination_and_scoped_cursor(workshop):
    m = workshop
    for n in range(33):
        seed(m, "model", f"{n:064x}")
    seed(m, "model", "f" * 64, "other-game")
    ready(m)
    first = unpack(request(m))
    assert len(first["workflows"]) == 30 and first["cursor"]
    second = unpack(request(m, query={"gameId": "synthetic-game", "cursor": first["cursor"]}))
    assert len(second["workflows"]) == 3 and second["cursor"] is None
    assert request(m, query={"gameId": "other-game", "cursor": first["cursor"]})["statusCode"] == 400


def test_stream_retries_failed_observations(workshop, monkeypatch):
    m = workshop
    _, key = seed(m, "playback")
    record = {"eventSourceARN": "arn:test:playback/stream/example", "dynamodb": {"Keys": {k: {"S": v} for k, v in key.items()}, "SequenceNumber": "42"}}
    assert m.project_handler({"Records": [record]}, None) == {"batchItemFailures": []}
    monkeypatch.setattr(m, "project", Mock(side_effect=RuntimeError("temporary")))
    assert m.project_handler({"Records": [record]}, None) == {"batchItemFailures": [{"itemIdentifier": "42"}]}


def test_transcription_groups_report_windows_not_live_text(workshop):
    m = workshop
    table = m.DB.Table(m.SOURCES["transcription"]["name"])
    pk = "synthetic-game#recording-" + "a" * 32
    table.put_item(Item={"pk": pk, "sk": "FINAL-PLAN", "groupCount": 2, "sessionName": "Test recording"})
    table.put_item(Item={"pk": pk, "sk": "FINAL#a", "mode": "final", "status": "DONE", "start": 0, "createdAt": 10, "text": "Private speech", "actor": "Private user"})
    ready(m)
    view = unpack(request(m))["workflows"][0]
    assert view["completedStages"] == 1 and view["totalStages"] == 3
    assert "Private" not in json.dumps(view)
    table.put_item(Item={"pk": pk, "sk": "FINAL-TRANSCRIPT", "text": "Do not expose"})
    m.project("transcription", {"pk": pk, "sk": "FINAL-TRANSCRIPT"})
    assert unpack(request(m))["workflows"][0]["status"] == "done"


def local_body():
    return {"kind": "video-production", "gameId": "synthetic-game", "runId": "d" * 64, "title": "Lantern scene", "status": "running", "expectedRevision": None, "stages": [{"id": "sound", "label": "Mixing sound", "status": "running"}]}


def test_local_reports_conflict_guard_and_strict_sanitization(workshop):
    m = workshop
    body = local_body()
    first = unpack(request(m, "POST /workflow-progress", body=body, username="example-worker"))["workflow"]
    assert first["reportedAt"] <= time.time()
    assert request(m, "POST /workflow-progress", body=body, username="example-worker")["statusCode"] == 409
    body["expectedRevision"] = first["revision"]
    body["status"] = "done"
    body["stages"][0]["status"] = "done"
    assert unpack(request(m, "POST /workflow-progress", body=body, username="example-worker"))["workflow"]["completedStages"] == 1
    assert request(m, "POST /workflow-progress", body={**body, "taskToken": "secret"}, username="example-worker")["statusCode"] == 400


def test_local_reporter_records_only_real_stage_events(tmp_path, monkeypatch):
    from panther_journal import workflows as w
    monkeypatch.setattr(w.cloud, "configuration", lambda: {})
    sends = []
    def api(_config, _method, _route, **kwargs):
        sends.append(json.loads(json.dumps(kwargs["json"])))
        return {"workflow": {"revision": "new-revision"}}
    monkeypatch.setattr(w.cloud, "api", api)
    report = w.Reporter(tmp_path, "a" * 64, "synthetic-game", "Synthetic", ["inputs", "sound"])
    report.enter()
    report.stage("inputs", "done")
    report.stage("sound", "running")
    report.close("paused")
    assert sends[-1]["status"] == "paused"
    assert sends[-1]["stages"][0]["status"] == "done"
    assert sends[-1]["stages"][1]["status"] == "running"
    assert json.loads((tmp_path / "workshop-progress.json").read_text())["expectedRevision"] == "new-revision"
    assert w.CURRENT.get() is None


def test_flow_preserves_parallel_branches_and_independent_tasks(workshop):
    m = workshop
    stages = [{"id": name, "status": "pending"} for name in ("context", "corrected-transcript", "novel-draft", "novel-proof", "video-screenplay", "video-preflight")]
    graph = m.flow({"kind": "editorial", "stages": stages})
    assert [lane["id"] for lane in graph["lanes"]] == ["shared", "novel", "video"]
    assert {"from": "corrected-transcript", "to": "novel-draft"} in graph["edges"]
    assert {"from": "corrected-transcript", "to": "video-screenplay"} in graph["edges"]
    assert not any(edge["from"].startswith("novel-") and edge["to"].startswith("video-") for edge in graph["edges"])
    assert m.flow({"kind": "video-generation", "stages": stages[:2]})["edges"] == []
    assert m.flow({"kind": "video-production", "stages": stages[:2]})["edges"] == [{"from": "context", "to": "corrected-transcript"}]


def test_hierarchy_exact_totals_status_changes_and_foreign_type_cursor(workshop):
    m = workshop
    for identity, state in [('a' * 64, 'done'), ('b' * 64, 'failed')]:
        body = {'kind': 'session-finalization', 'gameId': 'synthetic-game', 'runId': identity, 'title': 'Fictional run', 'stages': [{'id': 'prepare', 'label': 'Prepare', 'status': state}], 'status': state, 'expectedRevision': None}
        unpack(request(m, 'POST /workflow-progress', body=body, username='example-worker'))
    ready(m)
    assert request(m, query={'gameId': 'synthetic-game', 'view': 'types'})['statusCode'] == 503
    cursor = None
    while True:
        result = unpack(request(m, 'POST /workflows/rebuild', body={'kind': 'hierarchy', 'cursor': cursor}, username='example-worker', rebuild=True))
        cursor = result['cursor']
        if not cursor:
            break
    types = unpack(request(m, query={'gameId': 'synthetic-game', 'view': 'types'}))['types']
    summary = next(t for t in types if t['id'] == 'session-finalization')
    assert summary['total'] == 2 and summary['successful'] == summary['failed'] == 1
    item = m.get(m.INDEX, 'GAME#synthetic-game', 'session-finalization~' + 'b' * 64)
    changed = {k: v for k, v in item.items() if k not in {'pk', 'sk', 'revision'}}
    changed['status'] = 'done'
    m.store(changed, item)
    summary = unpack(request(m, query={'gameId': 'synthetic-game', 'view': 'types'}))['types'][0]
    assert summary['total'] == summary['successful'] == 2 and summary['failed'] == 0
    runs = unpack(request(m, query={'gameId': 'synthetic-game', 'view': 'runs', 'type': 'session-finalization'}))['workflows']
    assert len(runs) == 2
    wrong = m.encode({'pk': 'GAME#synthetic-game', 'sk': 'editorial~other'})
    assert request(m, query={'gameId': 'synthetic-game', 'view': 'runs', 'type': 'session-finalization', 'cursor': wrong})['statusCode'] == 400
    assert unpack(request(m, query={'gameId': 'another-game', 'view': 'types'}))['types'] == []


def test_hierarchy_normalizes_iso_and_decimal_timestamps(workshop):
    from decimal import Decimal
    import workflow_hierarchy

    result = workflow_hierarchy.summary('editorial', [
        {'status': 'done', 'createdAt': '2026-10-03T01:00:00Z',
         'reportedAt': '2026-10-03T02:00:00Z', 'observedAt': 9999999999},
        {'status': 'failed', 'createdAt': Decimal('1'), 'reportedAt': Decimal('2')},
    ])
    assert result['total'] == 2
    assert result['successful'] == result['failed'] == 1
    assert result['latestRunAt'] == 1790989200
    assert result['latestActivityAt'] == 1790992800
