"""Versioned Episode destination contract for the existing screen-adaptation graph."""

from __future__ import annotations
import copy
import re

VERSION = 1
MAX_SCENES = 24
TEXT = {"type": "string"}


def obj(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def strings():
    return {"type": "array", "items": copy.deepcopy(TEXT)}


SCENE_SCHEMA = obj(
    {
        "id": TEXT,
        "title": TEXT,
        "type": {
            "type": "string",
            "enum": ["general", "opener", "travel", "map", "action", "dialogue"],
        },
        "prompt": TEXT,
        "narration": TEXT,
        "characterIds": strings(),
        "referenceKeys": strings(),
        "shotIds": strings(),
    }
)
SCHEMA = obj(
    {
        "schemaVersion": {"type": "integer", "const": VERSION},
        "title": TEXT,
        "synopsis": TEXT,
        "scenes": {"type": "array", "minItems": 1, "maxItems": MAX_SCENES, "items": SCENE_SCHEMA},
    }
)


def validate(plan, *, game, shot_ids, source_keys, character_ids):
    if (
        not isinstance(plan, dict)
        or set(plan) != set(SCHEMA["properties"])
        or plan.get("schemaVersion") != VERSION
    ):
        raise ValueError("Invalid episode adaptation contract")
    for field, limit in [("title", 160), ("synopsis", 4000)]:
        if not isinstance(plan[field], str) or not plan[field].strip() or len(plan[field]) > limit:
            raise ValueError("Invalid episode text")
    scenes = plan["scenes"]
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= MAX_SCENES:
        raise ValueError("Episode adaptation requires bounded scenes")
    seen, covered = set(), []
    for scene in scenes:
        if not isinstance(scene, dict) or set(scene) != set(SCENE_SCHEMA["properties"]):
            raise ValueError("Invalid adapted scene")
        identity = scene["id"]
        if (
            not isinstance(identity, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identity)
            or len(identity) > 64
            or identity in seen
        ):
            raise ValueError("Adapted scenes require unique stable identities")
        seen.add(identity)
        for field, limit, required in [
            ("title", 160, True),
            ("prompt", 4000, True),
            ("narration", 5000, False),
        ]:
            if (
                not isinstance(scene[field], str)
                or len(scene[field]) > limit
                or required
                and not scene[field].strip()
            ):
                raise ValueError("Invalid adapted scene text")
        if scene["type"] not in SCENE_SCHEMA["properties"]["type"]["enum"]:
            raise ValueError("Invalid adapted scene type")
        for field, allowed in [
            ("shotIds", set(shot_ids)),
            ("referenceKeys", set(source_keys)),
            ("characterIds", set(character_ids)),
        ]:
            values = scene[field]
            if (
                not isinstance(values, list)
                or any(not isinstance(value, str) for value in values)
                or len(values) != len(set(values))
                or not set(values) <= allowed
            ):
                raise ValueError("Adapted scene references must match pinned production inputs")
        if not 1 <= len(scene["shotIds"]) <= 24 or any(
            not key.startswith(f"games/{game}/assets/") for key in scene["referenceKeys"]
        ):
            raise ValueError("Adapted scene requires owned shots and same-game references")
        covered.extend(scene["shotIds"])
    if covered != list(shot_ids):
        raise ValueError(
            "Every planned shot must belong to exactly one episode scene in its locked order"
        )
    return copy.deepcopy(plan)
