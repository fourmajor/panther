"""Source-to-catalog projection and bounded document reads; browsing uses the durable index."""

import base64
import binascii
import json
import math
import re

MAX_DOCUMENT = 2 * 1024**2
TRANSCRIPT_KINDS = {"transcript", "raw-transcript", "corrected-transcript", "edited-transcript"}


def transcript_summary(doc):
    """Index observed speaker IDs, never infer attendance from the full game roster."""
    summary = {
        "schemaVersion": 1,
        "state": "unavailable",
        "participants": [],
        "segmentCount": None,
        "unassignedSegments": None,
        "reviewStatus": "unknown",
        "publicationStatus": "unknown",
    }
    if not isinstance(doc, dict):
        return summary
    transcript = (
        doc
        if doc.get("entityType") == "PlayerTranscript"
        else (
            doc.get("payload", {}).get("transcript")
            if doc.get("stage") in {"corrected-transcript", "edited-transcript"}
            and isinstance(doc.get("payload"), dict)
            else None
        )
    )
    if not isinstance(transcript, dict) or not isinstance(transcript.get("segments"), list):
        return summary
    names, ambiguous = {}, set()
    for player in (
        transcript.get("players", []) if isinstance(transcript.get("players"), list) else []
    ):
        if not isinstance(player, dict):
            continue
        identity, name = player.get("id"), player.get("name")
        if not isinstance(identity, str) or not isinstance(name, str) or not 1 <= len(name) <= 120:
            continue
        if identity in names and names[identity] != name:
            ambiguous.add(identity)
        names[identity] = name
    counts, unassigned = {}, 0
    for segment in transcript["segments"]:
        player = segment.get("playerId") if isinstance(segment, dict) else None
        if (
            not isinstance(player, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", player)
            or len(player) > 96
        ):
            unassigned += 1
        else:
            counts[player] = counts.get(player, 0) + 1
    summary.update(
        state="available",
        segmentCount=len(transcript["segments"]),
        unassignedSegments=unassigned,
        participants=[
            {
                "id": player,
                "name": None if player in ambiguous else names.get(player),
                "segmentCount": count,
            }
            for player, count in sorted(counts.items())
        ],
    )
    for field in ("reviewStatus", "publicationStatus"):
        value = doc.get(field, transcript.get(field))
        if isinstance(value, str) and 1 <= len(value) <= 120:
            summary[field] = value
    if doc.get("entityType") == "PlayerTranscript" and summary["reviewStatus"] == "unknown":
        summary["reviewStatus"] = "unreviewed"
    return summary


def valid_key(media, game, key):
    return (
        media._valid_key(key) and key.startswith(f"games/{game}/assets/") and not key.endswith("/")
    )


def novel_summary(doc, asset):
    """Observed manuscript metadata only; review acceptance is not owner approval."""
    summary = {"schemaVersion": 1, "state": "unavailable"}
    if (
        not isinstance(doc, dict)
        or doc.get("entityType") != "EditorialArtifact"
        or doc.get("stage") != "novel-chapter"
        or doc.get("gameId") != asset["key"].split("/")[1]
    ):
        return summary
    job, session = doc.get("jobId"), doc.get("sessionId")
    text = doc.get("payload", {}).get("chapter") if isinstance(doc.get("payload"), dict) else None
    if (
        not isinstance(job, str)
        or not re.fullmatch(r"[a-f0-9]{64}", job)
        or not isinstance(session, str)
        or not 1 <= len(session) <= 96
        or not isinstance(text, str)
        or not text.strip()
        or doc.get("publicationStatus") not in {"accepted", "accepted-with-notes"}
    ):
        return summary
    manuscript = text.strip()
    notice = "**Adapted from fictional microphone-test material; not campaign canon.**"
    if manuscript.startswith(notice + "\n"):
        manuscript = manuscript[len(notice):].lstrip()
    heading = re.match(r"^# ([^\n]+)(?:\n|$)", manuscript)
    title = heading[1].strip()[:200] if heading else "Untitled chapter"
    return {
        "schemaVersion": 1,
        "state": "available",
        "id": job,
        "sessionId": session,
        "title": title,
        "publicationStatus": doc.get("publicationStatus", "unknown"),
        "reviewStatus": doc.get("reviewStatus") if isinstance(doc.get("reviewStatus"), str) else "ai-reviewed-unverified",
        "assetKey": asset["key"],
        "publishedAt": asset["lastModified"],
        "category": asset["metadata"].get("category", "unclassified"),
    }


def document(media, key, size, version=None):
    if not key.endswith(".json") or not 0 < size <= MAX_DOCUMENT:
        return None
    response = media.s3.get_object(
        Bucket=media.BUCKET_NAME, Key=key, **({"VersionId": version} if version else {})
    )
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
        "key": key,
        "name": key.rsplit("/", 1)[-1],
        "size": head["ContentLength"],
        "contentType": head.get("ContentType", "application/octet-stream"),
        "kind": stored.get("kind", "unclassified"),
        "metadata": metadata,
        "lastModified": media._asset_created_at(head).isoformat(),
        "sourceKeys": [],
    }
    sources = metadata.get("sourceKeys", [])
    sources = list(sources) if isinstance(sources, list) else []
    doc = None
    if key.endswith(".json"):
        try:
            doc = document(media, key, result["size"], head.get("VersionId"))
        except (ValueError, UnicodeError):
            result["lineageWarning"] = "Structured provenance could not be read. Original retained."
        if result["size"] > MAX_DOCUMENT:
            result["lineageWarning"] = "Large document: only compact metadata links are indexed."
    if doc:
        # Only explicit supported fields, never recursively guess that arbitrary strings are links.
        if doc.get("gameId", game) != game:
            result["lineageWarning"] = (
                "Document game identity does not match; structured content excluded."
            )
            doc = None
        else:
            sources.extend(
                doc.get("sourceKeys", []) if isinstance(doc.get("sourceKeys"), list) else []
            )
            raw = doc.get("rawReference")
            if isinstance(raw, dict):
                sources.append(raw.get("key"))
            inputs = doc.get("inputArtifacts")
            if isinstance(inputs, dict):
                sources.extend(v.get("key") for v in inputs.values() if isinstance(v, dict))
            if doc.get("entityType") == "Recording" and isinstance(doc.get("parts"), list):
                result["recording"] = {
                    "partCount": len(doc["parts"]),
                    "status": doc.get("status", "unknown"),
                }
                for part in doc["parts"]:
                    if (
                        isinstance(part, dict)
                        and isinstance(part.get("file"), str)
                        and "/" not in part["file"]
                    ):
                        sources.append(key.rsplit("/", 1)[0] + "/" + part["file"])
            if doc.get("entityType") == "RecordingPlayback":
                prefix = key.rsplit("/", 1)[0] + "/"
                digest = doc.get("sourceManifestSha256")
                duration = doc.get("durationSeconds")
                if (
                    doc.get("schemaVersion") == 1
                    and doc.get("version") == 1
                    and doc.get("recordingId") == key.split("/")[3]
                    and isinstance(digest, str)
                    and re.fullmatch(r"[a-f0-9]{64}", digest)
                    and key == prefix + f"playback-v1-{digest[:16]}.json"
                    and doc.get("recordingKey") == prefix + "recording.json"
                    and doc.get("audioKey") == prefix + f"playback-v1-{digest[:16]}.mp3"
                    and type(duration) in (int, float)
                    and math.isfinite(duration)
                    and duration > 0
                ):
                    result["playback"] = {
                        field: doc[field]
                        for field in (
                            "recordingKey",
                            "audioKey",
                            "sourceManifestSha256",
                            "durationSeconds",
                        )
                    }
                else:
                    result["lineageWarning"] = (
                        "Playback identity is invalid; original sources retained."
                    )
            if doc.get("entityType") == "PlayerTranscript" and isinstance(
                doc.get("recordingId"), str
            ):
                recording = doc["recordingId"]
                if media._valid_slug(recording):
                    sources.append(f"games/{game}/assets/{recording}/original/recording.json")
    result["sourceKeys"] = sorted({s for s in sources if valid_key(media, game, s) and s != key})
    if result["kind"] in TRANSCRIPT_KINDS:
        result["transcript"] = transcript_summary(doc)
    if (
        result["kind"] == "novel-chapter"
        and key.endswith(".json")
        or doc
        and doc.get("stage") == "novel-chapter"
    ):
        result["novel"] = novel_summary(doc, result)
    if include_document:
        result["document"] = doc
    return result


def handle(event, media):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    from access_policy import authorized

    if not authorized(claims, "MODEL_PUBLISHERS"):
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
    import browse_index

    try:
        return media._response(
            200, browse_index.page(game, query.get("section", "all"), query.get("cursor"))
        )
    except ValueError as error:
        return media._response(400, {"error": str(error)})
    except browse_index.IndexNotReady as error:
        return media._response(503, {"error": str(error)})
