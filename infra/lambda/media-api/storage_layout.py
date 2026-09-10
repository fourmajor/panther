"""Versioned physical organization. Asset references are identities, not storage paths.

Keep this pure: the API and migration planner must use exactly the same routing rules.
No routing from prose, filename guesses, canonical status, or inferred character identity.
"""

import re

VERSION = 2
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
REFERENCE = re.compile(
    r"games/(?P<game>[a-z0-9-]+)/assets/(?P<asset>[a-z0-9-]+)/"
    r"(?P<representation>original|derived/[a-z0-9-]+|metadata)/(?P<filename>[^/\\]+)"
)
CHARACTER_KINDS = {"portrait", "character-turnaround-view", "model-3d", "model-provenance"}
COLLECTIONS = {
    "portrait": "portraits", "character-turnaround-view": "reference-images",
    "model-3d": "models", "model-provenance": "models/provenance",
    "recording": "audio/source", "recording-playback": "audio/playback",
    "recording-manifest": "audio/manifests", "recording-checkpoint": "audio/checkpoints",
    "recording-setup": "audio/setup", "capture-health": "audio/diagnostics",
    "recording-playback-manifest": "audio/playback",
    "raw-transcript": "transcripts/raw", "corrected-transcript": "transcripts/corrected",
    "edited-transcript": "transcripts/edited", "novel-chapter": "novel/chapters",
    "novel": "novel", "story": "stories", "music": "music", "map": "maps",
    "document": "documents", "video-comparison": "videos/comparisons",
    "tv-episode": "videos/episodes", "silly-video": "videos/playful",
}


def slug(value):
    if not isinstance(value, str) or len(value) > 96 or not SLUG.fullmatch(value):
        raise ValueError("Storage identifiers must be lowercase hyphenated slugs")
    return value


def parts(reference):
    match = REFERENCE.fullmatch(reference) if isinstance(reference, str) else None
    if not match:
        raise ValueError("Invalid stable asset reference")
    result = match.groupdict()
    slug(result["game"])
    slug(result["asset"])
    filename = result["filename"]
    if filename in {".", ".."} or any(ord(c) < 32 for c in filename) or len(filename.encode()) > 180:
        raise ValueError("Invalid asset filename")
    return result


def index_key(reference):
    item = parts(reference)
    return (f"games/{item['game']}/catalog/assets/{item['asset']}/"
            f"{item['representation']}/{item['filename']}.json")


def location(reference, kind, metadata):
    item = parts(reference)
    slug(kind)
    if not isinstance(metadata, dict) or not isinstance(metadata.get("extra"), dict):
        raise ValueError("Structured metadata and an explicit relationshipRole are required")
    extra = metadata["extra"]
    role = extra.get("relationshipRole")
    if role not in {"finished", "intermediate"}:
        raise ValueError("Explicit finished/intermediate relationshipRole required")
    characters = metadata.get("characterIds")
    if not isinstance(characters, list) or len(characters) != len(set(characters)):
        raise ValueError("Explicit unique characterIds required")
    for character in characters:
        slug(character)
    session = metadata.get("sessionId")
    if session is not None:
        slug(session)
    # Sessions organize recordings and their adaptations; a portrait is owned by the character,
    # even when it was created during a session. Multiple-character media is stored once.
    if kind in CHARACTER_KINDS and len(characters) == 1:
        scope = f"characters/{characters[0]}"
    elif session:
        scope = f"sessions/{session}"
    else:
        scope = "library"
    collection = COLLECTIONS.get(kind)
    job = extra.get("jobId")
    if role == "intermediate" and job and kind not in COLLECTIONS:
        slug(job)
        scope += f"/workflows/{job}"
        collection = kind
    elif collection is None:
        # New types are first-class. No miscellaneous/unclassified dumping ground, and no
        # hard-coded extension whitelist that requires a code change for each new medium.
        collection = f"{'processing' if role == 'intermediate' else 'media'}/{kind}"
    representation = ""
    if item["representation"] != "original":
        representation = item["representation"] + "/"
    key = (f"games/{item['game']}/content/{scope}/{collection}/{item['asset']}/"
           f"{representation}{item['filename']}")
    if len(key.encode()) > 1024:
        raise ValueError("Organized storage key exceeds S3's byte limit")
    return key
