"""Synthetic, versioned S3 round trips; never touches private game files or AWS."""

import base64
import hashlib
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws
import pytest


@pytest.fixture
def store(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "infra/lambda/media-api"))
    for name in ("asset_storage", "storage_layout", "storage_migrations"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    storage = importlib.import_module("asset_storage")
    layout = importlib.import_module("storage_layout")
    with mock_aws():
        raw = boto3.client("s3", region_name="us-west-2")
        bucket = "synthetic-panther-storage"
        raw.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": "us-west-2"})
        raw.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        yield storage.Storage(raw, bucket), layout


def metadata(**extra):
    return {"schemaVersion": 1, "title": "Synthetic fixture", "category": "reference",
            "characterIds": [], "tags": [], "sourceKeys": [],
            "extra": {"relationshipRole": "finished"}, **extra}


REF = "games/example/assets/source-v1/original/source.flac"
DATE = "2020-01-01T00:00:00+00:00"


@pytest.mark.parametrize("kind,details,path", [
    ("recording", metadata(sessionId="night-one"), "sessions/night-one/audio/source"),
    ("recording-playback", metadata(sessionId="night-one"), "sessions/night-one/audio/playback"),
    ("raw-transcript", metadata(sessionId="night-one"), "sessions/night-one/transcripts/raw"),
    ("corrected-transcript", metadata(sessionId="night-one"), "sessions/night-one/transcripts/corrected"),
    ("novel-chapter", metadata(sessionId="night-one"), "sessions/night-one/novel/chapters"),
    ("portrait", metadata(characterIds=["captain"], sessionId="night-one"), "characters/captain/portraits"),
    ("model-3d", metadata(characterIds=["captain"]), "characters/captain/models"),
    ("portrait", metadata(characterIds=["captain", "sailor"]), "library/portraits"),
    ("map", metadata(), "library/maps"),
    ("holographic-scene", metadata(), "library/media/holographic-scene"),
    ("novel-proof", metadata(sessionId="night-one", extra={"relationshipRole": "intermediate", "jobId": "job-one"}), "sessions/night-one/workflows/job-one/novel-proof"),
])
def test_deterministic_extensible_locations(store, kind, details, path):
    _, layout = store
    assert layout.location(REF, kind, details) == f"games/example/content/{path}/source-v1/source.flac"


@pytest.mark.parametrize("details", [
    metadata(sessionId="../other"), metadata(characterIds=["UPPER"]),
    metadata(characterIds=["captain", "captain"]), metadata(extra={}),
    metadata(extra={"relationshipRole": "intermediate", "jobId": "../escape"}),
])
def test_invalid_routing_is_rejected(store, details):
    _, layout = store
    with pytest.raises(ValueError):
        layout.location(REF, "novel-proof", details)


def test_indexed_upload_preserves_identity_and_no_overwrite(store):
    storage, _ = store
    digest = base64.b64encode(hashlib.sha256(b"audio").digest()).decode()
    physical = storage.reserve(REF, "recording", metadata(sessionId="night-one"), digest, 5, DATE)
    assert storage.resolve(REF) == physical
    assert storage.reference_for(physical) == REF
    assert storage.reserve(REF, "recording", metadata(sessionId="night-one"), digest, 5, DATE) == physical
    with pytest.raises(ValueError):
        storage.reserve(REF, "recording", metadata(sessionId="night-two"), digest, 5, DATE)
    # A reservation is not a finished upload and is omitted from the normal catalog.
    args = {"Bucket": storage.bucket, "Prefix": "games/example/assets/", "MaxKeys": 25}
    assert not storage.list_objects_v2(**args)["Contents"]
    storage.raw.put_object(Bucket=storage.bucket, Key=physical, Body=b"audio", IfNoneMatch="*",
                           ChecksumSHA256=digest)
    assert storage.get_object(Bucket=storage.bucket, Key=REF)["Body"].read() == b"audio"
    listing = storage.list_objects_v2(**args)["Contents"]
    assert [o["Key"] for o in listing] == [REF]
    assert listing[0]["Size"] == 5 and listing[0]["LastModified"].isoformat() == DATE
    url = storage.generate_presigned_url("get_object", Params={"Bucket": storage.bucket, "Key": REF}, ExpiresIn=60)
    assert "/content/sessions/night-one/audio/source/" in url
    assert "/assets/source-v1/original/" not in url


def test_no_legacy_payload_fallback_or_cross_game_locator(store):
    storage, layout = store
    storage.raw.put_object(Bucket=storage.bucket, Key=REF, Body=b"old file")
    with pytest.raises(ClientError):
        storage.get_object(Bucket=storage.bucket, Key=REF)
    storage.raw.put_object(Bucket=storage.bucket, Key=layout.index_key(REF), Body=json.dumps({
        "schemaVersion": 1, "layoutVersion": 2, "assetRef": REF,
        "storageKey": "games/another/content/library/stolen.wav"}).encode())
    with pytest.raises(ValueError):
        storage.resolve(REF)


def test_catalog_pagination_delimiters_and_related_representations(store):
    storage, _ = store
    refs = [REF, "games/example/assets/source-v1/derived/web/source.flac",
            "games/example/assets/source-v1/metadata/source.flac"]
    for ref in refs:
        physical = storage.reserve(ref, "recording", metadata(), "digest", 1, DATE)
        storage.raw.put_object(Bucket=storage.bucket, Key=physical, Body=b"a")
        assert storage.reference_for(physical) == ref
    pages = list(storage.get_paginator("list_objects_v2").paginate(
        Bucket=storage.bucket, Prefix="games/example/assets/", MaxKeys=1))
    assert len(pages) == 3
    assert {p["Contents"][0]["Key"] for p in pages} == set(refs)
    folders = storage.list_objects_v2(Bucket=storage.bucket, Prefix="games/example/assets/", Delimiter="/")
    assert folders["CommonPrefixes"] == [{"Prefix": "games/example/assets/source-v1/"}]


def test_physical_copy_then_cutover_then_recoverable_retirement(store, monkeypatch):
    storage, layout = store
    raw, bucket = storage.raw, storage.bucket
    blob = b"Unchanged source, exact references and transcription evidence."
    source = raw.put_object(Bucket=bucket, Key=REF, Body=blob, ChecksumAlgorithm="SHA256",
                            ContentType="audio/flac", Metadata={"uploaded-by": "original-person"})
    # Use the actual API validator, rather than accepting a weaker migration test contract.
    media = SimpleNamespace(raw_s3=raw, BUCKET_NAME=bucket, STORAGE_MODE="prepare",
                            _valid_key=lambda key: isinstance(key, str) and key.startswith("games/") and ".." not in key,
                            _valid_slug=lambda value: isinstance(value, str) and layout.SLUG.fullmatch(value),
                            _asset_created_at=lambda head: head["LastModified"])
    monkeypatch.setitem(sys.modules, "index", media)
    monkeypatch.delitem(sys.modules, "asset_migrations", raising=False)
    migrations = importlib.import_module("storage_migrations")
    plan = {"schemaVersion": 1, "key": REF, "expectedVersionId": source["VersionId"],
            "kind": "recording", "metadata": metadata(sessionId="night-one"), "reason": "Synthetic layout migration"}
    claims = {"sub": "owner-id"}
    dry = migrations.handle(plan, claims, media)
    assert dry["status"] == "ready"
    assert raw.list_objects_v2(Bucket=bucket)["KeyCount"] == 1
    copied = migrations.handle({**plan, "dryRun": False}, claims, media)
    assert copied["status"] == "copied"
    assert migrations.handle({**plan, "dryRun": False}, claims, media)["status"] == "already-copied"
    assert storage.get_object(Bucket=bucket, Key=REF)["Body"].read() == blob
    assert raw.get_object(Bucket=bucket, Key=REF)["Body"].read() == blob
    assert storage.head_object(Bucket=bucket, Key=REF)["Metadata"]["uploaded-by"] == "original-person"
    with pytest.raises(ValueError, match="indexed readers"):
        migrations.handle({**plan, "action": "retire", "dryRun": False}, claims, media)
    media.STORAGE_MODE = "indexed"
    retired = migrations.handle({**plan, "action": "retire", "dryRun": False}, claims, media)
    assert retired["status"] == "retired"
    assert storage.get_object(Bucket=bucket, Key=REF)["Body"].read() == blob
    assert raw.get_object(Bucket=bucket, Key=REF, VersionId=source["VersionId"])["Body"].read() == blob
    assert migrations.handle({**plan, "action": "retire", "dryRun": False}, claims, media)["status"] == "already-retired"


def test_stale_version_and_destination_collision_never_overwrite(store, monkeypatch):
    storage, layout = store
    raw, bucket = storage.raw, storage.bucket
    source = raw.put_object(Bucket=bucket, Key=REF, Body=b"source")
    media = SimpleNamespace(raw_s3=raw, BUCKET_NAME=bucket, STORAGE_MODE="prepare",
                            _valid_key=lambda key: isinstance(key, str) and key.startswith("games/") and ".." not in key,
                            _valid_slug=lambda value: isinstance(value, str) and layout.SLUG.fullmatch(value),
                            _asset_created_at=lambda head: head["LastModified"])
    monkeypatch.setitem(sys.modules, "index", media)
    monkeypatch.delitem(sys.modules, "asset_migrations", raising=False)
    migrations = importlib.import_module("storage_migrations")
    plan = {"schemaVersion": 1, "key": REF, "expectedVersionId": "stale",
            "kind": "recording", "metadata": metadata(), "reason": "Synthetic layout migration", "dryRun": False}
    with pytest.raises(ValueError, match="Source version changed"):
        migrations.handle(plan, {"sub": "owner"}, media)
    plan["expectedVersionId"] = source["VersionId"]
    target = layout.location(REF, "recording", plan["metadata"])
    raw.put_object(Bucket=bucket, Key=target, Body=b"unrelated")
    with pytest.raises(ValueError, match="Destination collision"):
        migrations.handle(plan, {"sub": "owner"}, media)
    assert raw.get_object(Bucket=bucket, Key=target)["Body"].read() == b"unrelated"
