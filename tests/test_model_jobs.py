import base64
import hashlib
import importlib
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def broker(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("ASSET_BUCKET_NAME", "test-panther-assets")
    monkeypatch.setenv("JOB_TABLE", "test-jobs")
    monkeypatch.setenv("MODEL_PUBLISHERS", "example-operator,example-editor")
    monkeypatch.setenv("MODEL_WORKERS", "example-operator")
    monkeypatch.setenv(
        "STATE_MACHINE_ARN", "arn:aws:states:us-west-2:123456789012:stateMachine:test"
    )
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "infra/lambda/media-api"))
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="test-jobs",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
        )
        s3 = boto3.client("s3")
        s3.create_bucket(
            Bucket="test-panther-assets",
            CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
        )
        for module in ("index", "model_jobs"):
            monkeypatch.delitem(sys.modules, module, raising=False)
        m = importlib.import_module("model_jobs")
        # These test the job broker against a storage facade; indexed byte routing has
        # its own versioned S3 integration tests, independent of the job state machine.
        m.media.s3 = m.media.raw_s3
        yield m


def request(m, route, body=None, username="example-operator", query=None, actor="test-owner"):
    return m.handler(
        {
            "routeKey": route,
            "body": json.dumps(body or {}),
            "queryStringParameters": query,
            "requestContext": {
                "authorizer": {"jwt": {"claims": {"sub": actor, "cognito:username": username}}}
            },
        },
        None,
    )


def unpack(result):
    assert result["statusCode"] == 200, result
    return json.loads(result["body"])


def put(m, key, data=b"image", content_type="image/png"):
    return m.media.s3.put_object(
        Bucket=m.media.BUCKET_NAME,
        Key=key,
        Body=data,
        ContentType=content_type,
        ChecksumAlgorithm="SHA256",
        ChecksumSHA256=base64.b64encode(hashlib.sha256(data).digest()).decode(),
    )


def manifest(m, revision="first"):
    poster = "games/test-game/assets/poster/original/image.png"
    put(m, poster)
    profile = {
        "schemaVersion": 1,
        "gameId": "test-game",
        "id": "test-person",
        "name": "Test Person",
        "model": {"posterKey": poster, "webKey": "old", "sourceKey": "old-source"},
    }
    result = put(
        m,
        "games/test-game/characters/test-person/profile.json",
        json.dumps(profile).encode(),
        "application/json",
    )
    views = {}
    for view in m.VIEWS:
        key = f"games/test-game/assets/turnaround/original/{view}.png"
        put(m, key, view.encode())
        views[view] = key
    return {
        "kind": "character-turnaround",
        "gameId": "test-game",
        "characterId": "test-person",
        "appearanceId": "original",
        "revisionId": revision,
        "views": views,
        "expectedRevision": result["ETag"],
    }


def queued(m):
    body = manifest(m)
    job = unpack(request(m, "POST /model-reference-sets", body))
    m.handler(
        {"operation": "dispatch", "jobId": job["jobId"], "taskToken": "private-callback"}, None
    )
    claimed = unpack(request(m, "POST /model-jobs/claim"))
    return body, claimed


def outputs(m, job):
    import struct

    prefix = f"games/test-game/assets/model-job-{job['jobId'][:32]}-1/original/"
    glb = struct.pack("<4sII", b"glTF", 2, 12)
    result = {
        "passed": True,
        "webKey": prefix + "model.glb",
        "sourceKey": prefix + "model.blend",
        "provenanceKey": prefix + "provenance.json",
        "evidenceKey": prefix + "evidence.json",
    }
    put(m, result["webKey"], glb, "model/gltf-binary")
    put(m, result["sourceKey"], b"editable", "application/octet-stream")
    put(m, result["provenanceKey"], b"{}", "application/json")
    evidence = {
        "jobId": job["jobId"],
        "browserPassed": True,
        "modelSha256": hashlib.sha256(glb).hexdigest(),
        "visualReview": {"passed": True, "assessment": "Synthetic test evidence"},
        "blender": {"freshSourceOpen": True, "freshGlbImport": True, "views": list(m.VIEWS)},
    }
    put(m, result["evidenceKey"], json.dumps(evidence).encode(), "application/json")
    return result


def test_complete_set_is_atomic_idempotent_and_private(broker):
    body = manifest(broker)
    first = unpack(request(broker, "POST /model-reference-sets", body))
    assert first["status"] == "SUBMITTED"
    assert unpack(request(broker, "POST /model-reference-sets", body))["jobId"] == first["jobId"]
    assert broker.table.scan()["Count"] == 2
    assert "taskToken" not in first
    assert (
        request(broker, "POST /model-reference-sets", body, username="visitor")["statusCode"] == 403
    )


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "wrong-game", "alternate", "wrong-kind", "stale-profile"]
)
def test_ineligible_references_do_not_enqueue(broker, change):
    body = manifest(broker)
    if change == "missing":
        del body["views"]["front"]
    elif change == "duplicate":
        body["views"]["front"] = body["views"]["back"]
    elif change == "wrong-game":
        body["views"]["front"] = "games/other/assets/a/original/front.png"
    elif change == "alternate":
        body["appearanceId"] = "stone-skin"
    elif change == "wrong-kind":
        body["kind"] = "portrait"
    else:
        body["expectedRevision"] = '"stale"'
    assert request(broker, "POST /model-reference-sets", body)["statusCode"] in {400, 409}
    assert broker.table.scan()["Count"] == 0


def test_claim_is_exclusive_and_worker_only(broker):
    _, claimed = queued(broker)
    assert claimed["job"]["status"] == "RUNNING"
    assert unpack(request(broker, "POST /model-jobs/claim"))["job"] is None
    assert request(broker, "POST /model-jobs/claim", username="example-editor")["statusCode"] == 403
    assert "taskToken" not in claimed["job"] and "lease" not in claimed["job"]
    payload = {"jobId": claimed["job"]["jobId"], "lease": claimed["lease"]}
    assert (
        request(broker, "POST /model-jobs/heartbeat", payload, actor="different")["statusCode"]
        == 400
    )
    assert unpack(request(broker, "POST /model-jobs/heartbeat", payload))["status"] == "RUNNING"
    assert unpack(request(broker, "POST /model-jobs/defer", payload))["status"] == "QUEUED"
    assert unpack(request(broker, "POST /model-jobs/claim"))["job"] is None


def test_publish_preserves_portrait_and_history_and_retries(broker):
    _, claimed = queued(broker)
    job = claimed["job"]
    result = outputs(broker, job)
    body = {"jobId": job["jobId"], "lease": claimed["lease"], "result": result}
    assert unpack(request(broker, "POST /model-jobs/complete", body))["status"] == "PUBLISHED"
    profile = broker.media._profile_record("test-game", "test-person")[2]
    assert profile["model"]["posterKey"].endswith("poster/original/image.png")
    assert profile["model"]["webKey"] == result["webKey"]
    assert broker.media.s3.head_object(
        Bucket=broker.media.BUCKET_NAME, Key=profile["modelPublication"]["previousProfileKey"]
    )
    assert unpack(request(broker, "POST /model-jobs/complete", body))["status"] == "PUBLISHED"
    assert (
        "publishing"
        not in broker.table.get_item(Key=broker.head_key("test-game", "test-person"))["Item"]
    )


def test_superseded_job_cannot_publish(broker):
    manifest_body, claimed = queued(broker)
    manifest_body["revisionId"] = "new-references"
    unpack(request(broker, "POST /model-reference-sets", manifest_body))
    result = outputs(broker, claimed["job"])
    outcome = unpack(
        request(
            broker,
            "POST /model-jobs/complete",
            {"jobId": claimed["job"]["jobId"], "lease": claimed["lease"], "result": result},
        )
    )
    assert outcome["status"] == "SUPERSEDED"
    assert broker.media._profile_record("test-game", "test-person")[2]["model"]["webKey"] == "old"


def test_false_or_missing_quality_never_publishes(broker):
    _, claimed = queued(broker)
    result = outputs(broker, claimed["job"])
    put(broker, result["evidenceKey"], b"{}", "application/json")
    body = {"jobId": claimed["job"]["jobId"], "lease": claimed["lease"], "result": result}
    assert request(broker, "POST /model-jobs/complete", body)["statusCode"] == 400
    result["passed"] = False
    assert unpack(request(broker, "POST /model-jobs/complete", body))["status"] == "FAILED"
    assert broker.media._profile_record("test-game", "test-person")[2]["model"]["webKey"] == "old"


def test_outbox_starts_once_and_callback_tokens_stay_server_side(broker):
    body = manifest(broker)
    job = unpack(request(broker, "POST /model-reference-sets", body))
    stored = broker.get_job(job["jobId"])
    broker.states = Mock()
    event = {"Records": [{"dynamodb": {"SequenceNumber": "1", "NewImage": broker.wire(stored)}}]}
    assert broker.stream(event, None) == {"batchItemFailures": []}
    assert broker.states.start_execution.call_args.kwargs["name"] == job["jobId"]
    stored.update(status="PUBLISHED", taskToken="secret")
    event["Records"][0]["dynamodb"]["NewImage"] = broker.wire(stored)
    broker.stream(event, None)
    broker.states.send_task_success.assert_called_once()
    assert "secret" not in broker.response(200, broker.public(stored))["body"]


def test_stale_worker_and_changed_profile_cannot_overwrite(broker):
    _, claimed = queued(broker)
    job = claimed["job"]
    result = outputs(broker, job)
    body = {"jobId": job["jobId"], "lease": claimed["lease"], "result": result}
    broker.table.update_item(
        Key=broker.job_key(job["jobId"]),
        UpdateExpression="SET leaseUntil = :zero",
        ExpressionAttributeValues={":zero": 0},
    )
    assert request(broker, "POST /model-jobs/complete", body)["statusCode"] == 409
    new = unpack(request(broker, "POST /model-jobs/claim"))
    assert new["lease"] != claimed["lease"]
    assert request(broker, "POST /model-jobs/complete", body)["statusCode"] == 400
    profile = broker.media._profile_record("test-game", "test-person")[2]
    profile["title"] = "Concurrent change"
    put(
        broker,
        "games/test-game/characters/test-person/profile.json",
        json.dumps(profile).encode(),
        "application/json",
    )
    body["lease"] = new["lease"]
    assert unpack(request(broker, "POST /model-jobs/complete", body))["status"] == "CONFLICT"
    assert (
        broker.media._profile_record("test-game", "test-person")[2]["title"] == "Concurrent change"
    )


def test_reference_advancement_blocks_during_publication_and_recovery_works(broker, monkeypatch):
    body, claimed = queued(broker)
    job = claimed["job"]
    result = outputs(broker, job)
    real_publish = broker.media._publish_model
    monkeypatch.setattr(
        broker.media, "_publish_model", Mock(side_effect=RuntimeError("process stopped"))
    )
    with pytest.raises(RuntimeError):
        request(
            broker,
            "POST /model-jobs/complete",
            {"jobId": job["jobId"], "lease": claimed["lease"], "result": result},
        )
    assert broker.get_job(job["jobId"])["status"] == "PUBLISHING"
    body["revisionId"] = "next"
    assert request(broker, "POST /model-reference-sets", body)["statusCode"] == 409
    broker.table.update_item(
        Key=broker.job_key(job["jobId"]),
        UpdateExpression="SET leaseUntil = :zero",
        ExpressionAttributeValues={":zero": 0},
    )
    recovered = unpack(request(broker, "POST /model-jobs/claim"))
    assert recovered["job"]["status"] == "PUBLISHING"
    monkeypatch.setattr(broker.media, "_publish_model", real_publish)
    outcome = unpack(
        request(
            broker,
            "POST /model-jobs/complete",
            {"jobId": job["jobId"], "lease": recovered["lease"], "result": result},
        )
    )
    assert outcome["status"] == "PUBLISHED"


def test_expiration_preserves_success_and_releases_failed_publication_lock(broker):
    _, claimed = queued(broker)
    job = claimed["job"]
    broker.table.update_item(
        Key=broker.head_key("test-game", "test-person"),
        UpdateExpression="SET publishing = :j",
        ExpressionAttributeValues={":j": job["jobId"]},
    )
    broker.handler({"operation": "expire", "jobId": job["jobId"]}, None)
    assert broker.get_job(job["jobId"])["status"] == "EXPIRED"
    assert (
        "publishing"
        not in broker.table.get_item(Key=broker.head_key("test-game", "test-person"))["Item"]
    )
    broker.table.update_item(
        Key=broker.job_key(job["jobId"]),
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "PUBLISHED"},
    )
    broker.handler({"operation": "expire", "jobId": job["jobId"]}, None)
    assert broker.get_job(job["jobId"])["status"] == "PUBLISHED"
