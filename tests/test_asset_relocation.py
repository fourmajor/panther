"""Versioned synthetic round trips for the temporary indexed relocation capability."""
import base64
import copy
import hashlib
import importlib
import json
import sys
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError
from test_asset_storage import store, metadata, DATE


@pytest.fixture
def relocation(store, monkeypatch):
    storage, layout = store
    raw, bucket = storage.raw, storage.bucket
    ref = "games/example/assets/source-v1/original/front.png"
    details = metadata()
    details["extra"]["jobId"] = "example-job"
    blob = b"Exact original inspection pixels"
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode()
    physical = storage.reserve(ref, "image", details, digest, len(blob), DATE)
    source = raw.put_object(Bucket=bucket, Key=physical, Body=blob, ChecksumAlgorithm="SHA256",
        ContentType="image/png", CacheControl="private,max-age=60", Tagging="example=retained",
        Metadata={"uploaded-by": "original-actor", "kind": "image",
                  "panther": base64.b64encode(json.dumps(details).encode()).decode()})
    media = SimpleNamespace(raw_s3=raw, s3=storage, BUCKET_NAME=bucket,
        _valid_key=lambda key: isinstance(key, str) and key.startswith("games/") and ".." not in key,
        _valid_slug=lambda value: isinstance(value, str) and layout.SLUG.fullmatch(value))
    monkeypatch.setitem(sys.modules, "index", media)
    for name in ("asset_migrations", "asset_relocation"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module("asset_relocation")
    after = copy.deepcopy(details)
    after["extra"]["relationshipRole"] = "intermediate"
    plan = {"schemaVersion": 1, "key": ref, "kind": "image", "metadata": after,
            "expectedVersionId": source["VersionId"], "reason": "Synthetic inspected role migration"}
    monkeypatch.setenv("ASSET_RELOCATION_IDS", json.dumps([module.identity(plan)]))
    return module, storage, plan, physical, blob


def test_relocation_preserves_bytes_tags_headers_stable_identity_and_retained_versions(relocation):
    module, storage, plan, source, blob = relocation
    raw, bucket = storage.raw, storage.bucket
    assert module.handle(plan, {"sub": "synthetic-owner"})["status"] == "ready"
    assert storage.resolve(plan["key"]) == source
    applied = {**plan, "dryRun": False}
    assert module.handle(applied, {"sub": "synthetic-owner"})["status"] == "copied"
    target = storage.resolve(plan["key"])
    assert "/workflows/example-job/image/" in target
    assert storage.get_object(Bucket=bucket, Key=plan["key"])["Body"].read() == blob
    head = storage.head_object(Bucket=bucket, Key=plan["key"])
    assert head["ContentType"] == "image/png" and head["CacheControl"] == "private,max-age=60"
    assert head["Metadata"]["uploaded-by"] == "original-actor"
    assert raw.get_object_tagging(Bucket=bucket, Key=target)["TagSet"] == [{"Key": "example", "Value": "retained"}]
    assert module.handle(applied, {"sub": "synthetic-owner"})["status"] == "already-copied"
    assert module.handle({**plan, "action": "verify"}, {})["status"] == "verified"
    assert module.handle({**plan, "action": "retire"}, {})["status"] == "ready-to-retire"
    retired = module.handle({**applied, "action": "retire"}, {})
    assert retired["status"] == "retired"
    assert raw.head_object(Bucket=bucket, Key=source, VersionId=plan["expectedVersionId"])["ContentLength"] == len(blob)
    assert storage.get_object(Bucket=bucket, Key=plan["key"])["Body"].read() == blob
    assert module.handle({**applied, "action": "retire"}, {})["status"] == "already-retired"


def test_copy_checkpoint_recovers_without_overwriting_destination(relocation, monkeypatch):
    module, storage, plan, source, blob = relocation
    put = storage.raw.put_object
    monkeypatch.setattr(storage.raw, "put_object", lambda **_: (_ for _ in ()).throw(RuntimeError("Interrupted cutover")))
    with pytest.raises(RuntimeError):
        module.handle({**plan, "dryRun": False}, {"sub": "owner"})
    assert storage.resolve(plan["key"]) == source
    monkeypatch.setattr(storage.raw, "put_object", put)
    assert module.handle({**plan, "dryRun": False}, {"sub": "owner"})["status"] == "copied"
    assert storage.get_object(Bucket=storage.bucket, Key=plan["key"])["Body"].read() == blob


def test_exact_plan_and_destination_collisions_fail_closed(relocation, monkeypatch):
    module, storage, plan, source, _ = relocation
    with pytest.raises(ValueError, match="exact pinned plan"):
        module.handle({**plan, "reason": "Unreviewed"}, {})
    monkeypatch.setenv("ASSET_RELOCATION_IDS", "[]")
    with pytest.raises(ValueError, match="exact pinned plan"):
        module.handle(plan, {})
    monkeypatch.setenv("ASSET_RELOCATION_IDS", json.dumps([module.identity(plan)]))
    target = importlib.import_module("storage_layout").location(plan["key"], plan["kind"], plan["metadata"])
    storage.raw.put_object(Bucket=storage.bucket, Key=target, Body=b"Unrelated")
    with pytest.raises(ValueError):
        module.handle({**plan, "dryRun": False}, {})
    assert storage.resolve(plan["key"]) == source


def test_changed_source_checksum_locator_or_target_blocks_cutover_and_retirement(relocation, monkeypatch):
    module, storage, plan, source, _ = relocation
    storage.raw.put_object(Bucket=storage.bucket, Key=source, Body=b"Unexpected source", ChecksumAlgorithm="SHA256")
    with pytest.raises(ValueError, match="Source version changed"):
        module.handle({**plan, "dryRun": False}, {})


def test_conditional_locator_conflict_retains_original_and_cannot_retire(relocation, monkeypatch):
    module, storage, plan, source, blob = relocation
    def conflict(**_):
        raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
    monkeypatch.setattr(storage.raw, "put_object", conflict)
    with pytest.raises(ClientError):
        module.handle({**plan, "dryRun": False}, {"sub": "owner"})
    assert storage.resolve(plan["key"]) == source
    with pytest.raises(ValueError, match="distinct, verified"):
        module.handle({**plan, "action": "retire", "dryRun": False}, {})


def test_post_cutover_revision_refuses_retirement(relocation):
    module, storage, plan, source, _ = relocation
    applied = {**plan, "dryRun": False}
    module.handle(applied, {"sub": "owner"})
    target = storage.resolve(plan["key"])
    storage.raw.put_object(Bucket=storage.bucket, Key=target, Body=b"Unreviewed change", ChecksumAlgorithm="SHA256")
    with pytest.raises(ValueError):
        module.handle({**applied, "action": "retire"}, {})
    assert storage.raw.head_object(Bucket=storage.bucket, Key=source)["VersionId"] == plan["expectedVersionId"]
