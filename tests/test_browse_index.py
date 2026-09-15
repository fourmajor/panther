"""Synthetic catalog tests: listing never opens S3 assets."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def index(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "infra/lambda/media-api"))
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("ASSET_BROWSE_TABLE", "synthetic-browse")
    module = importlib.import_module("browse_index")
    # Older handler tests intentionally import with a stub boto3 module.
    monkeypatch.setattr(module, "boto3", boto3)
    with mock_aws():
        boto3.resource("dynamodb").create_table(TableName="synthetic-browse",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST")
        module.table().put_item(Item={"pk": "v1#catalog", "sk": "ready"})
        yield module


def asset(i=1, kind="video-comparison", mime="video/mp4"):
    key = f"games/example/assets/take-{i}/original/take.mp4"
    return {"key": key, "name": "take.mp4", "contentType": mime, "kind": kind,
            "metadata": {}, "sourceKeys": [], "lastModified": "2026-01-01", "size": 1}


def test_indexed_query_has_no_source_reads_and_scoped_pages(index, monkeypatch):
    library = importlib.import_module("asset_library")
    current = asset()
    monkeypatch.setattr(library, "describe", lambda *_: current)
    for i in range(103):
        current = asset(i)
        index.refresh(None, current["key"])
    monkeypatch.setattr(library, "describe", lambda *_: pytest.fail("Browsing must not read S3"))
    first = index.page("example", "videos")
    assert len(first["assets"]) == 100
    assert len(index.page("example", "videos", first["cursor"])["assets"]) == 3
    assert index.page("example", "audio")["assets"] == []
    for game, section in [("other", "videos"), ("example", "all")]:
        with pytest.raises(ValueError):
            index.page(game, section, first["cursor"])
    with pytest.raises(ValueError):
        index.page("example", "videos", "broken")


def test_refresh_changes_all_memberships_and_preserves_lineage(index, monkeypatch):
    library = importlib.import_module("asset_library")
    current = asset()
    current["sourceKeys"] = ["games/example/assets/source/original/text.json"]
    monkeypatch.setattr(library, "describe", lambda *_: current)
    index.refresh(None, current["key"])
    assert index.page("example", "videos")["assets"] == [current]
    current = {**current, "name": "take.json", "contentType": "application/json", "kind": "corrected-transcript"}
    index.refresh(None, current["key"])
    assert index.page("example", "videos")["assets"] == []
    assert index.page("example", "transcripts")["assets"] == [current]
    assert index.page("example", "all")["assets"] == [current]


def test_event_uses_current_asset_and_ignores_unrelated_objects(index, monkeypatch):
    import sys
    calls = []
    media = SimpleNamespace(BUCKET_NAME="test-bucket", s3=SimpleNamespace(reference_for=lambda _: asset()["key"]))
    monkeypatch.setitem(sys.modules, "index", media)
    monkeypatch.setattr(index, "refresh", lambda m, ref: calls.append(ref))
    index.event_handler({"detail": {"bucket": {"name": "test-bucket"}, "object": {"key": "games/example/content/take.mp4"}}}, None)
    index.event_handler({"detail": {"bucket": {"name": "test-bucket"}, "object": {"key": "games/example/catalog/assets/a.json"}}}, None)
    assert calls == [asset()["key"]]


def test_backfill_dry_run_apply_verify(index, monkeypatch):
    import sys
    monkeypatch.setenv("ASSET_MIGRATORS", "example-owner")
    current = asset()
    library = importlib.import_module("asset_library")
    monkeypatch.setattr(library, "describe", lambda *_: current)
    media = SimpleNamespace(BUCKET_NAME="test-bucket", _valid_slug=lambda v: v == "example",
        _response=lambda status, body: {"statusCode": status, "body": body},
        raw_s3=SimpleNamespace(list_objects_v2=lambda **_: {"Contents": [{"Key": current["key"].replace("/assets/", "/catalog/assets/") + ".json"}]}))
    monkeypatch.setitem(sys.modules, "index", media)
    event = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "synthetic", "cognito:username": "example-owner"}}}}}
    for mode, expected in [("dry-run", "ready"), ("verify", "mismatch"), ("apply", "indexed"), ("verify", "verified")]:
        result = index.rebuild_handler({**event, "body": json.dumps({"gameId": "example", "mode": mode})}, None)
        assert result["body"]["records"][0]["status"] == expected
    assert index.rebuild_handler({"body": "{}"}, None)["statusCode"] == 403


def test_initial_cutover_fails_closed(index):
    index.table().delete_item(Key={"pk": "v1#catalog", "sk": "ready"})
    with pytest.raises(index.IndexNotReady):
        index.page("example", "videos")


def test_overlapping_source_read_cannot_replace_newer_commit(index, monkeypatch):
    library = importlib.import_module("asset_library")
    current = asset()
    updated = {**current, "kind": "corrected-transcript", "name": "x.json", "contentType": "application/json"}
    def overlap(*_):
        monkeypatch.setattr(library, "describe", lambda *_: updated)
        index.refresh(None, current["key"])
        return current
    monkeypatch.setattr(library, "describe", overlap)
    with pytest.raises(RuntimeError, match="Concurrent index update"):
        index.refresh(None, current["key"])
    assert index.page("example", "videos")["assets"] == []
    assert index.page("example", "transcripts")["assets"] == [updated]


def test_chunks_and_exports_dont_become_duplicate_listing_cards(index, monkeypatch):
    library = importlib.import_module("asset_library")
    assert index.sections({**asset(), "name": "part-0001.flac", "kind": "recording", "contentType": "audio/flac"}) == {"all"}
    current = {**asset(), "key": "games/example/assets/text/original/raw.md", "name": "raw.md", "kind": "raw-transcript", "contentType": "text/markdown"}
    monkeypatch.setattr(library, "describe", lambda *_: current)
    index.refresh(None, current["key"])
    assert len(index.page("example", "transcripts")["assets"]) == 1
    current = {**current, "key": current["key"][:-3] + ".json", "name": "raw.json", "contentType": "application/json"}
    index.refresh(None, current["key"])
    assert index.page("example", "transcripts")["assets"] == [current]
