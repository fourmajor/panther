"""Storyboard authorship, exact-revision decisions and retained scene history."""

import copy
import importlib
import sys
from pathlib import Path
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "infra/lambda/media-api"))
boards = importlib.import_module("episode_storyboards")


def shots():
    return [
        {
            "shotId": "arrival",
            "description": "The party reaches the gates.",
            "camera": "Wide establishing shot",
            "durationSeconds": 8,
            "frameKey": None,
            "narration": "They arrive at dusk.",
        }
    ]


def test_only_ai_revisions_need_approval_and_decisions_do_not_transfer():
    human = boards.create(shots(), "fictional-game", origin="human", actor="fictional-editor")
    ai = boards.create(shots(), "fictional-game", origin="ai", actor="fictional-job")
    assert boards.state(human) == "ready"
    assert boards.state(ai) == "needs-approval"
    with pytest.raises(ValueError, match="Only AI"):
        boards.decide(human, {"revision": human["revision"], "action": "approved"}, "owner")
    with pytest.raises(ValueError, match="Approve"):
        boards.require_ready({"storyboard": ai})
    approved = boards.decide(ai, {"revision": ai["revision"], "action": "approved"}, "owner")
    boards.require_ready({"storyboard": approved})
    assert boards.state(ai) == "needs-approval"  # Input remains immutable.
    revised = shots()
    revised[0]["camera"] = "Close-up"
    replacement = boards.create(revised, "fictional-game", origin="ai", actor="fictional-job")
    with pytest.raises(ValueError, match="changed"):
        boards.decide(replacement, approved["decision"] | {"actor": "owner"}, "owner")
    replacement["decision"] = approved["decision"]
    assert boards.state(replacement) == "needs-approval"


def test_noop_human_save_preserves_ai_authorship_but_real_edit_is_human():
    ai = boards.create(shots(), "fictional-game", origin="ai", actor="fictional-job")
    assert boards.human_edit(shots(), "fictional-game", ai, "fictional-editor") == ai
    changed = shots()
    changed[0]["description"] = "The party reaches the docks."
    human = boards.human_edit(changed, "fictional-game", ai, "fictional-editor")
    assert human["origin"] == "human" and boards.state(human) == "ready"
    assert human["decision"] is None and human["revision"] != ai["revision"]


@pytest.mark.parametrize(
    "change", ["duplicate", "foreign-frame", "authorship", "duration", "oversized"]
)
def test_invalid_or_spoofed_shots_fail_closed(change):
    values = shots()
    if change == "duplicate":
        values *= 2
    elif change == "foreign-frame":
        values[0]["frameKey"] = "games/other-game/assets/frame/original/a.png"
    elif change == "authorship":
        values[0]["origin"] = "human"
    elif change == "duration":
        values[0]["durationSeconds"] = True
    else:
        values[0]["description"] = "x" * 5001
    with pytest.raises(ValueError):
        boards.create(values, "fictional-game", origin="human", actor="fictional-editor")


def test_unrelated_edits_preserve_storyboard_and_exact_decision():
    ai = boards.create(shots(), "fictional-game", origin="ai", actor="fictional-job")
    ai = boards.decide(ai, {"revision": ai["revision"], "action": "approved"}, "owner")
    previous = {
        "storyboard": ai,
        "narration": "Original words",
        "productionSource": {"jobId": "fictional-job"},
    }
    record = {"gameId": "fictional-game"}
    boards.apply(record, previous, {"name": "New scene title"}, actor="fictional-editor")
    assert record == {"gameId": "fictional-game", **previous, "planningState": "ready", "storyboardVideoVersion": 1}
    assert record["storyboard"] is not previous["storyboard"]


def test_local_scene_edits_have_canonical_storyboard_and_immutable_history(tmp_path):
    from test_dev_server import dev

    store = dev.Store(tmp_path / "storyboards.sqlite")
    store.seed()
    game = "preview-campaign"
    store.save_story_entity(
        "episode",
        {
            "gameId": game,
            "id": "journey",
            "name": "Journey",
            "expectedRevision": None,
            "operationId": uuid.uuid4().hex,
        },
    )
    body = {
        "gameId": game,
        "episodeId": "journey",
        "id": "arrival",
        "name": "Arrival",
        "expectedRevision": None,
        "operationId": uuid.uuid4().hex,
        "storyboardShots": shots(),
    }
    scene = store.save_story_entity("scene", body)["record"]
    assert scene["planningState"] == "ready" and scene["storyboard"]["origin"] == "human"
    ai = boards.create(shots(), game, origin="ai", actor="fictional-job")
    scene["storyboard"] = ai
    scene["planningState"] = "needs-approval"
    store.put("scene", game + ":journey:arrival", scene, game)
    unchanged = store.save_story_entity(
        "scene", {**body, "expectedRevision": scene["revision"], "operationId": uuid.uuid4().hex}
    )["record"]
    assert unchanged["planningState"] == "needs-approval"
    reviewed = store.save_story_entity(
        "scene",
        {
            key: value
            for key, value in {
                **body,
                "storyboardShots": None,
                "expectedRevision": unchanged["revision"],
                "operationId": uuid.uuid4().hex,
                "storyboardDecision": {"revision": ai["revision"], "action": "approved"},
            }.items()
            if key != "storyboardShots"
        },
    )["record"]
    assert reviewed["planningState"] == "ready"
    history = store.get("scene-history", game + ":journey:arrival:" + reviewed["revision"])
    assert history["previousRecord"]["storyboard"]["decision"] is None
    changed = copy.deepcopy(shots())
    changed[0]["camera"] = "Close-up"
    human = store.save_story_entity(
        "scene",
        {
            **body,
            "storyboardShots": changed,
            "expectedRevision": reviewed["revision"],
            "operationId": uuid.uuid4().hex,
        },
    )["record"]
    assert human["planningState"] == "ready" and human["storyboard"]["decision"] is None
