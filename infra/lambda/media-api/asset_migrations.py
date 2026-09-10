"""Serialized, version-guarded metadata migrations; never accepts replacement file bytes."""

import base64
from datetime import datetime, timezone
import hashlib
import json
import re

from botocore.exceptions import ClientError
import index as media
import asset_metadata


def validate(body):
    if not isinstance(body, dict) or set(body) - {
        "schemaVersion", "key", "expectedVersionId", "kind", "metadata", "reason", "dryRun"
    }:
        raise ValueError("Invalid migration fields")
    key = body.get("key")
    if (type(body.get("schemaVersion")) is not int or body["schemaVersion"] != 1 or not media._valid_key(key)
            or not re.fullmatch(r"games/[a-z0-9-]+/assets/[a-z0-9-]+/(original|derived/[^/]+|metadata)/[^/]+", key)
            or "\\" in key):
        raise ValueError("Migration requires an existing game asset key")
    if not isinstance(body.get("expectedVersionId"), str) or not 1 <= len(body["expectedVersionId"]) <= 1024:
        raise ValueError("Inspect the asset's exact version before migration")
    if not media._valid_slug(body.get("kind")) or len(body["kind"]) > 96:
        raise ValueError("Invalid kind")
    if not isinstance(body.get("reason"), str) or not 1 <= len(body["reason"]) <= 500:
        raise ValueError("A migration reason is required")
    if type(body.get("dryRun", True)) is not bool:
        raise ValueError("Invalid dryRun")
    details = body.get("metadata")
    if not isinstance(details, dict) or set(details) - {
        "schemaVersion", "title", "description", "category", "characterIds", "sessionId", "tags", "sourceKeys", "extra"
    } or type(details.get("schemaVersion")) is not int or details["schemaVersion"] != 1:
        raise ValueError("Current metadata schemaVersion 1 is required")
    if not isinstance(details.get("title"), str) or not 1 <= len(details["title"]) <= 500:
        raise ValueError("A meaningful title is required")
    if "description" in details and (not isinstance(details["description"], str) or len(details["description"]) > 500):
        raise ValueError("Invalid description")
    if details.get("category") not in {"canonical-source", "grounded-adaptation", "creative-reimagining", "playful-derivative", "reference", "unclassified"}:
        raise ValueError("Invalid category")
    for field in ("tags", "characterIds"):
        values = details.get(field)
        if not isinstance(values, list) or len(values) > 20 or not all(media._valid_slug(v) and len(v) <= 96 for v in values):
            raise ValueError(f"Explicit valid {field} required")
    if "sessionId" in details and (not media._valid_slug(details["sessionId"]) or len(details["sessionId"]) > 96):
        raise ValueError("Invalid sessionId")
    sources = details.get("sourceKeys")
    game_prefix = "/".join(key.split("/")[:2]) + "/"
    if (not isinstance(sources, list) or len(sources) > 20
            or not all(media._valid_key(v) and v.startswith(game_prefix) and v != key for v in sources)):
        raise ValueError("Explicit same-game sourceKeys required; keep large provenance in its document")
    if not isinstance(details.get("extra"), dict):
        raise ValueError("Explicit extra metadata required")
    if details["extra"].get("relationshipRole") not in {"finished", "intermediate"}:
        raise ValueError("Explicit finished/intermediate relationshipRole required")
    if (asset_metadata.internal(body["kind"]) and not (body["kind"] == "recording-manifest" and key.endswith("/recording.json"))
            and details["extra"]["relationshipRole"] != "intermediate"):
        raise ValueError("Internal workflow artifacts must remain intermediate")
    encoded = base64.b64encode(json.dumps(details, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()).decode()
    return key, encoded


def handler(event, _context):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if claims.get("cognito:username") != "stu" or not claims.get("sub"):
        return media._response(403, {"error": "Owner sign-in required for asset migrations"})
    try:
        raw = event.get("body", "")
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw, validate=True).decode()
        if len(raw) > 32 * 1024:
            raise ValueError("Migration request too large")
        body = json.loads(raw)
        key, encoded = validate(body)
        head = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=key, ChecksumMode="ENABLED")
        version = head.get("VersionId")
        if not version or version == "null":
            raise ValueError("Versioned storage is required; no asset was changed")
        migration_id = hashlib.sha256(json.dumps({k: v for k, v in body.items() if k != "dryRun"}, sort_keys=True, allow_nan=False).encode()).hexdigest()
        old = head.get("Metadata", {})
        if old.get("migration-id") == migration_id:
            return media._response(200, {"key": key, "status": "already-applied", "versionId": version, "migrationId": migration_id})
        if version != body["expectedVersionId"]:
            return media._response(409, {"error": "Asset changed; inspect and re-plan, never retry with a fresh version blindly"})
        if old.get("kind") == body["kind"] and old.get("panther") == encoded:
            return media._response(200, {"key": key, "status": "unchanged", "versionId": version})
        # Existing compact lineage cannot be silently dropped by a metadata-only migration.
        previous = json.loads(base64.b64decode(old.get("panther", "e30="), validate=True))
        if not set(previous.get("sourceKeys", [])) <= set(body["metadata"]["sourceKeys"]):
            raise ValueError("Migration must retain all existing compact sourceKeys")
        for source in body["metadata"]["sourceKeys"]:
            media.s3.head_object(Bucket=media.BUCKET_NAME, Key=source)
        updated = {**old, "kind": body["kind"], "panther": encoded,
                   "asset-created-at": media._asset_created_at(head).isoformat(),
                   "migration-id": migration_id, "migration-actor": claims["sub"],
                   "migration-previous-version": version,
                   "migration-at": datetime.now(timezone.utc).isoformat()}
        # Keep the reason in the durable request hash/report, not lossy ASCII S3 headers.
        if sum(len(k.encode()) + len(v.encode()) for k, v in updated.items()) > 2048:
            raise ValueError("Metadata is too large; move long notes into a provenance document")
        if body.get("dryRun", True):
            return media._response(200, {"key": key, "status": "ready", "versionId": version, "migrationId": migration_id,
                                         "before": {"kind": old.get("kind"), "metadata": previous},
                                         "after": {"kind": body["kind"], "metadata": body["metadata"]}})
        # This dedicated Lambda has reserved concurrency=1. It is the ONLY metadata writer;
        # ordinary uploads remain create-only. Source version pinning keeps file bytes exact.
        args = {field: head[field] for field in ("ContentType", "CacheControl", "ContentDisposition", "ContentEncoding", "ContentLanguage", "Expires", "WebsiteRedirectLocation", "StorageClass") if field in head}
        result = media.s3.copy_object(Bucket=media.BUCKET_NAME, Key=key,
            CopySource={"Bucket": media.BUCKET_NAME, "Key": key, "VersionId": version},
            CopySourceIfMatch=head["ETag"], MetadataDirective="REPLACE", TaggingDirective="COPY",
            ChecksumAlgorithm="SHA256", Metadata=updated, **args)
        return media._response(200, {"key": key, "status": "migrated", "previousVersionId": version,
                                     "versionId": result["VersionId"], "migrationId": migration_id})
    except ValueError as error:
        return media._response(400, {"error": str(error)})
    except (TypeError, KeyError, UnicodeError):
        return media._response(400, {"error": "Invalid migration or source evidence; run a dry run and inspect the plan"})
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        return media._response(409 if code in {"PreconditionFailed", "ConditionalRequestConflict"} else 503,
                               {"error": "Migration unavailable or conflicted; inspect before retrying"})
