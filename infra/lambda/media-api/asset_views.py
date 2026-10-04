"""Pure presentation predicates shared by materialized catalog and local development."""

import re
import math

import asset_metadata

MAP_SCENE_INSTRUCTIONS = (
    "Treat the input image as a map and use it as the first frame. Preserve its geography, "
    "labels and map style. Show a red dot at the initial location and animate red footprints "
    "following the travelers' route to the destination described in the scene prompt. "
    "Keep the map readable; do not turn it into a landscape or invent geographic facts. "
    "If a location is not identifiable, disclose the ambiguity in planning rather than guess."
)


def session_asset(asset):
    """Audio/recording and transcript union, excluding raw parts and processing artifacts."""
    kind = asset.get("kind", "")
    metadata = asset.get("metadata")
    extra = metadata.get("extra", {}) if isinstance(metadata, dict) else {}
    role = extra.get("relationshipRole") if isinstance(extra, dict) else None
    if (
        not isinstance(kind, str)
        or asset_metadata.internal(kind) and not (kind == "recording-manifest" and asset.get("recording"))
        or role in ("processing", "intermediate")
        or isinstance(extra, dict)
        and extra.get("browserPart") is not None
    ):
        return False
    if kind in {"narration", "music", "voice-performance", "speech"}:
        return False
    name, mime = asset.get("name", "").lower(), asset.get("contentType", "")
    source_chunk = kind == "recording" and re.fullmatch(r"part-\d{4}\.flac", name)
    listening_derivative = kind == "recording-playback-manifest"
    audio = bool(asset.get("recording")) or (
        not source_chunk
        and not listening_derivative
        and (mime.startswith("audio/") or name.endswith((".flac", ".wav", ".mp3", ".m4a", ".ogg")))
    )
    return bool(
        audio
        or kind in {"transcript", "raw-transcript", "corrected-transcript", "edited-transcript"}
    )


def recording_summary(doc):
    """Project explicit immutable recording facts, never infer them from a filename."""
    if not isinstance(doc, dict) or doc.get("entityType") not in {"Recording", "BrowserRecording"} or not isinstance(doc.get("parts"), list):
        return None
    result = {"schemaVersion": 1, "partCount": len(doc["parts"]), "status": doc.get("status", "unknown")}
    for field, limit in (("sessionName", 160), ("startedAt", 80)):
        value = doc.get(field)
        if isinstance(value, str) and 0 < len(value) <= limit and not any(ord(c) < 32 for c in value):
            result[field] = value
    durations = [part.get("duration") if isinstance(part, dict) else None for part in doc["parts"]]
    if durations and all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in durations):
        result["durationSeconds"] = sum(durations)
    return result
