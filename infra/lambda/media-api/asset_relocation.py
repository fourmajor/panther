"""Temporary, exact-plan relocation of already indexed layout-2 assets.

No alternate reader mode, arbitrary destination, replacement bytes or version deletion.
The retained locator revisions are the recovery journal. Disable the CDK capability after
all-game verification and recoverable source retirement.
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os

from botocore.exceptions import ClientError
import asset_migrations
from asset_storage import missing
import index as media
from migration_lock import exclusive
import storage_layout


def identity(request):
    return hashlib.sha256(json.dumps({k: v for k, v in request.items()
        if k not in {"dryRun", "action"}}, sort_keys=True, allow_nan=False).encode()).hexdigest()


def head_or_none(raw, bucket, key):
    try:
        return raw.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
    except ClientError as error:
        if missing(error):
            return None
        raise


def verify(head, entry, migration_id=None):
    if (not head or head["ContentLength"] != entry["size"]
            or head.get("ChecksumSHA256") != entry["sha256"]
            or head.get("ChecksumType") == "COMPOSITE"):
        raise ValueError("Full-file checksum/size verification failed; original retained")
    if migration_id and head.get("Metadata", {}).get("relocation-id") != migration_id:
        raise ValueError("Destination collision or unreviewed revision; original retained")


def handle(body, claims):
    action = body.get("action", "copy")
    if action not in {"copy", "verify", "retire"}:
        raise ValueError("Invalid relocation action")
    request = {k: v for k, v in body.items() if k != "action"}
    key, encoded = asset_migrations.validate(request)
    migration_id = identity(request)
    allowed = json.loads(os.environ.get("ASSET_RELOCATION_IDS", "[]"))
    if migration_id not in allowed:
        raise ValueError("This exact pinned plan is not enabled by CDK")
    raw, bucket = media.raw_s3, media.BUCKET_NAME
    locator_key = storage_layout.index_key(key)
    locator_reply = raw.get_object(Bucket=bucket, Key=locator_key)
    locator_etag = locator_reply["ETag"]
    with locator_reply["Body"] as stream:
        encoded_locator = stream.read(8193)
    if len(encoded_locator) > 8192:
        raise ValueError("Oversized location catalog")
    entry = media.s3.locator(key)  # Validate the canonical entry before any write.
    if json.loads(encoded_locator) != entry:
        raise ValueError("Locator changed during inspection")
    target = storage_layout.location(key, body["kind"], body["metadata"])
    audit = entry.get("relocation")
    if audit:
        if (audit.get("id") != migration_id or entry["storageKey"] != target
                or audit.get("sourceVersionId") != body["expectedVersionId"]):
            raise ValueError("Unrelated relocation history; inspect before planning again")
        destination = head_or_none(raw, bucket, target)
        verify(destination, entry, migration_id)
        if (destination["VersionId"] != audit["targetVersionId"]
                or destination["Metadata"].get("panther") != encoded
                or destination["Metadata"].get("kind") != body["kind"]):
            raise ValueError("Relocated asset changed; retirement refused")
        if action in {"copy", "verify"}:
            return {"status": "already-copied" if action == "copy" else "verified",
                    "key": key, "storageKey": target, "migrationId": migration_id}
        source = head_or_none(raw, bucket, audit["sourceStorageKey"])
        # Prove the original exact version survives, even after a delete marker.
        retained = raw.head_object(Bucket=bucket, Key=audit["sourceStorageKey"],
            VersionId=audit["sourceVersionId"], ChecksumMode="ENABLED")
        verify(retained, entry)
        if not source:
            return {"status": "already-retired", "key": key, "migrationId": migration_id}
        if source["VersionId"] != audit["sourceVersionId"]:
            raise ValueError("Source changed; retirement refused")
        if body.get("dryRun", True):
            return {"status": "ready-to-retire", "key": key, "migrationId": migration_id}
        deletion = raw.delete_object(Bucket=bucket, Key=audit["sourceStorageKey"], IfMatch=source["ETag"])
        return {"status": "retired", "key": key, "migrationId": migration_id,
                "deleteMarkerVersionId": deletion["VersionId"]}
    if action != "copy" or target == entry["storageKey"]:
        raise ValueError("A distinct, verified relocation is required")
    source = raw.head_object(Bucket=bucket, Key=entry["storageKey"], ChecksumMode="ENABLED")
    if (source.get("VersionId") in {None, "null"}
            or locator_reply.get("VersionId") in {None, "null"}
            or source["VersionId"] != body["expectedVersionId"]):
        raise ValueError("Source version changed; inspect and re-plan")
    verify(source, entry)
    old = source.get("Metadata", {})
    previous = json.loads(base64.b64decode(old.get("panther", "e30="), validate=True))
    if not set(previous.get("sourceKeys", [])) <= set(body["metadata"]["sourceKeys"]):
        raise ValueError("All existing compact lineage must be retained")
    for input_key in body["metadata"]["sourceKeys"]:
        media.s3.head_object(Bucket=bucket, Key=input_key)
    updated = {**old, "kind": body["kind"], "panther": encoded,
               "asset-created-at": entry["createdAt"], "relocation-id": migration_id}
    if sum(len(k.encode()) + len(v.encode()) for k, v in updated.items()) > 2048:
        raise ValueError("Relocation metadata exceeds storage limit")
    destination = head_or_none(raw, bucket, target)
    if destination:
        verify(destination, entry, migration_id)
        if destination["Metadata"] != updated:
            raise ValueError("Destination metadata differs; no overwrite permitted")
    result = {"status": "ready", "key": key, "storageKey": target, "migrationId": migration_id}
    if body.get("dryRun", True):
        return result
    if not destination:
        headers = {field: source[field] for field in ("ContentType", "CacheControl", "ContentDisposition",
            "ContentEncoding", "ContentLanguage", "Expires", "WebsiteRedirectLocation", "StorageClass") if field in source}
        raw.copy_object(Bucket=bucket, Key=target,
            CopySource={"Bucket": bucket, "Key": entry["storageKey"], "VersionId": source["VersionId"]},
            CopySourceIfMatch=source["ETag"], IfNoneMatch="*", ChecksumAlgorithm="SHA256",
            MetadataDirective="REPLACE", TaggingDirective="COPY", Metadata=updated, **headers)
        destination = head_or_none(raw, bucket, target)
    verify(destination, entry, migration_id)
    if destination.get("VersionId") in {None, "null"} or destination["Metadata"] != updated:
        raise ValueError("Copied metadata/version differs; original retained")
    source_tags = raw.get_object_tagging(Bucket=bucket, Key=entry["storageKey"], VersionId=source["VersionId"])["TagSet"]
    target_tags = raw.get_object_tagging(Bucket=bucket, Key=target, VersionId=destination["VersionId"])["TagSet"]
    if sorted(source_tags, key=lambda t: t["Key"]) != sorted(target_tags, key=lambda t: t["Key"]):
        raise ValueError("Copied tags differ; original retained")
    audit = {"id": migration_id, "sourceStorageKey": entry["storageKey"],
             "sourceVersionId": source["VersionId"], "targetVersionId": destination["VersionId"],
             "previousLocatorVersionId": locator_reply.get("VersionId"), "actor": claims["sub"],
             "at": datetime.now(timezone.utc).isoformat(), "reason": body["reason"]}
    new_locator = json.dumps({**entry, "storageKey": target, "relocation": audit}).encode()
    if len(new_locator) > 8192:
        raise ValueError("Relocation audit exceeds location catalog limit")
    raw.put_object(Bucket=bucket, Key=locator_key, Body=new_locator,
                   ContentType="application/json", IfMatch=locator_etag)
    return {**result, "status": "copied", "versionId": destination["VersionId"]}


def handler(event, _context):
    from access_policy import authorized
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "ASSET_MIGRATORS"):
        return media._response(403, {"error": "Owner sign-in required"})
    try:
        with exclusive() as lock:
            try:
                body = event.get("body", "")
                if event.get("isBase64Encoded"):
                    body = base64.b64decode(body, validate=True).decode()
                if len(body) > 32768:
                    raise ValueError("Oversized relocation request")
                parsed = json.loads(body)
                if not isinstance(parsed, dict):
                    raise ValueError("Relocation request must be an object")
                result = media._response(200, handle(parsed, claims))
            except (ValueError, TypeError, KeyError, UnicodeError) as error:
                result = media._response(400, {"error": str(error)})
            lock["complete"] = True
            return result
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        return media._response(409 if code in {"PreconditionFailed", "ConditionalRequestConflict"} else 503,
                               {"error": "Relocation conflicted or unavailable; inspect retained evidence before retrying"})
