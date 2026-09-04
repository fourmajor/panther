import base64
import binascii
import json
import logging
import os
import re
from pathlib import PurePosixPath

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
BUCKET_NAME = os.environ["ASSET_BUCKET_NAME"]
SIGNED_URL_TTL_SECONDS = int(os.environ.get("SIGNED_URL_TTL_SECONDS", "300"))
ROOT_PREFIX = "games/"
CHARACTER_PROFILE_PATTERN = re.compile(
    r"^games/(?P<game_id>[a-z0-9]+(?:-[a-z0-9]+)*)/characters/"
    r"(?P<character_id>[a-z0-9]+(?:-[a-z0-9]+)*)/profile\.json$"
)
MAX_CHARACTER_COUNT = 100
MAX_MODEL_BYTES = 5 * 1024 * 1024
MAX_POSTER_BYTES = 8 * 1024 * 1024
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024


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


def _list_characters(_event):
    characters = []
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=BUCKET_NAME, Prefix=ROOT_PREFIX)
    for page in pages:
        for item in page.get("Contents", []):
            match = CHARACTER_PROFILE_PATTERN.fullmatch(item["Key"])
            if not match:
                continue
            profile = _get_json(item["Key"])
            summary = _character_summary(profile, **match.groupdict())
            if summary:
                characters.append(summary)
            if len(characters) >= MAX_CHARACTER_COUNT:
                break
        if len(characters) >= MAX_CHARACTER_COUNT:
            break
    characters.sort(key=lambda item: (item["name"].casefold(), item["gameId"], item["id"]))
    return _response(200, {"characters": characters})


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


def _signed_asset(key):
    return s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": BUCKET_NAME,
            "Key": key,
            "ResponseContentDisposition": "inline",
        },
        ExpiresIn=SIGNED_URL_TTL_SECONDS,
    )


def _character(event):
    game_id = _query(event, "gameId")
    character_id = _query(event, "characterId")
    if not _valid_slug(game_id) or not _valid_slug(character_id):
        return _response(400, {"error": "Invalid character identifier"})

    profile_key = f"games/{game_id}/characters/{character_id}/profile.json"
    profile = _get_json(profile_key)
    summary = _character_summary(profile, game_id=game_id, character_id=character_id)
    if not summary:
        return _response(404, {"error": "Character not found"})

    description = _text(profile.get("summary"), maximum=1000) or ""
    model = profile.get("model")
    if not isinstance(model, dict):
        return _response(422, {"error": "Character model is not configured"})

    web_key = model.get("webKey")
    poster_key = model.get("posterKey")
    game_prefix = f"games/{game_id}/"
    if not all(
        isinstance(key, str) and key.startswith(game_prefix) for key in (web_key, poster_key)
    ):
        return _response(422, {"error": "Character assets are invalid"})
    try:
        configured_maximum = int(model.get("maxBytes", MAX_MODEL_BYTES))
    except (TypeError, ValueError):
        configured_maximum = MAX_MODEL_BYTES
    model_metadata = _asset_metadata(
        web_key,
        maximum=max(1, min(configured_maximum, MAX_MODEL_BYTES)),
        expected_types={"model/gltf-binary", "application/octet-stream"},
    )
    poster_metadata = _asset_metadata(
        poster_key,
        maximum=MAX_POSTER_BYTES,
        expected_types={"image/avif", "image/jpeg", "image/png", "image/webp"},
    )
    if not model_metadata or not poster_metadata:
        return _response(422, {"error": "Character assets are unavailable or exceed limits"})

    default_view = model.get("defaultView") if isinstance(model.get("defaultView"), dict) else {}
    camera_orbit = _text(default_view.get("cameraOrbit"), maximum=80) or "0deg 75deg 105%"
    field_of_view = _text(default_view.get("fieldOfView"), maximum=40) or "30deg"
    return _response(
        200,
        {
            "character": {**summary, "summary": description},
            "model": {
                **model_metadata,
                "url": _signed_asset(web_key),
                "expiresIn": SIGNED_URL_TTL_SECONDS,
                "cameraOrbit": camera_orbit,
                "fieldOfView": field_of_view,
                "sourceRetained": bool(model.get("sourceKey")),
                "provenanceRetained": bool(model.get("provenanceKey")),
            },
            "poster": {**poster_metadata, "url": _signed_asset(poster_key)},
        },
    )


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


def _object_url(event):
    key = _query(event, "key")
    if not _valid_key(key) or key.endswith("/"):
        return _response(400, {"error": "Invalid object key"})

    try:
        metadata = s3.head_object(Bucket=BUCKET_NAME, Key=key)
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
            "size": metadata.get("ContentLength", 0),
            "url": _signed_asset(key),
            "expiresIn": SIGNED_URL_TTL_SECONDS,
            "kind": stored.get("kind"),
            "metadata": details,
            "uploadedBy": stored.get("uploaded-by"),
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
    object_metadata = {"kind": kind, "uploaded-by": uploader, "panther": encoded_metadata}
    if sum(len(k) + len(v) for k, v in object_metadata.items()) > 1900:
        return _response(
            400, {"error": "Metadata is too large; upload long notes as another asset"}
        )
    key = f"games/{game}/assets/{asset}/original/{filename}"
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
            "url": url,
            "headers": headers,
            "expiresIn": SIGNED_URL_TTL_SECONDS,
        },
    )


def handler(event, _context):
    route_key = event.get("routeKey", "")
    try:
        if route_key == "POST /uploads":
            return _upload(event)
        if route_key == "GET /objects":
            return _list_objects(event)
        if route_key == "GET /object-url":
            return _object_url(event)
        if route_key == "GET /characters":
            return _list_characters(event)
        if route_key == "GET /character":
            return _character(event)
        return _response(404, {"error": "Not found"})
    except ClientError:
        logger.exception("Asset storage request failed for route %s", route_key)
        return _response(502, {"error": "Asset storage is temporarily unavailable"})
    except Exception:
        logger.exception("Unexpected media API failure for route %s", route_key)
        return _response(500, {"error": "Unexpected server error"})
