"""Bounded read-only asset catalog and provenance projection, without a new database."""

import base64
import binascii
from concurrent.futures import ThreadPoolExecutor
import json
import math
import re

MAX_DOCUMENT = 2 * 1024**2
PAGE_SIZE = 25


def valid_key(media, game, key):
    return media._valid_key(key) and key.startswith(f"games/{game}/assets/") and not key.endswith("/")


def document(media, key, size):
    if not key.endswith(".json") or not 0 < size <= MAX_DOCUMENT:
        return None
    response = media.s3.get_object(Bucket=media.BUCKET_NAME, Key=key)
    with response["Body"] as body:
        data = body.read(MAX_DOCUMENT + 1)
    if len(data) > MAX_DOCUMENT:
        raise ValueError("Document exceeds reader limit")
    value = json.loads(data)
    return value if isinstance(value, dict) else None


def describe(media, game, key, *, include_document=False):
    head = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=key)
    stored = head.get("Metadata", {})
    try:
        metadata = json.loads(base64.b64decode(stored.get("panther", "e30="), validate=True))
        if not isinstance(metadata, dict):
            metadata = {}
    except (ValueError, binascii.Error):
        metadata = {}
    result = {
        "key": key, "name": key.rsplit("/", 1)[-1],
        "size": head["ContentLength"], "contentType": head.get("ContentType", "application/octet-stream"),
        "kind": stored.get("kind", "unclassified"), "metadata": metadata,
        "lastModified": head["LastModified"].isoformat(), "sourceKeys": [],
    }
    sources = metadata.get("sourceKeys", [])
    sources = list(sources) if isinstance(sources, list) else []
    doc = None
    if key.endswith(".json"):
        try:
            doc = document(media, key, result["size"])
        except (ValueError, UnicodeError):
            result["lineageWarning"] = "Structured provenance could not be read. Original retained."
        if result["size"] > MAX_DOCUMENT:
            result["lineageWarning"] = "Large document: only compact metadata links are indexed."
    if doc:
        # Only explicit supported fields, never recursively guess that arbitrary strings are links.
        if doc.get("gameId", game) != game:
            result["lineageWarning"] = "Document game identity does not match; structured content excluded."
            doc = None
        else:
            sources.extend(doc.get("sourceKeys", []) if isinstance(doc.get("sourceKeys"), list) else [])
            raw = doc.get("rawReference")
            if isinstance(raw, dict):
                sources.append(raw.get("key"))
            inputs = doc.get("inputArtifacts")
            if isinstance(inputs, dict):
                sources.extend(v.get("key") for v in inputs.values() if isinstance(v, dict))
            if doc.get("entityType") == "Recording" and isinstance(doc.get("parts"), list):
                result["recording"] = {"partCount": len(doc["parts"]), "status": doc.get("status", "unknown")}
                for part in doc["parts"]:
                    if isinstance(part, dict) and isinstance(part.get("file"), str) and "/" not in part["file"]:
                        sources.append(key.rsplit("/", 1)[0] + "/" + part["file"])
            if doc.get("entityType") == "RecordingPlayback":
                prefix = key.rsplit("/", 1)[0] + "/"
                digest = doc.get("sourceManifestSha256")
                duration = doc.get("durationSeconds")
                if (doc.get("schemaVersion") == 1 and doc.get("version") == 1
                        and doc.get("recordingId") == key.split("/")[3]
                        and isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest)
                        and key == prefix + f"playback-v1-{digest[:16]}.json"
                        and doc.get("recordingKey") == prefix + "recording.json"
                        and doc.get("audioKey") == prefix + f"playback-v1-{digest[:16]}.m4a"
                        and type(duration) in (int, float) and math.isfinite(duration) and duration > 0):
                    result["playback"] = {field: doc[field] for field in
                                          ("recordingKey", "audioKey", "sourceManifestSha256", "durationSeconds")}
                else:
                    result["lineageWarning"] = "Playback identity is invalid; original sources retained."
            if doc.get("entityType") == "PlayerTranscript" and isinstance(doc.get("recordingId"), str):
                recording = doc["recordingId"]
                if media._valid_slug(recording):
                    sources.append(f"games/{game}/assets/{recording}/original/recording.json")
    result["sourceKeys"] = sorted({s for s in sources if valid_key(media, game, s) and s != key})
    if include_document:
        result["document"] = doc
    return result


def handle(event, media):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not claims.get("sub") or claims.get("cognito:username") not in {"stu", "other_stu"}:
        return media._response(403, {"error": "Owner or DM sign-in required"})
    query = event.get("queryStringParameters") or {}
    game = query.get("gameId", "")
    if not media._valid_slug(game) or len(game) > 96:
        return media._response(400, {"error": "Invalid game"})
    if event["routeKey"] == "GET /asset-document":
        key = query.get("key")
        if not valid_key(media, game, key):
            return media._response(400, {"error": "Invalid asset for selected game"})
        return media._response(200, describe(media, game, key, include_document=True))
    args = {"Bucket": media.BUCKET_NAME, "Prefix": f"games/{game}/assets/", "MaxKeys": PAGE_SIZE}
    if query.get("cursor"):
        try:
            cursor = json.loads(base64.urlsafe_b64decode(query["cursor"]))
            if cursor["gameId"] != game or not isinstance(cursor["token"], str):
                raise ValueError("Wrong cursor scope")
            args["ContinuationToken"] = cursor["token"]
        except (ValueError, KeyError, TypeError, binascii.Error):
            return media._response(400, {"error": "Invalid asset page cursor"})
    page = media.s3.list_objects_v2(**args)
    keys = [o["Key"] for o in page.get("Contents", []) if valid_key(media, game, o["Key"])]
    with ThreadPoolExecutor(max_workers=8) as pool:
        assets = list(pool.map(lambda key: describe(media, game, key), keys))
    cursor = None
    if page.get("NextContinuationToken"):
        cursor = base64.urlsafe_b64encode(json.dumps({
            "gameId": game, "token": page["NextContinuationToken"],
        }).encode()).decode()
    return media._response(200, {"assets": assets, "cursor": cursor})
