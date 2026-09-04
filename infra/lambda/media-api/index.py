import json
import logging
import os
from pathlib import PurePosixPath

import boto3
from botocore.exceptions import ClientError


s3 = boto3.client("s3")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
BUCKET_NAME = os.environ["ASSET_BUCKET_NAME"]
SIGNED_URL_TTL_SECONDS = int(os.environ.get("SIGNED_URL_TTL_SECONDS", "300"))
ROOT_PREFIX = "games/"


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

    signed_url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": BUCKET_NAME,
            "Key": key,
            "ResponseContentDisposition": "inline",
        },
        ExpiresIn=SIGNED_URL_TTL_SECONDS,
    )
    return _response(
        200,
        {
            "key": key,
            "contentType": metadata.get("ContentType", "application/octet-stream"),
            "size": metadata.get("ContentLength", 0),
            "url": signed_url,
            "expiresIn": SIGNED_URL_TTL_SECONDS,
        },
    )


def handler(event, _context):
    route_key = event.get("routeKey", "")
    try:
        if route_key == "GET /objects":
            return _list_objects(event)
        if route_key == "GET /object-url":
            return _object_url(event)
        return _response(404, {"error": "Not found"})
    except ClientError:
        logger.exception("Asset storage request failed for route %s", route_key)
        return _response(502, {"error": "Asset storage is temporarily unavailable"})
    except Exception:
        logger.exception("Unexpected media API failure for route %s", route_key)
        return _response(500, {"error": "Unexpected server error"})
