"""Historical layout-v2 migration engine. Not deployed or exposed by the current API.

Kept with tests as migration evidence, not an alternate storage mode. Recovery or a future
layout upgrade requires a new reviewed CDK/API migration and a freshly audited private plan.
"""

import base64
from datetime import datetime, timezone
import hashlib
import json

from botocore.exceptions import ClientError
from asset_storage import Storage, missing
import storage_layout


def handle(body, claims, media):
    import asset_migrations
    action = body.get("action", "copy")
    if action not in {"copy", "retire"}:
        raise ValueError("Invalid storage migration action")
    request = {k: v for k, v in body.items() if k != "action"}
    key, encoded = asset_migrations.validate(request)
    target = storage_layout.location(key, body["kind"], body["metadata"])
    raw, bucket = media.raw_s3, media.BUCKET_NAME
    storage = Storage(raw, bucket)
    migration_id = hashlib.sha256(json.dumps({k: v for k, v in request.items() if k != "dryRun"},
                                            sort_keys=True, allow_nan=False).encode()).hexdigest()
    dry_run = body.get("dryRun", True)
    if media.STORAGE_MODE not in ({"prepare"} if action == "copy" else {"indexed"}):
        raise ValueError("Copy requires the upload-freeze deployment; retirement requires indexed readers")
    index = None
    try:
        index = storage.locator(key)
    except ClientError as error:
        if not missing(error):
            raise
    if index and (index.get("migrationId") != migration_id or index["storageKey"] != target):
        raise ValueError("An unrelated asset locator already exists; inspect the conflict")
    if action == "retire" or index:
        if not index:
            raise ValueError("Verified asset location required before retiring the old physical key")
        target_head = raw.head_object(Bucket=bucket, Key=target, ChecksumMode="ENABLED")
        if (target_head["ContentLength"] != index["size"]
                or target_head.get("ChecksumSHA256") != index["sha256"]):
            raise ValueError("Organized payload failed checksum verification")
        if action == "copy":
            return {"status": "already-copied", "key": key, "storageKey": target, "migrationId": migration_id}
    try:
        head = raw.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
    except ClientError as error:
        if action == "retire" and index and missing(error):
            return {"status": "already-retired", "key": key, "storageKey": target}
        raise
    version = head.get("VersionId")
    if not version or version == "null" or version != body["expectedVersionId"]:
        raise ValueError("Source version changed or storage is unversioned; inspect and re-plan")
    result = {"status": "ready", "key": key, "storageKey": target, "migrationId": migration_id,
              "previousVersionId": version, "size": head["ContentLength"], "layoutVersion": 2}
    if action == "retire":
        if not dry_run:
            # No VersionId: add a recoverable delete marker, never erase original versions.
            deletion = raw.delete_object(Bucket=bucket, Key=key, IfMatch=head["ETag"])
            result.update(status="retired", deleteMarkerVersionId=deletion["VersionId"])
        return result
    old = head.get("Metadata", {})
    previous = json.loads(base64.b64decode(old.get("panther", "e30="), validate=True))
    if not set(previous.get("sourceKeys", [])) <= set(body["metadata"]["sourceKeys"]):
        raise ValueError("Storage migration must retain all existing compact source references")
    for source in body["metadata"]["sourceKeys"]:
        raw.head_object(Bucket=bucket, Key=source)
    updated = {**old, "kind": body["kind"], "panther": encoded,
               "asset-created-at": media._asset_created_at(head).isoformat(),
               "storage-migration-id": migration_id}
    if sum(len(k.encode()) + len(v.encode()) for k, v in updated.items()) > 2048:
        raise ValueError("Metadata exceeds S3's limit")
    existing_target = None
    try:
        existing_target = raw.head_object(Bucket=bucket, Key=target, ChecksumMode="ENABLED")
    except ClientError as error:
        if not missing(error):
            raise
    if existing_target and existing_target.get("Metadata", {}).get("storage-migration-id") != migration_id:
        raise ValueError("Destination collision; no file was overwritten")
    if dry_run:
        return result
    if not existing_target:
        headers = {field: head[field] for field in ("ContentType", "CacheControl", "ContentDisposition",
                   "ContentEncoding", "ContentLanguage", "Expires", "StorageClass") if field in head}
        raw.copy_object(Bucket=bucket, Key=target,
                        CopySource={"Bucket": bucket, "Key": key, "VersionId": version},
                        CopySourceIfMatch=head["ETag"], ChecksumAlgorithm="SHA256",
                        MetadataDirective="REPLACE", TaggingDirective="COPY", Metadata=updated, **headers)
    copied = raw.head_object(Bucket=bucket, Key=target, ChecksumMode="ENABLED")
    digest = copied.get("ChecksumSHA256")
    if (copied["ContentLength"] != head["ContentLength"] or not digest
            or (head.get("ChecksumSHA256") and head.get("ChecksumType") != "COMPOSITE"
                and head["ChecksumSHA256"] != digest)):
        raise ValueError("Copied object failed verification; original retained")
    entry = {"schemaVersion": 1, "layoutVersion": 2, "assetRef": key, "storageKey": target,
             "size": copied["ContentLength"], "sha256": digest,
             "createdAt": updated["asset-created-at"], "migrationId": migration_id,
             "previousVersionId": version, "actor": claims["sub"],
             "migratedAt": datetime.now(timezone.utc).isoformat(), "reason": body["reason"]}
    raw.put_object(Bucket=bucket, Key=storage_layout.index_key(key), Body=json.dumps(entry).encode(),
                   ContentType="application/json", IfNoneMatch="*")
    return {**result, "status": "copied", "sha256": digest, "versionId": copied["VersionId"]}
