import importlib
import json

import boto3
from botocore.exceptions import ClientError

import pytest

from test_editorial import editorial, submitted  # noqa: F401
from test_model_jobs import broker, put, request, unpack  # noqa: F401


@pytest.fixture
def novel(editorial, monkeypatch):  # noqa: F811
    monkeypatch.delitem(__import__("sys").modules, "novel", raising=False)
    monkeypatch.setenv("ASSET_BROWSE_TABLE", "novel-browse")
    boto3.resource("dynamodb").create_table(
        TableName="novel-browse",
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
    module = importlib.import_module("novel")
    monkeypatch.setattr(module.browse_index, "boto3", boto3)
    monkeypatch.setattr(module.browse_index, "ClientError", ClientError)
    module.browse_index.table().put_item(Item={"pk": "v3#catalog", "sk": "ready"})
    return module


def completed(novel, *, status="DONE", publication="accepted"):
    m = novel.jobs
    _, job = submitted(m)
    key = f"games/test-game/assets/editorial-{job['jobId'][:32]}-test/original/novel-chapter.json"
    artifact = {
        "entityType": "EditorialArtifact",
        "gameId": job["gameId"],
        "jobId": job["jobId"],
        "sessionId": job["sessionId"],
        "stage": "novel-chapter",
        "publicationStatus": publication,
        "payload": {
            "readerReferences": {
                "schemaVersion": 1,
                "mentions": [
                    {"text": "the captain", "target": {"type": "character", "id": "captain"}}
                ],
            },
            "chapter": "**Adapted from fictional microphone-test material; not campaign canon.**\n\n# A Synthetic Story\n\nOnly the **story**.\n\n## Editorial notes\n\nA fictional sign on the wall.",
            "review": {
                "markdown": "Private editorial audit",
                "uncertainties": ["Uncertain spelling"],
            },
        },
        "sourceKeys": [job["raw"]["key"]],
        "rawReference": job["raw"],
    }
    put(m, key, json.dumps(artifact).encode(), "application/json")
    reference, _ = m.asset(key, job["gameId"])
    m.table.put_item(
        Item={
            "pk": "TASKS",
            "sk": f"{job['jobId']}:novel-chapter",
            "status": status,
            "output": reference,
        }
    )
    novel.browse_index.refresh(m.media, key)
    return job, key


def test_completed_chapter_visible_before_video_finishes_and_prose_is_separate(novel):
    job, _ = completed(novel)
    q = {"gameId": "test-game"}
    listing = unpack(request(novel, "GET /novel", query=q))["chapters"]
    assert len(listing) == 1 and listing[0]["title"] == "A Synthetic Story"
    assert "details" not in listing[0] and "markdown" not in listing[0]
    assert "readerReferences" not in listing[0]
    result = unpack(request(novel, "GET /novel-chapter", query={**q, "chapterId": job["jobId"]}))
    assert result["markdown"].startswith("Only the **story**.")
    assert result["readerReferences"]["mentions"][0]["target"]["type"] == "character"
    assert "readerReferences" not in result["markdown"]
    assert "## Editorial notes" in result["markdown"]  # Never truncate arbitrary story headings.
    assert "Private editorial audit" not in result["markdown"]
    assert result["details"]["review"]["markdown"] == "Private editorial audit"
    assert result["notice"].endswith("not campaign canon.")
    assert "taskToken" not in json.dumps(result)
    assert request(novel, "GET /novel", query=q, username="example-editor")["statusCode"] == 200


def test_auth_game_boundaries_and_unfinished_chapters(novel):
    job, _ = completed(novel, status="RUNNING")
    q = {"gameId": "test-game", "chapterId": job["jobId"]}
    assert unpack(request(novel, "GET /novel", query=q))["chapters"] == []
    assert request(novel, "GET /novel-chapter", query=q)["statusCode"] == 404
    job, _ = completed(novel)
    assert request(novel, "GET /novel", query=q, username="outsider")["statusCode"] == 403
    assert request(novel, "GET /novel", query=q, actor="")["statusCode"] == 403
    assert (
        request(novel, "GET /novel-chapter", query={**q, "gameId": "other-game"})["statusCode"]
        == 404
    )
    assert request(novel, "GET /novel", query={"gameId": "../test-game"})["statusCode"] == 400
    assert (
        request(novel, "GET /novel-chapter", query={**q, "chapterId": "../anything"})["statusCode"]
        == 400
    )


def test_altered_artifact_and_foreign_reference_are_rejected(novel):
    job, key = completed(novel)
    put(novel.jobs, key, b"{}", "application/json")
    q = {"gameId": "test-game", "chapterId": job["jobId"]}
    assert request(novel, "GET /novel-chapter", query=q)["statusCode"] == 400
    novel.jobs.table.update_item(
        Key={"pk": "TASKS", "sk": f"{job['jobId']}:novel-chapter"},
        UpdateExpression="SET #o = :o",
        ExpressionAttributeNames={"#o": "output"},
        ExpressionAttributeValues={
            ":o": {"key": "games/other-game/assets/a/original/a.json", "size": 2}
        },
    )
    assert request(novel, "GET /novel-chapter", query=q)["statusCode"] == 400


def test_pagination_is_bounded_and_cursor_scoped_to_game(novel):
    completed(novel)
    for i in range(101):
        novel.browse_index.table().put_item(
            Item={
                "pk": novel.browse_index.partition("test-game", "novels"),
                "sk": f"z{i:04}",
                "payload": json.dumps({"novel": {"state": "unavailable"}}),
            }
        )
    page = unpack(request(novel, "GET /novel", query={"gameId": "test-game"}))
    assert page["cursor"]
    next_page = unpack(
        request(novel, "GET /novel", query={"gameId": "test-game", "cursor": page["cursor"]})
    )
    assert not next_page["cursor"]
    assert (
        request(novel, "GET /novel", query={"gameId": "test-game", "cursor": "garbage"})[
            "statusCode"
        ]
        == 400
    )
    assert (
        request(novel, "GET /novel", query={"gameId": "other-game", "cursor": page["cursor"]})[
            "statusCode"
        ]
        == 400
    )


def test_listing_never_opens_manuscripts_and_uses_completed_exact_output(novel, monkeypatch):
    job, key = completed(novel)
    monkeypatch.setattr(novel.jobs, "document", lambda *_: pytest.fail("Listing opened manuscript"))
    monkeypatch.setattr(
        novel.jobs.media.s3, "head_object", lambda **_: pytest.fail("Listing read S3")
    )
    q = {"gameId": "test-game"}
    assert unpack(request(novel, "GET /novel", query=q))["chapters"][0]["assetKey"] == key
    novel.jobs.table.update_item(
        Key={"pk": "TASKS", "sk": f"{job['jobId']}:novel-chapter"},
        UpdateExpression="SET #o = :o",
        ExpressionAttributeNames={"#o": "output"},
        ExpressionAttributeValues={":o": {"key": key + "other"}},
    )
    assert unpack(request(novel, "GET /novel", query=q))["chapters"] == []


def test_index_upgrade_and_incomplete_status_reads_fail_closed(novel, monkeypatch):
    completed(novel)
    monkeypatch.setattr(novel, "committed_records", lambda _: (_ for _ in ()).throw(RuntimeError()))
    assert request(novel, "GET /novel", query={"gameId": "test-game"})["statusCode"] == 503
    novel.browse_index.table().delete_item(Key={"pk": "v3#catalog", "sk": "ready"})
    assert request(novel, "GET /novel", query={"gameId": "test-game"})["statusCode"] == 503


def test_working_draft_label_is_not_added_to_prose(novel):
    job, _ = completed(novel, publication="accepted-with-notes")
    result = unpack(
        request(
            novel, "GET /novel-chapter", query={"gameId": "test-game", "chapterId": job["jobId"]}
        )
    )
    assert result["publicationStatus"] == "accepted-with-notes"
    assert "Working draft" not in result["markdown"]
