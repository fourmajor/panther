"""Positive, structured eligibility for narrative evidence; never title/name inference."""

import re

CREATIVE_KINDS = {"lore", "game-context", "character-profile", "corrected-transcript"}
TECHNICAL_KINDS = {
    "provenance",
    "model-provenance",
    "generation-provenance",
    "migration-audit",
    "generation-verification",
    "verification-report",
    "review-report",
    "capture-health",
    "recording-manifest",
    "recording-checkpoint",
    "reading-script",
    "test-script",
    "holdout",
}


def eligible(kind, metadata):
    if not isinstance(metadata, dict):
        return False
    extra = metadata.get("extra", {})
    if not isinstance(extra, dict):
        return False
    semantic_types = [kind, extra.get("artifactType"), extra.get("entityType")]
    normalized = [
        re.sub(r"(?<!^)(?=[A-Z])", "-", value).lower()
        for value in semantic_types
        if isinstance(value, str)
    ]
    if any(
        value in TECHNICAL_KINDS
        or {"provenance", "migration", "verification", "audit"} & set(value.split("-"))
        for value in normalized
    ):
        return False
    if (
        extra.get("relationshipRole") == "intermediate"
        or extra.get("contextUse") == "exclude"
        or metadata.get("category")
        in {"grounded-adaptation", "creative-reimagining", "playful-derivative"}
    ):
        return False
    return kind in CREATIVE_KINDS or extra.get("contextUse") == "creative-evidence"
