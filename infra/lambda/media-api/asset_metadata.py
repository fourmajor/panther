"""Current asset metadata defaults shared by normal uploads and migration validation."""

from decimal import Decimal, InvalidOperation
import re


def unknown_generation():
    return {"schemaVersion": 1, "method": "unknown", "cost": {"status": "unknown"}}


def validate_generation(value):
    """Compact creation facts, not a model guess or a sum of upstream asset charges."""
    fields = {"schemaVersion", "method", "model", "provider", "inference", "execution", "tool", "cost", "evidence"}
    if not isinstance(value, dict) or set(value) - fields:
        raise ValueError("Invalid generation metadata fields")
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1:
        raise ValueError("Generation schemaVersion 1 required")
    if not isinstance(value.get("method"), str) or value["method"] not in {"ai", "ai-assisted", "procedural", "capture", "human", "unknown"}:
        raise ValueError("Invalid generation method")
    for field in ("model", "provider", "tool", "evidence"):
        if field in value and (not isinstance(value[field], str) or not 1 <= len(value[field]) <= 200
                               or any(ord(c) < 32 for c in value[field])):
            raise ValueError(f"Invalid generation {field}")
    for field in ("inference", "execution"):
        if field in value and (not isinstance(value[field], str) or value[field] not in {"local", "remote", "unknown", "not-applicable"}):
            raise ValueError(f"Invalid generation {field}")
    if value.get("method") in {"procedural", "capture", "human"} and value.get("inference", "not-applicable") != "not-applicable":
        raise ValueError("Non-AI creation cannot assert inference")
    cost = value.get("cost")
    if not isinstance(cost, dict) or set(cost) - {"status", "amount", "currency"}:
        raise ValueError("Invalid generation cost")
    if not isinstance(cost.get("status"), str) or cost["status"] not in {"billed", "estimated", "subscription", "not-applicable", "unknown"}:
        raise ValueError("Invalid generation cost status")
    if cost["status"] in {"billed", "estimated"}:
        amount = cost.get("amount")
        if (not isinstance(amount, str) or not re.fullmatch(r"\d{1,9}(\.\d{1,9})?", amount)
                or not isinstance(cost.get("currency"), str) or not re.fullmatch(r"[A-Z]{3}", cost["currency"])):
            raise ValueError("Costs require a nonnegative decimal string and ISO currency")
        try:
            if not Decimal(amount).is_finite() or Decimal(amount) < 0:
                raise ValueError("Invalid generation amount")
        except InvalidOperation:
            raise ValueError("Invalid generation amount") from None
        if not value.get("evidence"):
            raise ValueError("Billed/estimated costs require evidence, never a budget reservation")
    elif set(cost) != {"status"}:
        raise ValueError("Unknown, subscription and inapplicable costs must not imply a numeric charge")
    return value

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
    extra.setdefault("generation", unknown_generation())
    result["extra"] = extra
    return result
