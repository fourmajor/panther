import importlib
import json
import uuid

import pytest

from test_novel_library import library  # noqa: F401
from test_novel import novel  # noqa: F401
from test_editorial import editorial  # noqa: F401
from test_model_jobs import broker  # noqa: F401


def body(**changes):
    return {
        "gameId": "test-game",
        "title": "The River",
        "markdown": "An explicitly authored fictional chapter.",
        "sourceKeys": [],
        "operationId": uuid.uuid4().hex,
        "previousChapterId": None,
        **changes,
    }


def test_manual_chapters_preserve_immutable_versions_and_honest_authorship(library):  # noqa: F811
    _, novel_module = library
    m = importlib.import_module("manual_chapters")
    from asset_storage import Storage

    novel_module.jobs.media.s3 = Storage(
        novel_module.jobs.media.s3, novel_module.jobs.media.BUCKET_NAME
    )
    first = body()
    saved = json.loads(m.save(novel_module.jobs.media, first, "synthetic-author")["body"])
    identity = saved["chapterId"]
    replay = json.loads(m.save(novel_module.jobs.media, first, "synthetic-author")["body"])
    assert replay == saved
    original = m.read("test-game", identity, novel_module.jobs.media)
    assert original["markdown"] == first["markdown"]
    assert original["reviewStatus"] == "not-reviewed"
    assert original["details"]["authorship"] == "human"
    assert (
        m.save(novel_module.jobs.media, {**first, "markdown": "Different"}, "synthetic-author")[
            "statusCode"
        ]
        == 409
    )
    second = body(
        previousChapterId=identity, title="The River revised", markdown="A new authored revision."
    )
    next_id = json.loads(m.save(novel_module.jobs.media, second, "synthetic-author")["body"])[
        "chapterId"
    ]
    assert m.read("test-game", identity, novel_module.jobs.media)["markdown"] == first["markdown"]
    assert (
        m.read("test-game", next_id, novel_module.jobs.media)["details"]["previousChapterId"]
        == identity
    )
    asset = novel_module.browse_index.refresh(novel_module.jobs.media, saved["assetKey"])
    assert asset["novel"]["authorship"] == "human"
    assert asset["metadata"]["extra"]["generation"]["method"] == "human"
    novel_module.browse_index.refresh(
        novel_module.jobs.media, m.record("test-game", next_id)["assetKey"]
    )
    event = {
        "routeKey": "GET /novel",
        "queryStringParameters": {"gameId": "test-game"},
        "requestContext": {
            "authorizer": {
                "jwt": {"claims": {"sub": "synthetic-author", "cognito:username": "example-owner"}}
            }
        },
    }
    # Use the fixture's configured reader identity rather than introducing account data.
    from access_policy import authorized
    import os

    event["requestContext"]["authorizer"]["jwt"]["claims"]["cognito:username"] = os.environ[
        "MODEL_PUBLISHERS"
    ].split(",")[0]
    assert authorized(event["requestContext"]["authorizer"]["jwt"]["claims"], "MODEL_PUBLISHERS")
    listing = novel_module.handler(event, None)
    assert listing["statusCode"] == 200
    assert len(json.loads(listing["body"])["chapters"]) == 2
    event["routeKey"] = "GET /novel-chapter"
    event["queryStringParameters"]["chapterId"] = next_id
    assert json.loads(novel_module.handler(event, None)["body"])["title"] == "The River revised"
    from test_novel_library import call, envelope

    assert call(library, body=envelope())["statusCode"] == 200
    selection = envelope(
        id="manual-book",
        storyId="harbor-story",
        authorCredit=None,
        coverAssetKey=None,
        classification="creative-reimagining",
        status="draft",
        order=1,
        volumes=[
            {"id": "first-volume", "title": "First volume", "chapterKeys": [saved["assetKey"]]}
        ],
        relatedAssetKeys=[],
    )
    assert call(library, "book", body=selection)["statusCode"] == 200


@pytest.mark.parametrize(
    "changes",
    [
        {"sourceKeys": ["games/foreign/assets/example/original/source.json"]},
        {"previousChapterId": "a" * 64},
        {"title": ""},
        {"markdown": ""},
    ],
)
def test_manual_chapters_reject_invalid_or_unavailable_sources(library, changes):  # noqa: F811
    _, novel_module = library
    m = importlib.import_module("manual_chapters")
    with pytest.raises(ValueError):
        m.save(novel_module.jobs.media, body(**changes), "synthetic-author")
