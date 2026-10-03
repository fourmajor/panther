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


def test_generated_chapter_edit_pins_prior_output_and_starts_human_family(library):  # noqa: F811
    _, novel_module = library
    from test_novel import completed
    from asset_storage import Storage

    m = importlib.import_module("manual_chapters")
    job, source_key = completed(novel_module)
    original = novel_module.chapter(job)
    # Place this synthetic completed output in the current physical catalog layout.
    import hashlib

    raw_client = novel_module.jobs.media.s3
    source = raw_client.get_object(Bucket=novel_module.jobs.media.BUCKET_NAME, Key=source_key)
    raw = source["Body"].read()
    storage = Storage(raw_client, novel_module.jobs.media.BUCKET_NAME)
    physical = storage.reserve(
        source_key,
        "novel-chapter",
        {"characterIds": [], "extra": {"relationshipRole": "finished"}},
        hashlib.sha256(raw).hexdigest(),
        len(raw),
        "2026-01-01T00:00:00Z",
    )
    raw_client.copy_object(
        Bucket=novel_module.jobs.media.BUCKET_NAME,
        Key=physical,
        CopySource={"Bucket": novel_module.jobs.media.BUCKET_NAME, "Key": source_key},
    )
    novel_module.jobs.media.s3 = storage
    request_body = body(previousChapterId=job["jobId"], markdown="A deliberately revised chapter.")
    result = json.loads(m.save(novel_module.jobs.media, request_body, "synthetic-author")["body"])
    saved = m.read("test-game", result["chapterId"], novel_module.jobs.media)
    assert saved["details"]["previousChapterId"] == job["jobId"]
    assert saved["details"]["sourceKeys"] == [source_key]
    assert request_body["sourceKeys"] == []
    assert saved["publicationStatus"] == "human-authored"
    assert saved["reviewStatus"] == "not-reviewed"
    assert novel_module.chapter(job)["markdown"] == original["markdown"]
    projected = novel_module.browse_index.refresh(novel_module.jobs.media, result["assetKey"])
    version = projected["metadata"]["extra"]["version"]
    assert version["number"] == 1
    assert version["seriesId"] == result["chapterId"]
    assert "previousKey" not in version
    assert projected["metadata"]["sourceKeys"] == [source_key]
    assert projected["metadata"]["extra"]["generation"]["method"] == "human"
    replay = json.loads(m.save(novel_module.jobs.media, request_body, "synthetic-author")["body"])
    assert replay == result


@pytest.mark.parametrize("invalid", ["unfinished", "foreign", "changed-bytes"])
def test_generated_chapter_edit_rejects_uncommitted_foreign_or_changed_output(library, invalid):  # noqa: F811
    _, novel_module = library
    from test_novel import completed
    from test_model_jobs import put

    m = importlib.import_module("manual_chapters")
    job, source_key = completed(
        novel_module, status="RUNNING" if invalid == "unfinished" else "DONE"
    )
    if invalid == "foreign":
        novel_module.jobs.table.update_item(
            Key={"pk": "RUNS", "sk": job["jobId"]},
            UpdateExpression="SET gameId = :game",
            ExpressionAttributeValues={":game": "foreign-game"},
        )
    if invalid == "changed-bytes":
        put(novel_module.jobs, source_key, b'{"changed":true}', "application/json")
    with pytest.raises(ValueError):
        m.save(novel_module.jobs.media, body(previousChapterId=job["jobId"]), "synthetic-author")
