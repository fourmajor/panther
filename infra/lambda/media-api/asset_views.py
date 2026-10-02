"""Pure presentation predicates shared by materialized catalog and local development."""

import re

import asset_metadata


def session_asset(asset):
    """Audio/recording and transcript union, excluding raw parts and processing artifacts."""
    kind = asset.get("kind", "")
    metadata = asset.get("metadata")
    extra = metadata.get("extra", {}) if isinstance(metadata, dict) else {}
    role = extra.get("relationshipRole") if isinstance(extra, dict) else None
    if (
        not isinstance(kind, str)
        or asset_metadata.internal(kind)
        or role in ("processing", "intermediate")
        or isinstance(extra, dict)
        and extra.get("browserPart") is not None
    ):
        return False
    name, mime = asset.get("name", "").lower(), asset.get("contentType", "")
    source_chunk = kind == "recording" and re.fullmatch(r"part-\d{4}\.flac", name)
    listening_derivative = kind in {"recording-playback", "recording-playback-manifest"}
    audio = bool(asset.get("recording")) or (
        not source_chunk
        and not listening_derivative
        and (mime.startswith("audio/") or name.endswith((".flac", ".wav", ".mp3", ".m4a", ".ogg")))
    )
    return bool(
        audio
        or kind in {"transcript", "raw-transcript", "corrected-transcript", "edited-transcript"}
    )
