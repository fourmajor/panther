import importlib
import json
import uuid

import pytest

from test_browse_index import index  # noqa: F401
from test_transcript_selection import selections  # noqa: F401


@pytest.fixture
def library(selections, monkeypatch):  # noqa: F811
    module = importlib.import_module("video_collections")
    monkeypatch.setattr(module, "browse_index", selections[1])
    assets = []
    for number in range(2):
        asset = {
            **selections[3],
            "key": f"games/example/assets/video-{number}/original/clip.mp4",
            "name": "clip.mp4",
            "kind": "silly-video",
            "contentType": "video/mp4",
        }
        selections[1].table().put_item(
            Item={
                "pk": selections[1].partition("example", "all"),
                "sk": asset["key"],
                "payload": json.dumps(asset),
                "observed": number + 1,
            }
        )
        assets.append(asset)
    return module, selections[1], selections[2], assets


def call(library, body=None, username="example-owner", **query):
    return library[0].handle(
        {
            "routeKey": "POST /video-collections" if body else "GET /video-collections",
            "body": json.dumps(body) if body else None,
            "queryStringParameters": {"gameId": "example", **query},
            "requestContext": {
                "authorizer": {
                    "jwt": {"claims": {"sub": "fictional-account", "cognito:username": username}}
                }
            },
        },
        library[2],
    )


def request(library, **changes):
    return {
        "gameId": "example",
        "id": "highlights",
        "name": "Highlights",
        "description": "Synthetic collection",
        "assetKeys": [a["key"] for a in reversed(library[3])],
        "expectedRevision": None,
        "operationId": uuid.uuid4().hex,
        **changes,
    }


def test_ordered_collection_guard_history_and_idempotency(library):
    assert call(library)["body"]["collections"] == []
    body = request(library)
    first = call(library, body)
    assert first["statusCode"] == 200
    record = first["body"]["collection"]
    detail = call(library, id="highlights")["body"]
    assert [a["key"] for a in detail["assets"]] == body["assetKeys"]
    assert detail["warnings"] == []
    assert call(library, body)["body"]["replayed"] is True
    assert call(library, {**body, "name": "New name"})["statusCode"] == 409
    assert call(library, request(library))["statusCode"] == 409
    second = call(library, request(library, expectedRevision=record["revision"]))["body"][
        "collection"
    ]
    assert second["previousRevision"] == record["revision"]
    assert call(library, body)["body"]["collection"] == second
    history = (
        library[1]
        .table()
        .get_item(
            Key={"pk": "video-collection-history#example#highlights", "sk": record["revision"]}
        )["Item"]
    )
    assert json.loads(history["payload"]) == record
    assert len(call(library)["body"]["collections"]) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"assetKeys": []},
        {"assetKeys": ["games/other/assets/video/original/clip.mp4"]},
        {"assetKeys": ["games/example/assets/unknown/original/clip.mp4"]},
        {"name": ""},
        {"expectedRevision": "bad"},
        {"operationId": "bad"},
        {"assetKeys": ["games/example/assets/video-0/original/clip.mp4"] * 2},
    ],
)
def test_invalid_collection_cannot_write(library, changes):
    assert call(library, request(library, **changes))["statusCode"] == 400
    assert call(library)["body"]["collections"] == []


def test_missing_members_are_reported_and_never_substituted(library):
    body = request(library)
    assert call(library, body, username="outsider")["statusCode"] == 403
    assert call(library, username="outsider")["statusCode"] == 403
    assert call(library, body)["statusCode"] == 200
    library[1].table().delete_item(
        Key={"pk": library[1].partition("example", "all"), "sk": body["assetKeys"][0]}
    )
    result = call(library, id="highlights")["body"]
    assert len(result["assets"]) == 1 and result["warnings"][0]["key"] == body["assetKeys"][0]
    assert len(result["collection"]["assetKeys"]) == 2
    assert call(library, id="missing")["statusCode"] == 404


def test_unprocessed_catalog_reads_fail_instead_of_claiming_missing_members(library, monkeypatch):
    class Throttled:
        def batch_get_item(self, **kwargs):
            return {"UnprocessedKeys": kwargs["RequestItems"]}

    monkeypatch.setattr(library[0].boto3, "resource", lambda *_: Throttled())
    # Replace the table accessor before stubbing the shared boto3 resource.
    from types import SimpleNamespace

    monkeypatch.setattr(library[1], "table", lambda: SimpleNamespace(name="synthetic-browse"))
    with pytest.raises(RuntimeError, match="incomplete"):
        library[0].members(library[2], "example", [a["key"] for a in library[3]])
