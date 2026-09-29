import importlib
import json
import re
from types import SimpleNamespace
import uuid

import pytest

from test_browse_index import index  # noqa: F401


@pytest.fixture
def selections(index, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MODEL_PUBLISHERS", "example-owner")
    module = importlib.import_module("transcript_selection")
    monkeypatch.setattr(module, "browse_index", index)
    lib = importlib.import_module("asset_library")
    key = "games/example/assets/raw-a/original/raw.json"
    asset = {"key": key, "name": "raw.json", "kind": "raw-transcript", "contentType": "application/json",
             "size": 100, "lastModified": "2026-01-01", "sourceKeys": [],
             "metadata": {"sessionId": "session-a", "extra": {"version": {"schemaVersion": 1, "seriesId": "raw-a", "number": 1}}},
             "transcript": lib.transcript_summary({"entityType": "PlayerTranscript", "segments": [{"playerId": None}]})}
    monkeypatch.setattr(lib, "describe", lambda *_: asset)
    index.refresh(None, key)
    media = SimpleNamespace(_query=lambda e, k: (e.get("queryStringParameters") or {}).get(k),
        _valid_slug=lambda s: isinstance(s, str) and bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", s)),
        _valid_key=lambda s: isinstance(s, str) and s.startswith("games/") and ".." not in s,
        _response=lambda status, body: {"statusCode": status, "body": body})
    return module, index, media, asset


def call(selections, body=None, username="example-owner", **query):
    module, _, media, _ = selections
    return module.handle({"routeKey": "POST /transcript-selection" if body else "GET /transcript-selection",
        "body": json.dumps(body) if body else None,
        "queryStringParameters": {"gameId": "example", "sessionId": "session-a", **query},
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "fictional-account", "cognito:username": username}}}}}, media)


def request(selections, **changes):
    return {"gameId": "example", "sessionId": "session-a", "key": selections[3]["key"],
            "expectedRevision": None, "reason": "Prefer this reading version; still unverified",
            "operationId": uuid.uuid4().hex, **changes}


def test_selection_is_explicit_guarded_audited_and_not_verification(selections):
    assert call(selections)["body"]["selection"] is None
    body = request(selections)
    result = call(selections, body)
    assert result["statusCode"] == 200
    selection = result["body"]["selection"]
    assert selection["key"] == body["key"] and "not human verification" in selection["notice"]
    assert selection["version"]["number"] == 1
    assert call(selections)["body"]["selection"] == selection
    assert call(selections, body)["body"]["replayed"] is True
    assert call(selections, {**body, "reason": "Different operation"})["statusCode"] == 409
    assert call(selections, request(selections))["statusCode"] == 409
    second = call(selections, request(selections, expectedRevision=selection["revision"]))["body"]["selection"]
    assert second["previousRevision"] == selection["revision"]
    replay = call(selections, body)["body"]
    assert replay["selection"] == second and replay["operation"] == selection
    assert call(selections, username="example-reader")["statusCode"] == 403
    history = selections[1].table().get_item(Key={"pk": "transcript-selection-history#example#session-a", "sk": selection["revision"]})["Item"]
    assert json.loads(history["payload"]) == selection
    assert selections[3]["transcript"]["unassignedSegments"] == 1


@pytest.mark.parametrize("changes", [{"key":"games/other/assets/x/original/a.json"},
    {"sessionId":"session-b"}, {"reason":""}, {"operationId":"bad"}, {"expectedRevision":"bad"}])
def test_invalid_cross_game_and_cross_session_selection_never_writes(selections, changes):
    assert call(selections, request(selections, **changes))["statusCode"] == 400
    assert call(selections)["body"]["selection"] is None


def test_unauthorized_selection_and_missing_target_do_not_fall_back(selections):
    assert call(selections, request(selections), username="outsider")["statusCode"] == 403
    first = call(selections, request(selections))["body"]["selection"]
    selections[1].table().delete_item(Key={"pk": selections[1].partition("example", "transcripts"), "sk": first["key"]})
    result = call(selections)["body"]
    assert result["selection"]["key"] == first["key"] and "No fallback" in result["warning"]


@pytest.mark.parametrize("change", [{"transcript": {"state": "unavailable"}}, {"metadata": {"sessionId": "session-a"}}])
def test_unreadable_or_unversioned_transcript_cannot_be_designated(selections, change):
    asset = {**selections[3], **change}
    db = selections[1].table()
    db.update_item(Key={"pk": selections[1].partition("example", "transcripts"), "sk": asset["key"]},
                   UpdateExpression="SET payload = :payload", ExpressionAttributeValues={":payload": json.dumps(asset)})
    assert call(selections, request(selections))["statusCode"] == 400
    assert call(selections)["body"]["selection"] is None
