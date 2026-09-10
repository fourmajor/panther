import base64
import hashlib
import importlib
import json
import sys
from unittest.mock import Mock

from boto3.dynamodb.types import TypeSerializer
import pytest

from test_model_jobs import broker, put, request, unpack  # noqa: F401


@pytest.fixture
def playback(broker, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PLAYBACK_TABLE", broker.table.name)
    monkeypatch.delitem(sys.modules, "playback_jobs", raising=False)
    return importlib.import_module("playback_jobs")


def complete_manifest(m):
    prefix = "games/test-game/assets/recording-" + "a" * 32 + "/original/"
    parts = []
    for i in range(2):
        body = f"synthetic part {i}".encode()
        name = f"part-{i:04d}.flac"
        put(m, prefix + name, body, "audio/flac")
        parts.append({"file": name, "start": float(i), "duration": 1.0,
                      "size": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                      "sampleRate": 48000, "channels": 1, "bitsPerSample": 16})
    doc = {"entityType": "Recording", "schemaVersion": 1, "id": "recording-" + "a" * 32,
           "gameId": "test-game", "sessionId": "test-session", "status": "complete",
           "sourceFormat": "flac", "parts": parts}
    raw = json.dumps(doc).encode()
    put(m, prefix + "recording.json", raw, "application/json")
    return {"gameId": "test-game", "recordingKey": prefix + "recording.json",
            "manifestSha256": hashlib.sha256(raw).hexdigest(), "status": "COMPLETE"}, doc


def event(item, old=None):
    wire = TypeSerializer()
    return {"Records": [{"dynamodb": {"SequenceNumber": "1",
        "NewImage": {k: wire.serialize(v) for k, v in item.items()},
        "OldImage": {k: wire.serialize(v) for k, v in (old or {}).items()}}}]}


def test_only_explicit_complete_set_starts_exactly_named_workflow(playback, monkeypatch):
    m = playback
    body, _ = complete_manifest(m)
    assert m.table.scan()["Count"] == 0  # Chunk uploads and even manifest upload do not trigger.
    assert request(m, "POST /recording-sets/complete", {**body, "status": "UPLOADING"})["statusCode"] == 400
    job = unpack(request(m, "POST /recording-sets/complete", body, username="other_stu"))
    assert job["entityType"] == "RecordingChunkSet" and job["setStatus"] == "COMPLETE"
    assert len(job["chunks"]) == 2 and job["status"] == "SUBMITTED"
    assert unpack(request(m, "POST /recording-sets/complete", body)) == job
    assert m.table.scan()["Count"] == 1
    states = Mock()
    monkeypatch.setattr(m, "states", states)
    assert m.stream(event(m.read(job["jobId"])), None) == {"batchItemFailures": []}
    assert states.start_execution.call_args.kwargs["name"] == job["jobId"]
    assert unpack(request(m, "POST /recording-playback-jobs/claim", {"workflowVersion": 1}))["job"] is None
    assert m.stream(event({**m.read(job["jobId"]), "setStatus": "UPLOADING"}), None) == {"batchItemFailures": []}
    assert states.start_execution.call_count == 1


def test_missing_changed_foreign_or_inconsistent_chunks_never_commit(playback):
    m = playback
    body, doc = complete_manifest(m)
    assert request(m, "POST /recording-sets/complete", {**body, "gameId": "foreign"})["statusCode"] == 400
    assert request(m, "POST /recording-sets/complete", {**body, "manifestSha256": "b" * 64})["statusCode"] == 400
    source = body["recordingKey"].replace("recording.json", "part-0001.flac")
    m.media.s3.delete_object(Bucket=m.media.BUCKET_NAME, Key=source)
    assert request(m, "POST /recording-sets/complete", body)["statusCode"] == 503
    put(m, source, b"changed", "audio/flac")
    assert request(m, "POST /recording-sets/complete", body)["statusCode"] == 400
    assert m.table.scan()["Count"] == 0
    body, doc = complete_manifest(m)
    doc["parts"][1]["file"] = "part-0000.flac"
    raw = json.dumps(doc).encode()
    put(m, body["recordingKey"], raw, "application/json")
    body["manifestSha256"] = hashlib.sha256(raw).hexdigest()
    assert request(m, "POST /recording-sets/complete", body)["statusCode"] == 400


def queued(m):
    body, _ = complete_manifest(m)
    job = unpack(request(m, "POST /recording-sets/complete", body))
    dispatch = {"operation": "dispatch", "jobId": job["jobId"], "taskToken": "private-token"}
    m.handler(dispatch, None)
    m.handler(dispatch, None)  # duplicate callback dispatch is safe
    return job


def test_owner_lease_excludes_dm_other_worker_and_expired_attempts(playback, monkeypatch):
    m = playback
    job = queued(m)
    assert request(m, "GET /recording-playback-jobs", username="outsider")["statusCode"] == 403
    assert request(m, "POST /recording-playback-jobs/claim", {"workflowVersion": 1}, username="other_stu")["statusCode"] == 403
    claim = unpack(request(m, "POST /recording-playback-jobs/claim", {"workflowVersion": 1}))
    body = {"jobId": job["jobId"], "lease": claim["lease"]}
    assert "taskToken" not in claim["job"] and "leaseActor" not in claim["job"]
    assert unpack(request(m, "POST /recording-playback-jobs/claim", {"workflowVersion": 1}))["job"] is None
    assert request(m, "POST /recording-playback-jobs/heartbeat", body, actor="other-owner")["statusCode"] == 400
    assert unpack(request(m, "POST /recording-playback-jobs/heartbeat", body))["status"] == "RUNNING"
    now = m.time.time()
    monkeypatch.setattr(m.time, "time", lambda: now + 601)
    assert request(m, "POST /recording-playback-jobs/complete", body)["statusCode"] == 400
    new = unpack(request(m, "POST /recording-playback-jobs/claim", {"workflowVersion": 1}))
    assert new["lease"] != body["lease"] and new["job"]["attempts"] == 2
    assert request(m, "POST /recording-playback-jobs/heartbeat", body)["statusCode"] == 400


def test_verified_output_finishes_via_durable_callback(playback, monkeypatch):
    m = playback
    job = queued(m)
    claimed = unpack(request(m, "POST /recording-playback-jobs/claim", {"workflowVersion": 1}))
    body = {"jobId": job["jobId"], "lease": claimed["lease"]}
    source_sha = base64.b64decode(job["recording"]["sha256"]).hex()
    stem = job["recording"]["key"].replace("recording.json", "playback-v1-" + source_sha[:16])
    audio = b"synthetic encoded audio"
    put(m, stem + ".mp3", audio, "audio/mpeg")
    doc = {"entityType": "RecordingPlayback", "version": 1, "gameId": job["gameId"],
        "recordingId": job["chunkSetId"], "recordingKey": job["recording"]["key"],
        "sourceManifestSha256": source_sha, "audioKey": stem + ".mp3", "size": len(audio),
        "audioSha256": hashlib.sha256(audio).hexdigest(),
        "sourceKeys": [job["recording"]["key"], *[r["key"] for r in job["chunks"]]]}
    put(m, stem + ".json", json.dumps({**doc, "sourceKeys": []}).encode(), "application/json")
    assert request(m, "POST /recording-playback-jobs/complete", body)["statusCode"] == 400
    put(m, stem + ".json", json.dumps(doc).encode(), "application/json")
    old = m.read(job["jobId"])
    result = unpack(request(m, "POST /recording-playback-jobs/complete", body))
    assert result["status"] == "DONE" and result["output"]["audio"]["key"] == stem + ".mp3"
    assert unpack(request(m, "POST /recording-playback-jobs/complete", body)) == result
    states = Mock()
    monkeypatch.setattr(m, "states", states)
    assert m.stream(event(m.read(job["jobId"]), old), None) == {"batchItemFailures": []}
    states.send_task_success.assert_called_once_with(taskToken="private-token", output='{"status": "DONE"}')


def test_failed_delivery_is_retried_and_terminal_jobs_do_not_run(playback, monkeypatch):
    m = playback
    job = queued(m)
    states = Mock()
    states.start_execution.side_effect = RuntimeError("temporary failure")
    monkeypatch.setattr(m, "states", states)
    assert m.stream(event({**m.read(job["jobId"]), "status": "SUBMITTED"}), None)["batchItemFailures"]
    m.handler({"operation": "fail", "jobId": job["jobId"]}, None)
    assert unpack(request(m, "POST /recording-playback-jobs/claim", {"workflowVersion": 1}))["job"] is None


def test_job_listing_paginates_and_hides_leases(playback):
    m = playback
    job = queued(m)
    for i in range(28):
        jid = hashlib.sha256(str(i).encode()).hexdigest()
        m.table.put_item(Item={**m.read(job["jobId"]), **m.key(jid), "jobId": jid})
    page = unpack(request(m, "GET /recording-playback-jobs"))
    assert len(page["jobs"]) == 25 and page["cursor"]
    assert all("taskToken" not in j for j in page["jobs"])
    assert len(unpack(request(m, "GET /recording-playback-jobs", query={"cursor": page["cursor"]}))["jobs"]) == 4
