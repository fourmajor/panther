"""Current asset metadata defaults shared by normal uploads and migration validation."""

INTERNAL_KINDS = {
    "context", "correction", "capture-health", "recording-checkpoint", "recording-manifest",
    "recording-playback-manifest", "novel-brief", "novel-options", "novel-outline", "novel-draft",
    "novel-developmental-edit", "novel-revision", "novel-continuity", "novel-line-copyedit", "novel-proof",
    "video-treatment", "video-screenplay", "video-script-edit", "video-shooting-script", "video-breakdown",
    "video-design", "video-reference-plan", "video-voice-casting", "video-blocking", "video-shot-list",
    "video-storyboards", "video-generation-packets", "video-edit-sound-vfx", "video-production-plan", "video-preflight",
}


def internal(kind):
    return kind in INTERNAL_KINDS or kind.startswith("editorial-") or "provenance" in kind


def defaults(kind, metadata, filename, content_type):
    result = dict(metadata)
    result.setdefault("title", filename.rsplit(".", 1)[0])
    for field in ("characterIds", "tags", "sourceKeys"):
        result.setdefault(field, [])
    extra = dict(result.get("extra", {}))
    if internal(kind):
        # A Recording manifest represents the finished audio set; all other manifests are technical.
        role = "finished" if kind == "recording-manifest" and filename == "recording.json" else "intermediate"
    elif kind in {"raw-transcript", "corrected-transcript", "edited-transcript", "novel-chapter", "novel", "story", "portrait", "map", "document", "game-context", "model-3d", "music", "recording", "recording-playback", "character-turnaround-view"} or content_type.startswith(("audio/", "video/", "image/")):
        role = "finished"
    else:
        role = "intermediate"
    extra.setdefault("relationshipRole", role)
    result["extra"] = extra
    return result
