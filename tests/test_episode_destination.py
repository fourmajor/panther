"""Canonical pipeline publication, never a second movie/episode implementation."""

import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "infra/lambda/media-api"))
destination = importlib.import_module("episode_destination")


def source():
    job = {
        "jobId": "a" * 64,
        "gameId": "fictional-game",
        "createdAt": 1700000000,
        "creation": {"title": "A chapter"},
        "selectedCharacters": [],
    }
    shot = {
        "shotId": "SC01_SH01",
        "sceneId": "SC01",
        "durationSeconds": 8,
        "description": "The gates open.",
        "camera": "Wide",
        "color": "#223344",
        "subjects": [],
    }
    scene = {
        "id": "arrival",
        "title": "Arrival",
        "type": "general",
        "prompt": "Show the party arriving.",
        "narration": "At dusk, they arrived.",
        "characterIds": [],
        "referenceKeys": [],
        "shotIds": [shot["shotId"]],
    }
    artifact = {
        "schemaVersion": 1,
        "entityType": "EditorialArtifact",
        "jobId": job["jobId"],
        "gameId": job["gameId"],
        "stage": "video-generation-packets",
        "workflowVersion": 5,
        "structuralValidation": "passed",
        "publicationStatus": "accepted",
        "videoGenerationAuthorized": False,
        "sourceKeys": [],
        "payload": {
            "shots": [shot],
            "episode": {
                "schemaVersion": 1,
                "title": "At the gates",
                "synopsis": "The party arrives.",
                "scenes": [scene],
            },
        },
    }
    pin = {
        "key": "games/fictional-game/assets/editorial-plan/original/packet.json",
        "size": 1200,
        "sha256": "actual-checksum",
    }
    return job, artifact, pin


def test_episode_owns_scenes_and_exact_storyboard_source_without_fake_outputs():
    job, artifact, pin = source()
    original = copy.deepcopy(artifact)
    episode, scenes = destination.records(job, artifact, pin)
    assert episode["id"] == destination.placeholder(job)["id"]
    assert episode["production"]["state"] == "planned" and episode["sceneIds"] == ["arrival"]
    assert scenes[0]["episodeId"] == episode["id"]
    assert scenes[0]["planningState"] == "needs-approval"
    assert scenes[0]["storyboard"]["origin"] == "ai"
    assert scenes[0]["selectedOutputKey"] is None
    assert scenes[0]["narration"] == "At dusk, they arrived."
    assert scenes[0]["productionSource"]["plannedShots"] == artifact["payload"]["shots"]
    assert destination.records(job, artifact, pin) == (episode, scenes)
    assert artifact == original


@pytest.mark.parametrize(
    "change",
    ["game", "job", "unvalidated", "authorized", "missing-shot", "duplicate", "foreign-cast"],
)
def test_invalid_destination_fails_before_publication(change):
    job, artifact, pin = source()
    scene = artifact["payload"]["episode"]["scenes"][0]
    if change == "game":
        artifact["gameId"] = "other-game"
    elif change == "job":
        artifact["jobId"] = "b" * 64
    elif change == "unvalidated":
        artifact["structuralValidation"] = "unknown"
    elif change == "authorized":
        artifact["videoGenerationAuthorized"] = True
    elif change == "missing-shot":
        scene["shotIds"] = ["missing"]
    elif change == "foreign-cast":
        scene["characterIds"] = ["unbound-character"]
    else:
        artifact["payload"]["episode"]["scenes"].append(copy.deepcopy(scene))
    with pytest.raises(ValueError):
        destination.records(job, artifact, pin)


def test_local_chapter_submission_pins_bytes_and_persists_episode_placeholder(tmp_path):
    from test_dev_server import dev

    store = dev.Store(tmp_path / "episode-source.sqlite")
    store.seed()
    game, identity = "preview-campaign", "c" * 64
    key = f"games/{game}/assets/chapter-source/original/chapter.json"
    raw = json.dumps(
        {"gameId": game, "title": "The crossing", "markdown": "The boat reaches the far bank."}
    ).encode()
    with store.connect() as db:
        db.execute(
            "INSERT INTO objects VALUES (?,?,?,?,?)",
            (
                key,
                game,
                json.dumps({"kind": "novel-chapter", "contentType": "application/json"}),
                raw,
                "now",
            ),
        )
    store.put(
        "chapter",
        identity,
        {"id": identity, "gameId": game, "title": "The crossing", "assetKey": key},
        game,
    )
    body = {"schemaVersion": 4, "target": "video", "chapterId": identity}
    from types import SimpleNamespace
    handler = dev.Handler.__new__(dev.Handler)
    handler.server = SimpleNamespace(store=store)
    handler.send = lambda value: value
    first = handler.post("/editorial-jobs", {"gameId": game, "creation": body})
    assert store.submit_episode_adaptation(game, body) == first
    assert first["chapterSource"]["size"] == len(raw)
    assert (
        first["chapterSource"]["sha256"]
        == __import__("base64").b64encode(hashlib.sha256(raw).digest()).decode()
    )
    assert first["rawSources"] == [] and first["videoGenerationAuthorized"] is False
    assert {person["characterId"] for person in first["selectedCharacters"]} == {person["id"] for person in store.list("character",game)}
    episode = store.get("episode", game + ":" + first["episodeRef"]["episodeId"])
    assert episode["production"]["state"] == "planning" and episode["sceneIds"] == []
    assert (
        store.get("episode-history", game + ":" + episode["id"] + ":" + episode["revision"])[
            "record"
        ]
        == episode
    )
    with pytest.raises(ValueError, match="this game"):
        store.submit_episode_adaptation("preview-sandbox", body)
    with pytest.raises(ValueError):
        store.submit_episode_adaptation(game, {**body, "markdown": "Spoofed manuscript"})


def test_scene_publication_preserves_fractional_dynamodb_values():
    from decimal import Decimal
    job, artifact, pin = source()
    job["selectedScene"] = {"gameId":job["gameId"], "episodeId":"owned-episode", "id":"arrival", "revision":"prior", "position": Decimal("1"), "generationInputs":{"durationSeconds":Decimal("7.5")}, "selectedOutputKey":"existing-output"}
    record = destination.scene_record(job, artifact, pin)
    assert record["generationInputs"]["durationSeconds"] == 7.5
    assert record["episodeId"] == "owned-episode" and record["selectedOutputKey"] == "existing-output"
    assert json.loads(json.dumps(record))["position"] == 1
