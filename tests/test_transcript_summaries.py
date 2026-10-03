import copy
import importlib
import json
from pathlib import Path
import uuid

import boto3
import pytest

from panther_journal import transcript_summaries as worker
from test_novel_library import library, novel, editorial, broker  # noqa: F401
from test_model_jobs import put
from test_editorial import raw


@pytest.fixture
def summaries(library, monkeypatch):  # noqa: F811
    monkeypatch.setenv("TRANSCRIPT_SUMMARY_TABLE", "test-transcript-summaries")
    monkeypatch.setenv("MODEL_WORKERS", "example-worker")
    boto3.resource("dynamodb").create_table(
        TableName="test-transcript-summaries",
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": n, "AttributeType": t}
            for n, t in (("pk", "S"), ("sk", "S"), ("status", "S"), ("createdAt", "N"))
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "StatusIndex",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "createdAt", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    return importlib.import_module("transcript_summaries")


def call(
    module, route="POST /transcript-summaries", body=None, username="example-operator", **query
):
    return module.handler(
        {
            "routeKey": route,
            "body": json.dumps(body or {}),
            "queryStringParameters": query,
            "requestContext": {
                "authorizer": {"jwt": {"claims": {"sub": username, "cognito:username": username}}}
            },
        },
        None,
    )


def unpack(reply):
    assert reply["statusCode"] == 200, reply
    return json.loads(reply["body"])


def source(summaries):
    key = "games/test-game/assets/source-transcript/original/raw.json"
    document = raw()
    document.update(
        players=[{"id": "person", "name": "Fictional Speaker"}], startedAt="2026-10-02T10:00:00Z"
    )
    put(summaries, key, json.dumps(document).encode(), "application/json")
    return key, document


def summary():
    return {
        "title": "A question for Captain Kade",
        "summary": "The speaker suggests asking Captain Kade and reports having thirteen left.",
        "segmentIndexes": [0],
        "uncertainties": ["The object counted is not specified."],
    }


def complete(summaries, claimed, value=None):
    job = claimed["job"]
    key = f"games/test-game/assets/summary-{job['jobId'][:40]}/original/summary.json"
    document = {
        "schemaVersion": 1,
        "entityType": "TranscriptSummary",
        "gameId": job["gameId"],
        "jobId": job["jobId"],
        "source": job["source"],
        "sourceKeys": [job["key"]],
        "summary": value or summary(),
        "reviewStatus": "ai-reviewed-unverified",
    }
    put(summaries, key, json.dumps(document).encode(), "application/json")
    return call(
        summaries,
        "POST /transcript-summaries/complete",
        {"jobId": job["jobId"], "lease": claimed["lease"], "assetKey": key},
        username="example-worker",
    )


def test_summary_ensure_regenerate_preserves_raw_and_prior_versions(summaries):
    key, original = source(summaries)
    body = {"gameId": "test-game", "key": key}
    assert unpack(call(summaries, "GET /transcript-summaries", **body))["status"] == "MISSING"
    queued = unpack(call(summaries, body=body))
    assert queued["status"] == "QUEUED" and queued["summary"] is None
    assert queued["participants"] == [{"id": "person", "name": "Fictional Speaker"}]
    assert queued["recordedAt"] == original["startedAt"]
    assert unpack(call(summaries, body=body))["jobId"] == queued["jobId"]
    claimed = unpack(call(summaries, "POST /transcript-summaries/claim", username="example-worker"))
    ready = unpack(complete(summaries, claimed))
    assert ready["status"] == "READY" and ready["summary"] == summary()
    again = unpack(call(summaries, body={**body, "operationId": uuid.uuid4().hex}))
    assert again["jobId"] != ready["jobId"] and again["status"] == "QUEUED"
    assert again["summary"] == ready["summary"] and again["assetKey"] == ready["assetKey"]
    assert again["previousSummaryKey"] == ready["assetKey"]
    assert summaries.read(ready["jobId"])["status"] == "READY"
    assert (
        json.loads(
            summaries.media.s3.get_object(Bucket=summaries.media.BUCKET_NAME, Key=key)[
                "Body"
            ].read()
        )
        == original
    )


def test_summary_authorization_source_integrity_and_real_citations(summaries):
    key, original = source(summaries)
    body = {"gameId": "test-game", "key": key}
    assert call(summaries, body=body, username="outsider")["statusCode"] == 403
    assert call(summaries, body={**body, "gameId": "other-game"})["statusCode"] == 400
    unpack(call(summaries, body=body))
    claimed = unpack(call(summaries, "POST /transcript-summaries/claim", username="example-worker"))
    assert complete(summaries, claimed, {**summary(), "segmentIndexes": [999]})["statusCode"] == 400
    put(
        summaries,
        key,
        json.dumps(
            {**original, "segments": [{**original["segments"][0], "text": "Changed source"}]}
        ).encode(),
        "application/json",
    )
    assert complete(summaries, claimed)["statusCode"] == 400
    assert summaries.read(claimed["job"]["jobId"])["status"] == "GENERATING"


def test_summary_worker_independent_review_preserves_evidence(tmp_path, monkeypatch):
    document = raw()
    original = copy.deepcopy(document)
    calls = []

    def download(config, reference, path):
        path.write_text(json.dumps(document))

    def run(command, **kwargs):
        calls.append(command)
        path = Path(command[command.index("--output-last-message") + 1])
        candidate = summary()
        if path.name == "summary-result.json":
            candidate["summary"] = "An unsupported candidate claim."
        path.write_text(json.dumps(candidate))
        return 0

    monkeypatch.setattr(worker.local, "download", download)
    monkeypatch.setattr(worker.local, "codex_base", lambda: ["codex"])
    monkeypatch.setattr(worker.local, "run_process", run)
    job = {
        "source": {
            "key": "games/test-game/assets/raw/original/raw.json",
            "sha256": "actual",
            "size": 100,
        }
    }
    assert worker.summarize({}, job, tmp_path, lambda: None) == summary()
    assert len(calls) == 2 and all("image_generation" in c and "--ephemeral" in c for c in calls)
    assert "unsupported" in json.loads((tmp_path / "summary-result.json").read_text())["summary"]
    assert json.loads((tmp_path / "source.json").read_text()) == original
    assert worker.summarize({}, job, tmp_path, lambda: None) == summary()
    assert len(calls) == 2


def test_summary_rebuild_is_repeatable_private_and_bounded(tmp_path, monkeypatch):
    calls = []

    def api(config, method, route, **kwargs):
        calls.append((method, route, kwargs))
        if route == "/games":
            return {"games": [{"id": "test-game"}, {"id": "other-game"}]}
        if route == "/assets":
            return {
                "assets": [
                    {
                        "kind": "raw-transcript",
                        "key": f"games/{kwargs['params']['gameId']}/assets/raw/original/raw.json",
                    },
                    {"kind": "document", "key": "irrelevant.json"},
                ],
                "cursor": None,
            }
        if route == "/transcript-summaries":
            return {"jobId": "a" * 64, "status": "QUEUED"}
        raise AssertionError(route)

    monkeypatch.setattr(worker.cloud, "configuration", lambda: {})
    monkeypatch.setattr(worker.cloud, "api", api)
    worker.rebuild(tmp_path / "inventory.json", False)
    assert len(json.loads((tmp_path / "inventory.json").read_text())["records"]) == 2
    assert not any(m == "POST" for m, _, _ in calls)
    worker.rebuild(tmp_path / "applied.json", True)
    assert len([c for c in calls if c[0] == "POST"]) == 2
    assert (tmp_path / "applied.json").stat().st_mode & 0o777 == 0o600


def test_summary_worker_discovers_missing_completed_sources_once_per_checkpoint(
    tmp_path, monkeypatch
):
    calls = []

    def api(config, method, route, **kwargs):
        calls.append((method, route))
        if route == "/games":
            return {"games": [{"id": "test-game"}]}
        if route == "/assets":
            return {
                "assets": [
                    {
                        "kind": "raw-transcript",
                        "key": "games/test-game/assets/new/original/raw.json",
                    },
                    {
                        "kind": "raw-transcript",
                        "key": "games/test-game/assets/blocked/original/raw.json",
                    },
                ],
                "cursor": None,
            }
        if route == "/transcript-summaries":
            if method == "GET":
                return {
                    "status": "ATTENTION" if "blocked" in kwargs["params"]["key"] else "MISSING"
                }
            return {"status": "QUEUED"}
        raise AssertionError(route)

    monkeypatch.setattr(worker.cloud, "api", api)
    worker.discover({}, tmp_path)
    assert calls.count(("POST", "/transcript-summaries")) == 1
    count = len(calls)
    worker.discover({}, tmp_path)
    assert len(calls) == count
    assert json.loads((tmp_path / "discovery.json").read_text())["queued"] == 1


def test_summary_worker_rejects_private_work_inside_git(tmp_path, monkeypatch):
    import click

    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(worker.cloud, "configuration", lambda: {})
    with pytest.raises(click.ClickException, match="outside a Git"):
        worker.run_worker(tmp_path / "private-source", True)
    assert not (tmp_path / "private-source").exists()
