"""Archive contract: retained bytes, current references, races and verified activation."""

import base64
import importlib
from pathlib import Path
from types import SimpleNamespace
import boto3
import pytest
from moto import mock_aws
from botocore.exceptions import ClientError


@pytest.fixture
def archive(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "infra/lambda/media-api"))
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("ASSET_BROWSE_TABLE", "archive-test")
    with mock_aws():
        for name in ("archive-test", "jobs-test", "catalog-test"):
            boto3.resource("dynamodb").create_table(
                TableName=name,
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
        module = importlib.import_module("asset_archive")
        monkeypatch.setattr(module, "boto3", boto3)
        module.db().put_item(Item={"pk": "asset-archives-v1#catalog", "sk": "ready"})
        yield module


def request():
    return {
        "gameId": "example",
        "key": "games/example/assets/map/original/map.png",
        "sha256": base64.b64encode(b"x" * 32).decode(),
        "operationId": "a" * 32,
    }


def media():
    return SimpleNamespace(
        _valid_slug=lambda value: value == "example",
        _valid_key=lambda value: value.startswith("games/example/assets/"),
        BUCKET_NAME="private",
        s3=SimpleNamespace(head_object=lambda **kwargs: {"ChecksumSHA256": request()["sha256"]}),
    )


def commit(archive, owner, keys, active=None):
    boto3.client("dynamodb").transact_write_items(
        TransactItems=archive.reference_writes("example", owner, keys, active)
    )


def test_archive_retains_bytes_and_historical_refs_but_removes_all_catalog_sections(archive):
    import browse_index

    body = request()
    table = archive.db()
    for section in browse_index.SECTIONS:
        table.put_item(
            Item={
                "pk": browse_index.partition("example", section),
                "sk": body["key"],
                "payload": "{}",
            }
        )
    table.put_item(Item={"pk": "historical", "sk": "previous", "sourceKeys": [body["key"]]})
    assert archive.archive(body, "fictional-user", media()) == {"deleted": True, "key": body["key"]}
    assert archive.archived("example", body["key"])
    assert all(
        not table.get_item(
            Key={"pk": browse_index.partition("example", section), "sk": body["key"]}
        ).get("Item")
        for section in browse_index.SECTIONS
    )
    assert table.get_item(Key={"pk": "historical", "sk": "previous"})["Item"]["sourceKeys"] == [
        body["key"]
    ]
    assert archive.archive(body, "fictional-user", media())["replayed"]
    with pytest.raises(ValueError):
        archive.archive(
            {**body, "sha256": base64.b64encode(b"z" * 32).decode()}, "fictional-user", media()
        )


@pytest.mark.parametrize("owner", ["character:hero", "appearance:hero", "scene:episode:scene"])
def test_current_selection_blocks_archive(archive, owner):
    body = request()
    commit(archive, owner, [body["key"]])
    with pytest.raises(LookupError, match="selected"):
        archive.archive(body, "fictional-user", media())
    commit(archive, owner, [])
    assert archive.archive(body, "fictional-user", media())["deleted"]


@pytest.mark.parametrize(
    "status,blocked", [("SUBMITTED", True), ("ATTENTION", True), ("DONE", False), ("FAILED", False)]
)
def test_only_active_job_input_pins_block_archive(archive, status, blocked):
    table = boto3.resource("dynamodb").Table("jobs-test")
    table.put_item(Item={"pk": "JOBS", "sk": "job", "status": status})
    commit(
        archive,
        "model-job:job",
        [request()["key"]],
        {"table": table.name, "pk": "JOBS", "sk": "job"},
    )
    assert archive.current_references("example", request()["key"]) is blocked


def test_concurrent_new_selection_cancels_archive(archive, monkeypatch):
    original = archive.current_references

    def race(game, key):
        assert not original(game, key)
        commit(archive, "character:new", [key])
        return False

    monkeypatch.setattr(archive, "current_references", race)
    with pytest.raises(ClientError):
        archive.archive(request(), "fictional-user", media())
    assert not archive.archived("example", request()["key"])


def test_archived_input_rejects_new_pins_atomically(archive):
    archive.archive(request(), "fictional-user", media())
    with pytest.raises(ClientError):
        commit(archive, "scene:episode:scene", [request()["key"]])
    assert (
        not archive.db()
        .get_item(Key={"pk": "asset-references-v1#example", "sk": "scene:episode:scene"})
        .get("Item")
    )


def test_checksum_and_migration_guards_fail_closed(archive):
    with pytest.raises(LookupError, match="changed"):
        archive.archive(
            {**request(), "sha256": base64.b64encode(b"z" * 32).decode()}, "fictional-user", media()
        )
    archive.db().delete_item(Key={"pk": "asset-archives-v1#catalog", "sk": "ready"})
    with pytest.raises(RuntimeError, match="migration"):
        archive.archive(request(), "fictional-user", media())


def test_projection_refresh_never_resurrects_archive(archive, monkeypatch):
    import browse_index
    import asset_library

    archive.archive(request(), "fictional-user", media())
    value = {
        "key": request()["key"],
        "kind": "map",
        "contentType": "image/png",
        "name": "map.png",
        "metadata": {},
        "sourceKeys": [],
    }
    monkeypatch.setattr(asset_library, "describe", lambda *_: value)
    assert browse_index.refresh(None, request()["key"]) == value
    assert (
        not archive.db()
        .get_item(Key={"pk": browse_index.partition("example", "all"), "sk": request()["key"]})
        .get("Item")
    )


def test_all_game_migration_requires_verified_projection_before_activation(archive, monkeypatch):
    import sys

    migration = importlib.import_module("asset_archive_migration")
    monkeypatch.setitem(sys.modules, "index", media())
    monkeypatch.setenv("CATALOG_TABLE", "catalog-test")
    catalog = boto3.resource("dynamodb").Table("catalog-test")
    catalog.put_item(Item={"pk": "GAMES", "sk": "example", "id": "example"})
    archive.db().delete_item(Key={"pk": "asset-archives-v1#catalog", "sk": "ready"})
    refs = [{"owner": "character:hero", "keys": [request()["key"]]}]
    monkeypatch.setattr(migration, "inventory", lambda game: refs)
    with pytest.raises(RuntimeError, match="Every game"):
        migration.migrate({"mode": "activate"})
    assert migration.migrate({"gameId": "example", "mode": "dry-run"})["references"] == 1
    migration.migrate({"gameId": "example", "mode": "apply"})
    migration.migrate({"gameId": "example", "mode": "verify"})
    assert migration.migrate({"mode": "activate"})["games"] == 1
    assert (
        archive.db().get_item(Key={"pk": "asset-archives-v1#catalog", "sk": "ready"})["Item"][
            "schemaVersion"
        ]
        == 1
    )


def test_migration_detects_concurrent_reference_write(archive, monkeypatch):
    import sys

    migration = importlib.import_module("asset_archive_migration")
    monkeypatch.setitem(sys.modules, "index", media())

    def race(game):
        commit(archive, "character:new", [])
        return []

    monkeypatch.setattr(migration, "inventory", race)
    with pytest.raises(RuntimeError, match="changed during inventory"):
        migration.migrate({"gameId": "example", "mode": "apply"})
    assert (
        not archive.db()
        .get_item(Key={"pk": "asset-archives-v1#verified", "sk": "example"})
        .get("Item")
    )


@pytest.mark.parametrize(
    "kind,content_type",
    [
        ("recording", "audio/wav"),
        ("raw-transcript", "application/json"),
        ("recording-playback-manifest", "application/json"),
    ],
)
def test_unintegrated_recording_workflow_inputs_fail_closed(archive, kind, content_type):
    value = media()
    value.s3.head_object = lambda **kwargs: {
        "ChecksumSHA256": request()["sha256"],
        "Metadata": {"kind": kind},
        "ContentType": content_type,
    }
    with pytest.raises(LookupError, match="not available yet"):
        archive.archive(request(), "fictional-user", value)
    assert not archive.archived("example", request()["key"])


def test_inventory_projects_explicit_current_profiles_appearances_and_scene_assets(
    archive, monkeypatch
):
    import json

    migration = importlib.import_module("asset_archive_migration")
    for name in ("EDITORIAL_TABLE", "MODEL_JOBS_TABLE", "ASSET_GENERATION_TABLE"):
        monkeypatch.setenv(name, "jobs-test")
    monkeypatch.setenv("CATALOG_TABLE", "catalog-test")
    catalog = boto3.resource("dynamodb").Table("catalog-test")
    table = archive.db()
    key = request()["key"]
    catalog.put_item(
        Item={
            "pk": "GAME#example",
            "sk": "CHARACTER#hero",
            "entityType": "Character",
            "gameId": "example",
            "id": "hero",
            "schemaVersion": 2,
            "detailsRevision": "a" * 32,
            "detailsJson": json.dumps({"thumbnailAssetKey": key}),
            "appearanceContractJson": json.dumps({"schemaVersion": 1, "origin": "created-current"}),
        }
    )
    table.put_item(
        Item={
            "pk": "character-looks#activation#hero#example",
            "sk": "current",
            "payload": json.dumps({"appearanceId": "initial", "selectionId": "chosen"}),
        }
    )
    table.put_item(
        Item={
            "pk": "character-looks#selection#hero#example",
            "sk": "chosen",
            "payload": json.dumps(
                {"portraitKey": key, "modelKey": None, "sourceKey": None, "provenanceKey": None}
            ),
        }
    )
    table.put_item(
        Item={
            "pk": "episode-scenes-v1#episode#example",
            "sk": "arrival",
            "payload": json.dumps({"id": "arrival"}),
        }
    )
    table.put_item(
        Item={
            "pk": "episode-scenes-v1#scene#arrival#example",
            "sk": "gate",
            "payload": json.dumps({"id": "gate", "mapAssetKey": key, "selectedOutputKey": None}),
        }
    )
    assert migration.inventory("example") == [
        {"owner": "appearance:hero", "keys": [key]},
        {"owner": "character:hero", "keys": [key]},
        {"owner": "scene:arrival:gate", "keys": [key]},
    ]


@pytest.mark.parametrize(
    "document",
    [
        {"entityType": "BrowserRecording"},
        {"entityType": "PlayerTranscript"},
        {
            "stage": "corrected-transcript",
            "payload": {"transcript": {"entityType": "PlayerTranscript"}},
        },
    ],
)
def test_unknown_kind_json_is_classified_before_archive(archive, document):
    import io
    import json

    body = {**request(), "key": "games/example/assets/unknown/original/context.json"}
    value = media()
    value.s3.get_object = lambda **kwargs: {"Body": io.BytesIO(json.dumps(document).encode())}
    with pytest.raises(LookupError, match="not available yet"):
        archive.archive(body, "fictional-user", value)
    assert not archive.archived("example", body["key"])


def test_arbitrary_json_context_can_be_archived(archive):
    import io

    body = {**request(), "key": "games/example/assets/context/original/context.json"}
    value = media()
    value.s3.get_object = lambda **kwargs: {"Body": io.BytesIO(b'{"setting":"fictional place"}')}
    assert archive.archive(body, "fictional-user", value)["deleted"]


def test_foreign_reference_is_rejected_without_silent_projection_loss(archive):
    with pytest.raises(ValueError, match="same game"):
        archive.reference_writes(
            "example", "character:hero", ["games/another/assets/map/original/map.png"]
        )


def test_unavailable_archive_reports_human_message_and_logs_diagnostic(
    archive, monkeypatch, caplog
):
    import sys

    media_api = SimpleNamespace(_response=lambda status, body: (status, body))
    monkeypatch.setitem(sys.modules, "index", media_api)
    monkeypatch.setattr(archive, "authorized", lambda *_: True)
    monkeypatch.setattr(
        archive,
        "archive",
        lambda *_: (_ for _ in ()).throw(RuntimeError("Asset archive migration must be verified")),
    )
    monkeypatch.setattr(media_api, "_response", lambda status, body: (status, body))
    response = archive.handler(
        {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "example-member"}}}}}, None
    )
    assert response == (503, {"error": "Asset deletion is temporarily unavailable."})
    assert "migration must be verified" in caplog.text
