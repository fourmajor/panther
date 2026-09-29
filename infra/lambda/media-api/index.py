import base64
import binascii
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from asset_storage import Storage


s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
BUCKET_NAME = os.environ["ASSET_BUCKET_NAME"]
raw_s3 = s3
s3 = Storage(raw_s3, BUCKET_NAME)
SIGNED_URL_TTL_SECONDS = int(os.environ.get("SIGNED_URL_TTL_SECONDS", "300"))
ROOT_PREFIX = "games/"
MAX_MODEL_BYTES = 5 * 1024 * 1024
MAX_POSTER_BYTES = 8 * 1024 * 1024
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024
MODEL_PUBLISHERS = set(filter(None, os.environ.get("MODEL_PUBLISHERS", "").split(",")))


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store",
        },
        "body": json.dumps(body),
    }


def _query(event, name, default=None):
    return (event.get("queryStringParameters") or {}).get(name, default)


def _valid_key(value, *, allow_root=False):
    if not isinstance(value, str) or len(value) > 1024:
        return False
    if allow_root and value == ROOT_PREFIX:
        return True
    if not value.startswith(ROOT_PREFIX) or value == ROOT_PREFIX:
        return False
    if any(ord(character) < 32 for character in value):
        return False
    return ".." not in PurePosixPath(value).parts


def _valid_slug(value):
    return isinstance(value, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value)


def _asset_created_at(head):
    """Metadata-only revisions do not change when the file entered the game record."""
    value = head.get("Metadata", {}).get("asset-created-at")
    return datetime.fromisoformat(value) if value else head["LastModified"]


def _text(value, *, maximum):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > maximum:
        return None
    return value


def _get_json(key):
    try:
        result = s3.get_object(Bucket=BUCKET_NAME, Key=key)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    try:
        return json.loads(result["Body"].read())
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        logger.warning("Ignoring invalid JSON asset %s", key)
        return None


def _character_summary(profile, *, game_id, character_id):
    if not isinstance(profile, dict) or profile.get("schemaVersion") != 1:
        return None
    if profile.get("gameId") != game_id or profile.get("id") != character_id:
        return None
    name = _text(profile.get("name"), maximum=120)
    title = _text(profile.get("title"), maximum=160)
    if not name:
        return None
    return {
        "gameId": game_id,
        "id": character_id,
        "name": name,
        "title": title or "Character",
    }


def _asset_metadata(key, *, maximum, expected_types):
    if not _valid_key(key):
        return None
    try:
        metadata = s3.head_object(Bucket=BUCKET_NAME, Key=key)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    size = metadata.get("ContentLength", 0)
    content_type = metadata.get("ContentType", "application/octet-stream")
    if size <= 0 or size > maximum or content_type not in expected_types:
        return None
    return {"size": size, "contentType": content_type}


def _signed_asset(key, *, download=False):
    filename = PurePosixPath(key).name
    # ASCII fallback plus RFC 5987 UTF-8 filename; never interpolate raw header text.
    fallback = re.sub(r"[^a-zA-Z0-9._ -]", "_", filename) or "asset"
    disposition = (
        f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
        if download
        else "inline"
    )
    return s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": BUCKET_NAME,
            "Key": key,
            "ResponseContentDisposition": disposition,
        },
        ExpiresIn=SIGNED_URL_TTL_SECONDS,
    )


def _character(event):
    import sys
    import character_appearances

    game, character = _query(event, "gameId"), _query(event, "characterId")
    if not all(_valid_slug(value) and len(value) <= 96 for value in (game, character)):
        return _response(400, {"error": "Invalid character identifier"})
    try:
        aid, sid = _query(event, "appearanceId"), _query(event, "selectionId")
        if any(v is not None and (not _valid_slug(v) or len(v) > 96) for v in (aid, sid)):
            raise ValueError("Invalid selection identity")
        return _response(
            200, character_appearances.view(sys.modules[__name__], game, character, aid, sid)
        )
    except ValueError:
        return _response(404, {"error": "Exact selected character appearance unavailable"})
    except RuntimeError:
        return _response(503, {"error": "Character appearance migration is not complete"})


def _character_versions(event):
    import sys
    import character_appearances

    game, character = _query(event, "gameId"), _query(event, "characterId")
    if not all(_valid_slug(value) and len(value) <= 96 for value in (game, character)):
        return _response(400, {"error": "Invalid character identifier"})
    try:
        return _response(200, character_appearances.history(sys.modules[__name__], game, character))
    except ValueError:
        return _response(404, {"error": "Character appearance history unavailable"})
    except RuntimeError:
        return _response(503, {"error": "Character appearance migration is not complete"})


def _list_objects(event):
    prefix = _query(event, "prefix", ROOT_PREFIX)
    cursor = _query(event, "cursor")
    if not _valid_key(prefix, allow_root=True) or not prefix.endswith("/"):
        return _response(400, {"error": "Invalid prefix"})

    request = {
        "Bucket": BUCKET_NAME,
        "Prefix": prefix,
        "Delimiter": "/",
        "MaxKeys": 250,
    }
    if cursor:
        request["ContinuationToken"] = cursor

    try:
        result = s3.list_objects_v2(**request)
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code == "InvalidArgument":
            return _response(400, {"error": "Invalid cursor"})
        raise

    objects = []
    for item in result.get("Contents", []):
        if item["Key"] == prefix:
            continue
        objects.append(
            {
                "key": item["Key"],
                "name": item["Key"].removeprefix(prefix),
                "size": item["Size"],
                "lastModified": item["LastModified"].isoformat(),
            }
        )

    return _response(
        200,
        {
            "prefix": prefix,
            "prefixes": [item["Prefix"] for item in result.get("CommonPrefixes", [])],
            "objects": objects,
            "nextCursor": result.get("NextContinuationToken"),
        },
    )


def _legacy_profile_record(game, character):
    key = f"games/{game}/characters/{character}/profile.json"
    try:
        record = s3.get_object(Bucket=BUCKET_NAME, Key=key)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    raw = record["Body"].read(64 * 1024 + 1)
    if len(raw) > 64 * 1024:
        return None
    try:
        profile = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not _character_summary(profile, game_id=game, character_id=character):
        return None
    return key, raw, profile, record["ETag"]


def _profile_record(game, character):
    import sys
    import character_appearances

    return character_appearances.profile(sys.modules[__name__], game, character)


def _character_profile(event):
    game, character = _query(event, "gameId"), _query(event, "characterId")
    if not all(_valid_slug(v) and len(v) <= 96 for v in (game, character)):
        return _response(400, {"error": "Invalid character identifier"})
    try:
        record = _profile_record(game, character)
    except ValueError:
        return _response(404, {"error": "Character not found"})
    except RuntimeError:
        return _response(503, {"error": "Character appearance migration is not complete"})
    if not record:
        return _response(404, {"error": "Character not found"})
    return _response(200, {"profile": record[2], "revision": record[3]})


def _publish_model(event):
    import sys
    import character_appearances

    return character_appearances.publish(sys.modules[__name__], event, "model")


def _publish_portrait(event):
    import sys
    import character_appearances

    return character_appearances.publish(sys.modules[__name__], event, "portrait")


def _object_url(event):
    key = _query(event, "key")
    download = _query(event, "download")
    if download not in {None, "", "true"}:
        return _response(400, {"error": "Invalid download option"})
    if not _valid_key(key) or key.endswith("/"):
        return _response(400, {"error": "Invalid object key"})

    try:
        key = s3.reference_for(key)
        metadata = s3.head_object(Bucket=BUCKET_NAME, Key=key, ChecksumMode="ENABLED")
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return _response(404, {"error": "Object not found"})
        raise

    stored = metadata.get("Metadata", {})
    try:
        details = json.loads(base64.b64decode(stored.get("panther", "e30="), validate=True))
    except (ValueError, binascii.Error):
        details = {}
    return _response(
        200,
        {
            "key": key,
            "contentType": metadata.get("ContentType", "application/octet-stream"),
            "storageKey": s3.resolve(key),
            "size": metadata.get("ContentLength", 0),
            "versionId": metadata.get("VersionId"),
            "etag": metadata.get("ETag"),
            "sha256": metadata.get("ChecksumSHA256"),
            "createdAt": _asset_created_at(metadata).isoformat()
            if metadata.get("LastModified")
            else None,
            "url": _signed_asset(key, download=download == "true"),
            "filename": PurePosixPath(key).name,
            "expiresIn": SIGNED_URL_TTL_SECONDS,
            "kind": stored.get("kind"),
            "metadata": details,
            "uploadedBy": stored.get("uploaded-by"),
            "migrationId": stored.get("migration-id"),
        },
    )


def _upload(event):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    uploader = claims.get("sub")
    if not isinstance(uploader, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,128}", uploader):
        return _response(401, {"error": "Sign in to upload"})
    try:
        raw = event.get("body") or ""
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw, validate=True).decode("utf-8")
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return _response(400, {"error": "Invalid upload request"})
    if not isinstance(body, dict):
        return _response(400, {"error": "Invalid upload request"})
    game, asset, kind = (body.get(name) for name in ("gameId", "assetId", "kind"))
    if not all(_valid_slug(value) and len(value) <= 96 for value in (game, asset, kind)):
        return _response(
            400, {"error": "Use lowercase words separated by hyphens for IDs and kind"}
        )
    filename = body.get("filename")
    if (
        not isinstance(filename, str)
        or not 1 <= len(filename.encode("utf-8")) <= 180
        or filename in {".", ".."}
        or any(ord(c) < 32 or c in "/\\" for c in filename)
    ):
        return _response(400, {"error": "Invalid filename"})
    size = body.get("size")
    if type(size) is not int or not 0 <= size <= MAX_UPLOAD_BYTES:
        return _response(400, {"error": "Uploads must be at most 1 GiB"})
    content_type = body.get("contentType")
    if (
        not isinstance(content_type, str)
        or not re.fullmatch(r"[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+", content_type)
        or len(content_type) > 120
    ):
        return _response(400, {"error": "Invalid content type"})
    checksum = body.get("sha256")
    try:
        valid_checksum = (
            isinstance(checksum, str) and len(base64.b64decode(checksum, validate=True)) == 32
        )
    except (ValueError, binascii.Error):
        valid_checksum = False
    if not valid_checksum:
        return _response(400, {"error": "Invalid SHA-256 checksum"})
    metadata = body.get("metadata", {})
    if not isinstance(metadata, dict):
        return _response(400, {"error": "Metadata must be a JSON object"})
    allowed = {
        "title",
        "description",
        "category",
        "characterIds",
        "sessionId",
        "tags",
        "sourceKeys",
        "extra",
    }
    if set(metadata) - allowed:
        return _response(400, {"error": "Unknown metadata fields belong under extra"})
    for field in ("title", "description"):
        if field in metadata and (
            not isinstance(metadata[field], str) or len(metadata[field]) > 500
        ):
            return _response(400, {"error": f"Invalid metadata {field}"})
    categories = {
        "canonical-source",
        "grounded-adaptation",
        "creative-reimagining",
        "playful-derivative",
        "reference",
        "unclassified",
    }
    metadata.setdefault("category", "unclassified")
    if not isinstance(metadata["category"], str) or metadata["category"] not in categories:
        return _response(400, {"error": "Invalid metadata category"})
    for field in ("characterIds", "tags"):
        values = metadata.get(field, [])
        if (
            not isinstance(values, list)
            or len(values) > 20
            or not all(_valid_slug(value) and len(value) <= 96 for value in values)
        ):
            return _response(400, {"error": f"Invalid metadata {field}"})
    if "sessionId" in metadata and (
        not _valid_slug(metadata["sessionId"]) or len(metadata["sessionId"]) > 96
    ):
        return _response(400, {"error": "Invalid metadata sessionId"})
    sources = metadata.get("sourceKeys", [])
    if (
        not isinstance(sources, list)
        or len(sources) > 20
        or not all(_valid_key(key) and key.startswith(f"games/{game}/") for key in sources)
    ):
        return _response(400, {"error": "Source keys must belong to this game"})
    if "extra" in metadata and not isinstance(metadata["extra"], dict):
        return _response(400, {"error": "Metadata extra must be an object"})
    import asset_metadata

    reference = f"games/{game}/assets/{asset}/original/{filename}"
    requested_version = (metadata.get("extra") or {}).get("version")
    if requested_version is not None:
        if not isinstance(requested_version, dict) or set(requested_version) != {"previousKey"}:
            return _response(
                400, {"error": "For a new version, provide only extra.version.previousKey"}
            )
        previous_key = requested_version["previousKey"]
        if (
            not _valid_key(previous_key)
            or not previous_key.startswith(f"games/{game}/assets/")
            or previous_key == reference
        ):
            return _response(400, {"error": "Previous version must be another asset in this game"})
        try:
            previous = s3.head_object(Bucket=BUCKET_NAME, Key=previous_key)
            old_metadata = json.loads(
                base64.b64decode(previous.get("Metadata", {}).get("panther", ""), validate=True)
            )
            old_version = asset_metadata.validate_version(
                old_metadata["extra"]["version"], previous_key
            )
            if previous.get("Metadata", {}).get("kind") != kind:
                return _response(400, {"error": "A version must keep the same asset kind"})
            metadata["extra"]["version"] = {
                "schemaVersion": 1,
                "seriesId": old_version["seriesId"],
                "number": old_version["number"] + 1,
                "previousKey": previous_key,
            }
        except (ClientError, ValueError, KeyError, TypeError, binascii.Error):
            return _response(
                422, {"error": "Previous asset has no valid version record; migrate it first"}
            )
    metadata = asset_metadata.defaults(kind, metadata, filename, content_type, reference)
    try:
        asset_metadata.validate_generation(metadata["extra"]["generation"])
        asset_metadata.validate_version(metadata["extra"]["version"], reference)
    except ValueError as error:
        return _response(400, {"error": str(error)})
    if metadata["extra"]["relationshipRole"] not in {"finished", "intermediate"}:
        return _response(400, {"error": "Invalid relationshipRole"})
    if (
        asset_metadata.internal(kind)
        and not (kind == "recording-manifest" and filename == "recording.json")
        and metadata["extra"]["relationshipRole"] != "intermediate"
    ):
        return _response(400, {"error": "Internal workflow files must be intermediate"})
    try:
        encoded_metadata = base64.b64encode(
            json.dumps(
                {"schemaVersion": 1, **metadata},
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).decode("ascii")
    except (ValueError, TypeError):
        return _response(400, {"error": "Metadata must be valid JSON"})
    object_metadata = {
        "kind": kind,
        "uploaded-by": uploader,
        "panther": encoded_metadata,
        "asset-created-at": datetime.now(timezone.utc).isoformat(),
    }
    if sum(len(k) + len(v) for k, v in object_metadata.items()) > 1900:
        return _response(
            400, {"error": "Metadata is too large; upload long notes as another asset"}
        )
    key = f"games/{game}/assets/{asset}/original/{filename}"
    try:
        storage_key = s3.reserve(
            key, kind, metadata, checksum, size, object_metadata["asset-created-at"]
        )
    except ValueError as error:
        return _response(409, {"error": str(error)})
    headers = {
        "Content-Type": content_type,
        "Content-Length": str(size),
        "If-None-Match": "*",
        "x-amz-checksum-sha256": checksum,
        **{f"x-amz-meta-{name}": value for name, value in object_metadata.items()},
    }
    url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": BUCKET_NAME,
            "Key": key,
            "ContentType": content_type,
            "ContentLength": size,
            "IfNoneMatch": "*",
            "ChecksumSHA256": checksum,
            "Metadata": object_metadata,
        },
        ExpiresIn=SIGNED_URL_TTL_SECONDS,
    )
    return _response(
        200,
        {
            "key": key,
            "storageKey": storage_key,
            "url": url,
            "headers": headers,
            "expiresIn": SIGNED_URL_TTL_SECONDS,
        },
    )


def handler(event, _context):
    route_key = event.get("routeKey", "")
    try:
        if route_key in {"GET /video-collections", "POST /video-collections"}:
            import video_collections
            import sys

            return video_collections.handle(event, sys.modules[__name__])
        if route_key in {"GET /transcript-selection", "POST /transcript-selection"}:
            import transcript_selection
            import sys

            return transcript_selection.handle(event, sys.modules[__name__])
        if route_key == "POST /image-links":
            import image_delivery
            import sys

            return image_delivery.handle(event, sys.modules[__name__])
        if route_key in {"GET /assets", "GET /asset-document"}:
            import asset_library
            import sys

            return asset_library.handle(event, sys.modules[__name__])
        if route_key == "GET /character-profile":
            return _character_profile(event)
        if route_key == "GET /character-versions":
            return _character_versions(event)
        if route_key == "PUT /character-model":
            return _publish_model(event)
        if route_key == "PUT /character-portrait":
            return _publish_portrait(event)
        if route_key == "POST /uploads":
            return _upload(event)
        if route_key == "GET /objects":
            return _list_objects(event)
        if route_key == "GET /object-url":
            return _object_url(event)
        if route_key == "GET /character":
            return _character(event)
        return _response(404, {"error": "Not found"})
    except ClientError:
        logger.exception("Asset storage request failed for route %s", route_key)
        return _response(502, {"error": "Asset storage is temporarily unavailable"})
    except Exception:
        logger.exception("Unexpected media API failure for route %s", route_key)
        return _response(500, {"error": "Unexpected server error"})
