import importlib
import json
import uuid

import pytest

from test_novel_library import library  # noqa: F401
from test_novel import novel  # noqa: F401
from test_editorial import editorial  # noqa: F401
from test_model_jobs import broker, unpack  # noqa: F401


@pytest.fixture
def tv(library):  # noqa: F811
    module = importlib.import_module("tv_library")
    asset = {
        "key": "games/test-game/assets/video-one/original/video.mp4",
        "kind": "episode-video",
        "name": "video.mp4",
        "contentType": "video/mp4",
        "size": 100,
        "sourceKeys": [],
        "metadata": {"extra": {"relationshipRole": "finished"}, "sessionId": "session-one"},
    }
    module.browse_index.table().put_item(
        Item={
            "pk": module.browse_index.partition("test-game", "all"),
            "sk": asset["key"],
            "payload": json.dumps(asset),
            "observed": 1,
        }
    )
    return module, library[1].jobs.media, asset


def call(tv, kind="series", body=None, **q):
    return tv[0].handle(
        {
            "routeKey": ("POST " if body else "GET ")
            + ("/tv-series" if kind == "series" else "/tv-episodes"),
            "body": json.dumps(body) if body else None,
            "queryStringParameters": {"gameId": "test-game", **q},
            "requestContext": {
                "authorizer": {
                    "jwt": {
                        "claims": {"sub": "fictional-owner", "cognito:username": "example-operator"}
                    }
                }
            },
        },
        tv[1],
    )


def envelope(**changes):
    return {
        "gameId": "test-game",
        "id": "harbor-series",
        "title": "Harbor Tales",
        "synopsis": "Synthetic dramatization",
        "operationId": uuid.uuid4().hex,
        "expectedRevision": None,
        "reason": "Organize synthetic episodes",
        **changes,
    }


def series(**changes):
    return envelope(
        seasons=[
            {
                "id": "season-one",
                "number": 1,
                "title": "The Harbor",
                "synopsis": "A synthetic first season.",
            }
        ],
        **changes,
    )


def episode(tv, **changes):
    body = envelope(
        id="episode-one",
        seriesId="harbor-series",
        seasonId="season-one",
        number=1,
        status="draft",
        cuts=[
            {
                "id": "browser-cut",
                "title": "Browser edition",
                "assetKey": tv[2]["key"],
                "durationSeconds": None,
                "durationEvidence": None,
            }
        ],
        selectedCutId="browser-cut",
        posterAssetKey=None,
        captionAssetKeys=[],
        credits=[],
        sourceAssetKeys=[],
        relatedAssetKeys=[],
        preparationAssetKeys=[],
    )
    return {**body, **changes}


def test_series_episode_history_exact_members_and_retry(tv):
    parent = unpack(call(tv, body=series()))["record"]
    body = episode(tv)
    first = unpack(call(tv, "episode", body))["record"]
    detail = unpack(call(tv, "episode", id=body["id"]))
    assert detail["assets"] == [tv[2]] and detail["warnings"] == []
    assert unpack(call(tv, "episode", body))["replayed"]
    second = unpack(
        call(
            tv,
            "episode",
            {
                **body,
                "status": "approved",
                "expectedRevision": first["revision"],
                "operationId": uuid.uuid4().hex,
            },
        )
    )["record"]
    assert second["status"] == "approved" and second["previousRevision"] == first["revision"]
    assert (
        unpack(call(tv, "episode", id=body["id"], revision=first["revision"]))["record"]["status"]
        == "draft"
    )
    assert unpack(call(tv, "series", id=parent["id"]))["record"] == parent
    assert call(tv, "episode", {**body, "title": "Changed arguments"})["statusCode"] == 409


def test_episode_number_is_unique_and_renumbering_retains_history(tv):
    call(tv, body=series())
    body = episode(tv)
    first = unpack(call(tv, "episode", body))["record"]
    assert call(tv, "episode", episode(tv, id="episode-two"))["statusCode"] == 409
    changed = unpack(
        call(
            tv,
            "episode",
            {
                **body,
                "number": 2,
                "expectedRevision": first["revision"],
                "operationId": uuid.uuid4().hex,
            },
        )
    )["record"]
    assert changed["number"] == 2
    assert call(tv, "episode", episode(tv, id="episode-two"))["statusCode"] == 200
    assert (
        unpack(call(tv, "episode", id=body["id"], revision=first["revision"]))["record"]["number"]
        == 1
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"seriesId": "missing"},
        {"seasonId": "missing"},
        {"number": True},
        {"status": "public"},
        {"selectedCutId": "absent"},
        {"sourceAssetKeys": ["games/other/assets/a/original/a.json"]},
        {"captionAssetKeys": ["games/test-game/assets/missing/original/a.vtt"]},
        {"credits": [{"role": "Actor", "name": ""}]},
    ],
)
def test_invalid_or_foreign_metadata_never_creates_episode(tv, changes):
    call(tv, body=series())
    assert call(tv, "episode", {**episode(tv), **changes})["statusCode"] == 400
    assert unpack(call(tv, "episode"))["records"] == []


def test_source_catalog_changes_and_unavailable_members_are_explicit(tv, monkeypatch):
    call(tv, body=series())
    body = episode(tv)
    assert call(tv, "episode", body)["statusCode"] == 200
    tv[0].browse_index.table().delete_item(
        Key={"pk": tv[0].browse_index.partition("test-game", "all"), "sk": tv[2]["key"]}
    )
    detail = unpack(call(tv, "episode", id=body["id"]))
    assert detail["assets"] == [] and len(detail["warnings"]) == 1
    assert call(tv, "episode", episode(tv, id="episode-two", number=2))["statusCode"] == 400
    monkeypatch.setenv("MODEL_PUBLISHERS", "")
    assert call(tv)["statusCode"] == 403
