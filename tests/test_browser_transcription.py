import base64
import hashlib
import importlib
import json
import sys
from unittest.mock import Mock

import pytest

from test_model_jobs import broker, request, unpack  # noqa: F401
from test_browser_recording import manifest, wav


@pytest.fixture
def browser(broker, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PLAYBACK_TABLE", broker.table.name)
    monkeypatch.setenv("BROWSER_TRANSCRIPTION_TABLE", "test-job-catalog")
    monkeypatch.setenv("CATALOG_READERS", "example-operator,example-editor,example-member")
    monkeypatch.setenv("OPENAI_TRANSCRIPTION_SECRET_ARN", "configured-secret-reference")
    for name in ("playback_jobs", "browser_transcription"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    return importlib.import_module("browser_transcription")


def sources(m):
    doc = manifest()
    prefix = f"games/test-game/assets/{doc['id']}/original/"

    def put(key, raw, kind, extra):
        metadata = {"sessionId": doc["sessionId"], "extra": extra}
        m.media.s3.put_object(
            Bucket=m.media.BUCKET_NAME,
            Key=key,
            Body=raw,
            ChecksumAlgorithm="SHA256",
            ChecksumSHA256=base64.b64encode(hashlib.sha256(raw).digest()).decode(),
            Metadata={
                "kind": kind,
                "uploaded-by": "test-owner",
                "panther": base64.b64encode(json.dumps(metadata).encode()).decode(),
            },
        )

    part_key = prefix + "part-0000.wav"
    put(
        part_key, wav(), "recording", {"browserPart": {**doc["parts"][0], "recordingId": doc["id"]}}
    )
    raw = json.dumps(doc).encode()
    put(prefix + "recording.json", raw, "recording-manifest", {})
    complete = {
        "gameId": "test-game",
        "recordingKey": prefix + "recording.json",
        "manifestSha256": hashlib.sha256(raw).hexdigest(),
        "status": "COMPLETE",
    }
    live = {"gameId": "test-game", "recordingId": doc["id"], "mode": "live", "inputKey": part_key}
    return complete, live


def message(m, mode):
    pk = "test-game#recording-" + "a" * 32
    job = m.entries(pk, mode)[0]
    return {
        "Records": [{"messageId": "message", "body": json.dumps({"pk": pk, "sk": job["sk"]})}]
    }, job


def test_configuration_and_ownership_fail_closed(browser, monkeypatch):
    complete, live = sources(browser)
    assert (
        request(browser, "GET /browser-recording/capabilities", username="outsider")["statusCode"]
        == 403
    )
    assert (
        request(browser, "POST /browser-transcriptions", live, actor="foreign")["statusCode"] == 400
    )
    assert (
        request(browser, "POST /browser-recording/complete", complete, actor="foreign")[
            "statusCode"
        ]
        == 400
    )
    monkeypatch.setattr(browser, "SECRET", "")
    caps = unpack(
        request(browser, "GET /browser-recording/capabilities", username="example-member")
    )
    assert caps["canRecord"] and not caps["transcriptionAvailable"]
    assert request(browser, "POST /browser-transcriptions", live)["statusCode"] == 503
    assert browser.TABLE.scan()["Count"] == 0
    completed = unpack(
        request(browser, "POST /browser-recording/complete", complete, username="example-member")
    )
    assert completed["workflowVersion"] == 2 and completed["setStatus"] == "COMPLETE"


def test_live_disable_does_not_replace_independent_completed_full_pass(browser):
    complete, live = sources(browser)
    assert unpack(request(browser, "POST /browser-transcriptions", live)) == unpack(
        request(browser, "POST /browser-transcriptions", live)
    )
    final = {
        **{k: live[k] for k in ("gameId", "recordingId")},
        "mode": "final",
        "playbackJobId": "not-complete",
    }
    assert request(browser, "POST /browser-transcriptions", final)["statusCode"] == 400
    completed = unpack(request(browser, "POST /browser-recording/complete", complete))
    final["playbackJobId"] = completed["jobId"]
    first = unpack(request(browser, "POST /browser-transcriptions", final))
    assert first == unpack(request(browser, "POST /browser-transcriptions", final))
    live_jobs = browser.entries("test-game#" + live["recordingId"], "live")
    final_jobs = browser.entries("test-game#" + live["recordingId"], "final")
    assert len(live_jobs) == len(final_jobs) == 1
    assert live_jobs[0]["id"] != final_jobs[0]["id"]
    assert live_jobs[0]["inputs"] == final_jobs[0]["inputs"]
    assert len(browser.input_audio(final_jobs[0])) == len(wav())
    # Old worker protocol cannot consume new WAV capture; version 2 accepts it.
    browser.playback_jobs.handler(
        {"operation": "dispatch", "jobId": completed["jobId"], "taskToken": "test"}, None
    )
    assert (
        unpack(
            request(
                browser.playback_jobs, "POST /recording-playback-jobs/claim", {"workflowVersion": 1}
            )
        )["job"]
        is None
    )
    assert (
        unpack(
            request(
                browser.playback_jobs, "POST /recording-playback-jobs/claim", {"workflowVersion": 2}
            )
        )["job"]["workflowVersion"]
        == 2
    )


def test_redelivery_never_repeats_paid_call_and_retains_response(browser, monkeypatch):
    _, live = sources(browser)
    unpack(request(browser, "POST /browser-transcriptions", live))
    event, job = message(browser, "live")
    provider = Mock(
        return_value={"text": "Synthetic recognized speech", "model": "verified-provider-snapshot"}
    )
    monkeypatch.setattr(browser, "transcribe", provider)
    saved = []

    def publish(*args):
        saved.append(args)
        return "games/test-game/assets/test/original/provider-response.json"

    monkeypatch.setattr(browser, "publish", publish)
    assert browser.work(event, None) == {"batchItemFailures": []}
    assert browser.work(event, None) == {"batchItemFailures": []}
    assert provider.call_count == 1
    assert saved[0][2]["response"]["text"] == "Synthetic recognized speech"
    assert saved[0][2]["sourceKeys"] == [live["inputKey"]]
    assert saved[0][-1]["model"] == "verified-provider-snapshot"
    assert saved[0][-1]["cost"]["status"] == "unknown"
    assert browser.read(job["pk"], job["sk"])["status"] == "DONE"


def test_unknown_provider_outcome_is_not_automatically_retried(browser, monkeypatch):
    _, live = sources(browser)
    unpack(request(browser, "POST /browser-transcriptions", live))
    event, job = message(browser, "live")
    provider = Mock(side_effect=TimeoutError("unknown outcome"))
    monkeypatch.setattr(browser, "transcribe", provider)
    browser.work(event, None)
    browser.work(event, None)
    assert provider.call_count == 1
    assert browser.read(job["pk"], job["sk"])["status"] == "UNKNOWN"


def test_final_aggregation_retry_preserves_done_and_does_not_call_provider(browser, monkeypatch):
    complete, live = sources(browser)
    completed = unpack(request(browser, "POST /browser-recording/complete", complete))
    final = {
        "gameId": live["gameId"],
        "recordingId": live["recordingId"],
        "mode": "final",
        "playbackJobId": completed["jobId"],
    }
    unpack(request(browser, "POST /browser-transcriptions", final))
    event, job = message(browser, "final")
    provider = Mock(return_value={"text": "Full pass text"})
    monkeypatch.setattr(browser, "transcribe", provider)
    monkeypatch.setattr(
        browser, "publish", lambda *args: "games/test-game/assets/test/original/response.json"
    )
    finish = Mock(side_effect=ValueError("temporary aggregation failure"))
    monkeypatch.setattr(browser, "finish", finish)
    assert browser.work(event, None)["batchItemFailures"] == [{"itemIdentifier": "message"}]
    assert browser.read(job["pk"], job["sk"])["status"] == "DONE"
    assert browser.work(event, None)["batchItemFailures"] == [{"itemIdentifier": "message"}]
    assert provider.call_count == 1
    assert browser.read(job["pk"], job["sk"])["status"] == "DONE"


def test_final_transcript_preserves_unassigned_identity_and_exact_inputs(browser, monkeypatch):
    complete, live = sources(browser)
    completed = unpack(request(browser, "POST /browser-recording/complete", complete))
    unpack(
        request(
            browser,
            "POST /browser-transcriptions",
            {
                "gameId": live["gameId"],
                "recordingId": live["recordingId"],
                "mode": "final",
                "playbackJobId": completed["jobId"],
            },
        )
    )
    event, job = message(browser, "final")
    monkeypatch.setattr(browser, "transcribe", lambda audio: {"text": "Fresh full pass"})
    saved = []

    def publish(job, name, doc, kind, sources, generation):
        saved.append((name, doc, kind, sources, generation))
        return f"games/test-game/assets/output/original/{name}"

    monkeypatch.setattr(browser, "publish", publish)
    assert browser.work(event, None) == {"batchItemFailures": []}
    doc = saved[-1][1]
    assert doc["entityType"] == "BrowserTranscript"
    assert doc["players"] == [] and doc["segments"][0]["playerId"] is None
    assert doc["sourceKeys"] == [complete["recordingKey"], live["inputKey"]]
    assert doc["inputArtifacts"]["response-0"]["key"].endswith("provider-response.json")
    assert doc["captureIntegrity"]["warnings"] == manifest()["captureWarnings"]
    assert doc["timestampPrecision"] == "window-boundary"
    assert browser.read(job["pk"], "FINAL-TRANSCRIPT")["key"].endswith("transcript.json")


def test_provider_request_uses_explicit_model_without_context_or_browser_credentials(
    browser, monkeypatch
):
    secret_client = Mock()
    secret_client.get_secret_value.return_value = {"SecretString": "synthetic-provider-key"}
    monkeypatch.setattr(browser.boto3, "client", lambda name: secret_client)
    response = Mock()
    response.read.return_value = b'{"text":"Synthetic response"}'
    opened = Mock()
    opened.__enter__ = Mock(return_value=response)
    opened.__exit__ = Mock(return_value=False)
    transport = Mock(return_value=opened)
    monkeypatch.setattr(browser.urllib.request, "urlopen", transport)
    assert browser.transcribe(wav())["text"] == "Synthetic response"
    req = transport.call_args.args[0]
    assert req.full_url == "https://api.openai.com/v1/audio/transcriptions"
    assert b"\r\ngpt-transcribe\r\n" in req.data
    assert b'name="prompt"' not in req.data
    assert wav() in req.data
