import base64
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

import pytest

from test_media_api import load_media_api, response_body
from test_model_jobs import broker, put, request, unpack  # noqa: F401


@pytest.fixture
def library(monkeypatch):
    media, s3 = load_media_api(monkeypatch)
    spec = importlib.util.spec_from_file_location(
        "asset_library_test", Path(__file__).parents[1] / "infra/lambda/media-api/asset_library.py"
    )
    lib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lib)
    old_head = s3.head_object

    def head(**args):
        return {**old_head(**args), "LastModified": datetime(2026, 1, 1, tzinfo=timezone.utc)}

    def listing(Prefix, MaxKeys, ContinuationToken="0", **_kwargs):
        keys = [k for k in sorted(s3.objects) if k.startswith(Prefix)]
        start = int(ContinuationToken)
        page = {"Contents": [{"Key": k} for k in keys[start : start + MaxKeys]]}
        if start + MaxKeys < len(keys):
            page["NextContinuationToken"] = str(start + MaxKeys)
        return page

    s3.head_object = head
    s3.list_objects_v2 = listing
    return lib, media, s3


def test_library_access_uses_private_configuration_not_a_builtin_identity(library, monkeypatch):
    monkeypatch.setenv("MODEL_PUBLISHERS", "custom-account")
    assert call(library, username="custom-account")["statusCode"] == 200
    assert call(library, username="example-operator")["statusCode"] == 403
    monkeypatch.delenv("MODEL_PUBLISHERS")
    assert call(library, username="custom-account")["statusCode"] == 403


def add(s3, name, kind, doc=None, sources=()):
    key = "games/example-game/assets/" + name
    s3.objects[key] = {
        "Body": json.dumps(doc or {}).encode(), "ContentType": "application/json",
        "Metadata": {"kind": kind, "panther": base64.b64encode(json.dumps({
            "sourceKeys": sources, "sessionId": "test-session",
        }).encode()).decode()},
    }
    return key


def call(library, route="/assets", username="example-operator", **query):
    lib, media, _ = library
    return lib.handle({
        "routeKey": "GET " + route,
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "test", "cognito:username": username}}}},
        "queryStringParameters": {"gameId": "example-game", **query},
    }, media)


def test_explicit_recording_raw_corrected_and_stage_links(library):
    _, _, s3 = library
    part = add(s3, "recording-a/original/part-0000.flac", "recording")
    recording = add(s3, "recording-a/original/recording.json", "recording-manifest", {
        "entityType": "Recording", "parts": [{"file": "part-0000.flac"}], "gameId": "example-game",
    })
    header = add(s3, "recording-a/original/capture.json", "recording-manifest", {"id": "recording-a"})
    raw = add(s3, "recording-a/original/raw.json", "raw-transcript", {
        "entityType": "PlayerTranscript", "recordingId": "recording-a", "segments": [],
    })
    corrected = add(s3, "corrected/original/corrected.json", "corrected-transcript", {
        "entityType": "EditorialArtifact", "sourceKeys": [raw], "rawReference": {"key": raw},
        "inputArtifacts": {"recording": {"key": recording}, "foreign": {"key": "games/other/assets/a/a.json"}},
        "payload": {"transcript": {"segments": [{"playerId": "test-player", "text": "Uncertain source"}] }},
    })
    page = response_body(call(library))
    indexed = {a["key"]: a for a in page["assets"]}
    assert indexed[recording]["sourceKeys"] == [part]
    assert indexed[recording]["recording"]["partCount"] == 1
    assert "recording" not in indexed[header]
    assert indexed[raw]["sourceKeys"] == [recording]
    assert indexed[corrected]["sourceKeys"] == sorted([recording, raw])
    assert "document" not in indexed[corrected]
    detail = response_body(call(library, "/asset-document", key=corrected))
    assert detail["document"]["payload"]["transcript"]["segments"][0]["playerId"] == "test-player"
    assert not s3.signed_requests  # Catalog never issues URLs or mutations.


def test_scope_auth_and_cursor(library):
    _, _, s3 = library
    for i in range(30):
        add(s3, f"test-{i}/original/a.json", "document")
    page = response_body(call(library))
    assert len(page["assets"]) == 25 and page["cursor"]
    assert response_body(call(library, cursor=page["cursor"]))["cursor"] is None
    assert call(library, gameId="other-game", cursor=page["cursor"])["statusCode"] == 400
    assert call(library, cursor="broken")["statusCode"] == 400
    assert call(library, username="outsider")["statusCode"] == 403
    assert call(library, username="example-editor")["statusCode"] == 200
    assert call(library, "/asset-document", key="games/other/assets/a/a.json")["statusCode"] == 400
    assert call(library, "/asset-document", key="games/example-game/assets/../a")["statusCode"] == 400


def test_bad_large_and_foreign_documents_do_not_invent_lineage(library):
    _, _, s3 = library
    foreign = add(s3, "a/original/foreign.json", "raw-transcript", {"gameId": "other-game", "sourceKeys": []})
    broken = add(s3, "a/original/broken.json", "document")
    s3.objects[broken]["Body"] = b"not json"
    huge = add(s3, "a/original/huge.json", "document")
    s3.objects[huge]["Body"] = b" " * (2 * 1024**2 + 1)
    for key in (foreign, broken, huge):
        item = response_body(call(library, "/asset-document", key=key))
        assert item["lineageWarning"] and item["document"] is None
        assert item["sourceKeys"] == []


def test_real_handler_routes_and_streaming_storage(broker):  # noqa: F811
    key = "games/test-game/assets/sample/original/raw.json"
    put(broker, key, json.dumps({"entityType": "PlayerTranscript", "gameId": "test-game", "segments": []}).encode(), "application/json")
    page = unpack(request(broker.media, "GET /assets", query={"gameId": "test-game"}))
    assert page["assets"][0]["key"] == key
    detail = unpack(request(broker.media, "GET /asset-document", query={"gameId": "test-game", "key": key}))
    assert detail["document"]["segments"] == []


def test_playback_projection_requires_exact_same_recording_identity(library):
    _, _, s3 = library
    prefix = "games/example-game/assets/recording-a/original/"
    doc = {"entityType": "RecordingPlayback", "schemaVersion": 1, "version": 1,
           "gameId": "example-game", "recordingId": "recording-a",
           "sourceManifestSha256": "a" * 64, "durationSeconds": 60,
           "audioKey": prefix + "playback-v1-" + "a" * 16 + ".mp3",
           "recordingKey": prefix + "recording.json", "sourceKeys": [prefix + "recording.json"]}
    key = add(s3, "recording-a/original/playback-v1-" + "a" * 16 + ".json", "recording-playback-manifest", doc)
    item = response_body(call(library, "/asset-document", key=key))
    assert item["playback"]["audioKey"] == doc["audioKey"]
    assert item["sourceKeys"] == [doc["recordingKey"]]
    for field, bad in [("audioKey", "games/other-game/assets/a/original/a.mp3"),
                       ("recordingId", "other"), ("durationSeconds", -1), ("version", 2)]:
        changed = {**doc, field: bad}
        s3.objects[key]["Body"] = json.dumps(changed).encode()
        item = response_body(call(library, "/asset-document", key=key))
        assert "playback" not in item and item["lineageWarning"]
