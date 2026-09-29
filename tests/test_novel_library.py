import importlib
import json
import uuid

import boto3
import pytest

from test_novel import novel, completed  # noqa: F401
from test_editorial import editorial  # noqa: F401
from test_model_jobs import broker, request, unpack  # noqa: F401


@pytest.fixture
def library(novel, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CATALOG_TABLE", "narrative-games")
    table = boto3.resource("dynamodb").create_table(
        TableName="narrative-games",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.put_item(Item={"pk": "GAMES", "sk": "test-game"})
    return importlib.import_module("novel_library"), novel


def call(library, kind="story", body=None, **query):
    module, novel_module = library
    route = {
        "story": "/novel-stories",
        "book": "/novel-books",
        "illustration": "/novel-illustrations",
    }[kind]
    return module.handle(
        {
            "routeKey": ("POST " if body else "GET ") + route,
            "body": json.dumps(body) if body else None,
            "queryStringParameters": {"gameId": "test-game", **query},
            "requestContext": {
                "authorizer": {
                    "jwt": {
                        "claims": {"sub": "fictional-owner", "cognito:username": "example-operator"}
                    }
                }
            },
        },
        novel_module.jobs.media,
    )


def envelope(**changes):
    return {
        "gameId": "test-game",
        "id": "harbor-story",
        "title": "Harbor Tales",
        "synopsis": "Synthetic story.",
        "expectedRevision": None,
        "operationId": uuid.uuid4().hex,
        "reason": "Organize synthetic chapters",
        **changes,
    }


def book(library, **changes):
    _, key = completed(library[1])
    return envelope(
        id="book-one",
        storyId="harbor-story",
        authorCredit=None,
        coverAssetKey=None,
        classification="grounded-adaptation",
        status="draft",
        order=1,
        volumes=[{"id": "volume-one", "title": "The Harbor", "chapterKeys": [key]}],
        relatedAssetKeys=[],
        **changes,
    )


def illustrations(library):
    job, chapter = completed(library[1])
    key = "games/test-game/assets/illustration/original/image.png"
    asset = {
        "key": key,
        "kind": "portrait",
        "contentType": "image/png",
        "size": 20,
        "metadata": {"extra": {"relationshipRole": "finished"}},
    }
    library[1].browse_index.table().put_item(
        Item={
            "pk": library[1].browse_index.partition("test-game", "all"),
            "sk": key,
            "observed": 1,
            "payload": json.dumps(asset),
        }
    )
    return envelope(
        id=job["jobId"],
        chapterKey=chapter,
        status="approved",
        illustrations=[
            {
                "assetKey": key,
                "placement": "before-chapter",
                "altText": "A fictional harbor",
                "caption": "Illustrative adaptation",
            }
        ],
    )


def test_illustrations_pin_exact_chapter_and_keep_revision_history(library):
    body = illustrations(library)
    first = unpack(call(library, "illustration", body))["record"]
    assert first["entityType"] == "ChapterIllustrations"
    assert first["chapterKey"] == body["chapterKey"]
    assert unpack(call(library, "illustration", body))["replayed"]
    second = unpack(
        call(
            library,
            "illustration",
            {
                **body,
                "expectedRevision": first["revision"],
                "operationId": uuid.uuid4().hex,
                "illustrations": [],
            },
        )
    )["record"]
    assert second["previousRevision"] == first["revision"]
    assert (
        unpack(call(library, "illustration", id=body["id"], revision=first["revision"]))["record"]
        == first
    )
    assert unpack(call(library, "illustration", body))["record"] == second


@pytest.mark.parametrize(
    "invalid",
    ["foreign", "alt", "placement", "duplicate", "chapter", "unfinished", "internal", "oversized"],
)
def test_illustrations_reject_invalid_inputs_without_writes(library, invalid):
    body = illustrations(library)
    entry = body["illustrations"][0]
    if invalid == "foreign":
        entry["assetKey"] = "games/other/assets/image/original/image.png"
    if invalid == "alt":
        entry["altText"] = ""
    if invalid == "placement":
        entry["placement"] = "after-paragraph-guess"
    if invalid == "duplicate":
        body["illustrations"] *= 2
    if invalid == "chapter":
        body["id"] = "f" * 64
    if invalid == "unfinished":
        library[1].jobs.table.update_item(
            Key={"pk": "TASKS", "sk": body["id"] + ":novel-chapter"},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "RUNNING"},
        )
    if invalid in {"internal", "oversized"}:
        db = library[1].browse_index.table()
        key = {"pk": library[1].browse_index.partition("test-game", "all"), "sk": entry["assetKey"]}
        item = db.get_item(Key=key)["Item"]
        asset = json.loads(item["payload"])
        if invalid == "internal":
            asset["metadata"]["extra"]["relationshipRole"] = "intermediate"
        else:
            asset["size"] = 9 * 1024**2
        db.put_item(Item={**item, "payload": json.dumps(asset)})
    assert call(library, "illustration", body)["statusCode"] == 400
    assert unpack(call(library, "illustration"))["records"] == []


def test_illustration_catalog_race_and_nonpublisher_blocked(library, monkeypatch):
    body = illustrations(library)
    original = library[0].indexed

    def stale(game, keys):
        result = original(game, keys)
        for item in result.values():
            item["observed"] += 1
        return result

    monkeypatch.setattr(library[0], "indexed", stale)
    assert call(library, "illustration", body)["statusCode"] == 409
    monkeypatch.setenv("MODEL_PUBLISHERS", "")
    assert call(library, "illustration", body)["statusCode"] == 403


def test_story_revision_history_conflicts_and_exact_retries(library):
    body = envelope()
    first = unpack(call(library, body=body))["record"]
    assert unpack(call(library, body=body))["replayed"]
    assert call(library, body={**body, "title": "Changed"})["statusCode"] == 409
    second = unpack(
        call(library, body=envelope(expectedRevision=first["revision"], title="A New Title"))
    )["record"]
    assert second["previousRevision"] == first["revision"]
    assert unpack(call(library, id=body["id"], revision=first["revision"]))["record"] == first
    replay = unpack(call(library, body=body))
    assert replay["record"] == second and replay["operationRevision"] == first["revision"]
    assert len(unpack(call(library))["records"]) == 1


def test_book_pins_completed_chapters_and_private_approval_not_source_state(library):
    call(library, body=envelope())
    body = book(library)
    before = library[1].jobs.table.scan()["Items"]
    first = unpack(call(library, "book", body))["record"]
    assert first["volumes"] == body["volumes"] and first["status"] == "draft"
    second = unpack(
        call(
            library,
            "book",
            {
                **body,
                "expectedRevision": first["revision"],
                "operationId": uuid.uuid4().hex,
                "status": "approved",
            },
        )
    )["record"]
    assert second["status"] == "approved"
    assert (
        unpack(call(library, "book", id=body["id"], revision=first["revision"]))["record"]["status"]
        == "draft"
    )
    assert library[1].jobs.table.scan()["Items"] == before


@pytest.mark.parametrize(
    "changes",
    [
        {"storyId": "missing"},
        {"classification": "canon"},
        {"status": "public"},
        {"order": True},
        {"volumes": []},
        {"relatedAssetKeys": ["games/other/assets/a/original/b.png"]},
        {"coverAssetKey": "games/test-game/assets/missing/original/a.png"},
    ],
)
def test_invalid_books_fail_without_writes(library, changes):
    call(library, body=envelope())
    body = book(library)
    assert call(library, "book", {**body, **changes})["statusCode"] == 400
    assert unpack(call(library, "book"))["records"] == []


def test_unfinished_chapter_and_foreign_cursor_rejected(library):
    call(library, body=envelope())
    body = book(library)
    key = body["volumes"][0]["chapterKeys"][0]
    summary = json.loads(
        library[1]
        .browse_index.table()
        .get_item(Key={"pk": library[1].browse_index.partition("test-game", "all"), "sk": key})[
            "Item"
        ]["payload"]
    )["novel"]
    library[1].jobs.table.update_item(
        Key={"pk": "TASKS", "sk": summary["id"] + ":novel-chapter"},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "RUNNING"},
    )
    assert call(library, "book", body)["statusCode"] == 400
    assert call(library, "book", cursor="garbage")["statusCode"] == 400


def test_source_index_conflict_and_authorization_are_not_bypassed(library, monkeypatch):
    call(library, body=envelope())
    body = book(library)
    original = library[0].indexed

    def changed(game, keys):
        found = original(game, keys)
        for item in found.values():
            item["observed"] += 1
        return found

    monkeypatch.setattr(library[0], "indexed", changed)
    assert call(library, "book", body)["statusCode"] == 409
    assert unpack(call(library, "book"))["records"] == []
    monkeypatch.setenv("MODEL_PUBLISHERS", "")
    assert call(library)["statusCode"] == 403
