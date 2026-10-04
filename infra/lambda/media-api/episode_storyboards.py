"""Canonical scene-owned storyboard revisions; approval is separate from rendering.

Human authorship is assigned by the authenticated edit handler, never accepted
from a request body. AI publication uses the worker-only constructor. Immutable
scene history retains every prior storyboard and decision.
"""

import copy
import hashlib
import json
import re

VERSION = 1
MAX_SHOTS = 24
FIELDS = {"shotId", "description", "camera", "durationSeconds", "frameKey", "narration"}


def normalize(shots, game):
    if not isinstance(shots, list) or not 1 <= len(shots) <= MAX_SHOTS:
        raise ValueError("Choose one to twenty-four storyboard shots")
    ids = set()
    result = []
    for shot in shots:
        if not isinstance(shot, dict) or set(shot) != FIELDS:
            raise ValueError("Invalid storyboard shot fields")
        identity = shot["shotId"]
        if (
            not isinstance(identity, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identity)
            or len(identity) > 96
            or identity in ids
        ):
            raise ValueError("Storyboard shot identities must be unique within a scene")
        ids.add(identity)
        for field in ("description", "camera", "narration"):
            if not isinstance(shot[field], str) or len(shot[field]) > 5000:
                raise ValueError("Invalid storyboard direction")
        if not shot["description"].strip():
            raise ValueError("Describe each storyboard shot")
        seconds = shot["durationSeconds"]
        if type(seconds) not in (int, float) or not 0 < seconds <= 120:
            raise ValueError("Invalid storyboard shot duration")
        key = shot["frameKey"]
        if key is not None and (
            not isinstance(key, str)
            or not key.startswith(f"games/{game}/assets/")
            or ".." in key.split("/")
            or "\\" in key
        ):
            raise ValueError("Storyboard frames must belong to the scene's game")
        result.append(copy.deepcopy(shot))
    if len(json.dumps(result).encode()) > 48_000:
        raise ValueError("Storyboard exceeds the bounded scene record limit")
    return result


def create(shots, game, *, origin, actor):
    if origin not in {"ai", "human"} or not isinstance(actor, str) or not actor:
        raise ValueError("Storyboard authorship must be supplied by its authenticated producer")
    shots = normalize(shots, game)
    revision = hashlib.sha256(
        json.dumps(
            {"origin": origin, "shots": shots},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    return {
        "schemaVersion": VERSION,
        "revision": revision,
        "origin": origin,
        "createdBy": actor,
        "shots": shots,
        "decision": None,
    }


def human_edit(shots, game, previous, actor):
    normalized = normalize(shots, game)
    # A no-op save cannot reclassify an AI plan or erase its pending approval.
    if previous and normalized == previous["shots"]:
        return copy.deepcopy(previous)
    return create(normalized, game, origin="human", actor=actor)


def decide(board, decision, actor):
    if not board or board["origin"] != "ai":
        raise ValueError("Only AI storyboards require approval")
    if (
        not isinstance(decision, dict)
        or set(decision) != {"revision", "action"}
        or decision["revision"] != board["revision"]
    ):
        raise ValueError("The storyboard changed; review its current revision")
    if decision["action"] not in {"approved", "changes-requested"}:
        raise ValueError("Invalid storyboard decision")
    result = copy.deepcopy(board)
    result["decision"] = {**decision, "actor": actor}
    return result


def state(board):
    if not board:
        return "unplanned"
    if board["origin"] == "human":
        return "ready"
    decision = board.get("decision")
    if decision and decision.get("revision") == board["revision"]:
        return "ready" if decision["action"] == "approved" else "changes-requested"
    return "needs-approval"


def apply(record, previous, body, *, actor):
    """Preserve production facts across unrelated scene edits and take selections."""
    for field in ("storyboard", "narration", "productionSource", "shotTakes"):
        if field in (previous or {}):
            record[field] = copy.deepcopy(previous[field])
    if "narration" in body:
        if not isinstance(body["narration"], str) or len(body["narration"]) > 5000:
            raise ValueError("Narration must contain at most 5000 characters")
        record["narration"] = body["narration"]
    if "storyboardShots" in body:
        record["storyboard"] = human_edit(
            body["storyboardShots"], record["gameId"], record.get("storyboard"), actor
        )
    if "storyboardDecision" in body:
        if "storyboardShots" in body:
            raise ValueError("Save the storyboard before reviewing its exact revision")
        record["storyboard"] = decide(record.get("storyboard"), body["storyboardDecision"], actor)
    if (record.get('storyboard') or {}).get('revision') != ((previous or {}).get('storyboard') or {}).get('revision'):
        record['shotTakes'] = {}
    record['storyboardVideoVersion'] = 1
    record["planningState"] = state(record.get("storyboard"))


def require_ready(scene):
    if state(scene.get("storyboard")) in {"needs-approval", "changes-requested"}:
        raise ValueError("Approve this AI storyboard revision before generating footage")
