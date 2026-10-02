"""The development UI reads persistent state, not route-specific fixtures."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("panther_development", Path(__file__).parents[1] / "tools/dev_server.py")
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)


def test_empty_database_stays_empty_until_explicit_seed(tmp_path):
    store = dev.Store(tmp_path / "development.sqlite")
    assert store.list("game") == []
    assert dev.Store(store.path).list("game") == []
    store.seed()
    assert len(dev.Store(store.path).list("game")) == 2
    assert store.game("preview-campaign")["gameSettings"]["description"] == ""
    with store.connect() as db:
        db.execute("INSERT INTO objects VALUES ('retained','preview-campaign','{}',X'0102','now')")
    store.seed()
    assert store.object("retained")[1] == b"\x01\x02"


def test_character_changes_are_durable_guarded_and_have_history(tmp_path):
    store = dev.Store(tmp_path / "development.sqlite")
    store.seed()
    character = store.get("character", "preview-campaign:lantern-guide")
    updated = {**character["details"], "overview": "A recorded character fact."}
    body = {"gameId": "preview-campaign", "characterId": "lantern-guide", "expectedRevision": character["revision"], "name": "Lantern Keeper", "details": updated, "reason": "Updated background"}
    result = store.edit_character(body)["character"]
    assert dev.Store(store.path).get("character", "preview-campaign:lantern-guide") == result
    assert len(store.list("history", "preview-campaign:lantern-guide")) == 2
    with pytest.raises(FileExistsError):
        store.edit_character(body)
    history = store.list("history", "preview-campaign:lantern-guide")[0]
    assert history["previousName"] == "The Lantern Guide"
    assert history["previousDetails"] == character["details"]


def test_development_database_cannot_write_inside_repository():
    with pytest.raises(ValueError, match="outside"):
        dev.Store(dev.ROOT / "development.sqlite")


def test_episode_scenes_have_ownership_revisions_and_immutable_history(tmp_path):
    store = dev.Store(tmp_path / "development.sqlite")
    store.seed()
    episode_body = {"gameId": "preview-campaign", "id": "first-episode", "name": "The northern gate", "description": "", "expectedRevision": None, "operationId": "a" * 32}
    episode = store.save_story_entity("episode", episode_body)["record"]
    assert store.save_story_entity("episode", episode_body)["record"] == episode
    scene_body = {"gameId": "preview-campaign", "episodeId": episode["id"], "id": "first-scene", "name": "Lanterns at the gate", "description": "At dusk", "type": "opener", "expectedRevision": None, "operationId": "b" * 32}
    scene = store.save_story_entity("scene", scene_body)["record"]
    assert scene["episodeId"] == episode["id"] and scene["position"] == 0
    with pytest.raises(ValueError, match="episode"):
        store.save_story_entity("scene", {**scene_body, "gameId": "preview-sandbox", "operationId": "c" * 32})
    updated = store.save_story_entity("scene", {**scene_body, "description": "After dusk", "expectedRevision": scene["revision"], "operationId": "d" * 32})["record"]
    assert updated["position"] == scene["position"] and updated["revision"] != scene["revision"]
    history = store.list("scene-history", "preview-campaign")
    assert len(history) == 2 and history[0]["previousRecord"] == scene
    with pytest.raises(FileExistsError, match="changed"):
        store.save_story_entity("scene", {**scene_body, "expectedRevision": scene["revision"], "operationId": "e" * 32})
    with pytest.raises(FileExistsError, match="different"):
        store.save_story_entity("scene", {**scene_body, "description": "Different payload"})
    assert dev.Store(store.path).get("scene", "preview-campaign:first-episode:first-scene") == updated


def test_prompt_led_scene_generation_pins_history_without_inventing_transcripts(tmp_path):
    from types import SimpleNamespace
    store = dev.Store(tmp_path / "development.sqlite")
    store.seed()
    episode = store.save_story_entity("episode", {"gameId": "preview-campaign", "id": "opening", "name": "Opening", "description": "", "expectedRevision": None, "operationId": "1" * 32})["record"]
    body = {"gameId": "preview-campaign", "episodeId": episode["id"], "id": "lanterns", "name": "Lanterns at dusk", "description": "A quiet arrival", "type": "travel", "expectedRevision": None, "operationId": "2" * 32}
    scene = store.save_story_entity("scene", body)["record"]
    store.save_story_entity("scene", {**body, "name": "Lanterns at dawn", "expectedRevision": scene["revision"], "operationId": "3" * 32})
    handler = dev.Handler.__new__(dev.Handler)
    handler.server = SimpleNamespace(store=store)
    handler.send = lambda response: response
    creation = {"schemaVersion": 2, "target": "video", "characterIds": ["lantern-guide"], "sourceKeys": [], "contextKeys": [], "sceneRef": {"episodeId": episode["id"], "sceneId": scene["id"], "revision": scene["revision"]}}
    job = handler.post("/editorial-jobs", {"gameId": "preview-campaign", "creation": creation})
    assert job["creation"]["title"] == scene["name"] and job["creation"]["brief"] == scene["name"]
    assert job["selectedScene"] == scene and job["sourceMode"] == "prompt"
    assert job["videoGenerationAuthorized"] is False and job["workflowVersion"] == 4
    assert "rawKey" not in job and job["creation"]["sourceKeys"] == []
    assert handler.post("/editorial-jobs", {"gameId": "preview-campaign", "creation": creation}) == job
    with pytest.raises(ValueError, match="Scene revision"):
        handler.post("/editorial-jobs", {"gameId": "preview-campaign", "creation": {**creation, "sceneRef": {**creation["sceneRef"], "revision": "4" * 32}}})


def test_episode_order_selection_and_atomic_scene_append(tmp_path):
    import json
    import uuid
    store = dev.Store(tmp_path / "composition.sqlite")
    store.seed()
    base = {"gameId": "preview-campaign", "id": "arrival", "name": "Arrival", "description": "", "expectedRevision": None, "operationId": uuid.uuid4().hex}
    episode = store.save_story_entity("episode", base)["record"]
    scene_bodies = [{"gameId": "preview-campaign", "episodeId": "arrival", "id": identity, "name": identity.title(), "description": "", "type": "general", "expectedRevision": None, "operationId": uuid.uuid4().hex} for identity in ("gate", "river")]
    scenes = []
    for body in scene_bodies:
        response = store.save_story_entity("scene", body)
        scenes.append(response["record"])
        episode = response["episodeRecord"]
    assert episode["sceneIds"] == ["gate", "river"]
    assert store.save_story_entity("scene", scene_bodies[-1])["episodeRecord"] == episode
    assert len(store.list("episode-history", "preview-campaign")) == 3
    with pytest.raises(ValueError, match="exactly once"):
        store.save_story_entity("episode", {**base, "sceneIds": ["gate"], "expectedRevision": episode["revision"], "operationId": uuid.uuid4().hex})
    ordered = store.save_story_entity("episode", {**base, "sceneIds": ["river", "gate"], "expectedRevision": episode["revision"], "operationId": uuid.uuid4().hex})["record"]
    missing = store.episode_composition("preview-campaign", "arrival", ordered["revision"])
    assert not missing["ready"] and missing["missingSceneIds"] == ["river", "gate"]
    for scene, body in zip(scenes, scene_bodies):
        key = f"games/preview-campaign/assets/{scene['id']}/original/take.webm"
        meta = {"kind": "video", "contentType": "video/webm", "extra": {"relationshipRole": "finished", "sceneRef": {"episodeId": "arrival", "sceneId": scene["id"], "revision": scene["revision"]}}}
        with store.connect() as db:
            db.execute("INSERT INTO objects VALUES (?,?,?,?,?)", (key, "preview-campaign", json.dumps(meta), b"synthetic video", "2026-10-01T00:00:00Z"))
        store.save_story_entity("scene", {**body, "selectedOutputKey": key, "expectedRevision": scene["revision"], "operationId": uuid.uuid4().hex})
    ready = dev.Store(store.path).episode_composition("preview-campaign", "arrival", ordered["revision"])
    assert ready["ready"] and [row["scene"]["id"] for row in ready["scenes"]] == ["river", "gate"]
    assert ready["compositionHash"] != missing["compositionHash"]
    assert ready["sourceKeys"] == [f"games/preview-campaign/assets/{id}/original/take.webm" for id in ("river", "gate")]
    with pytest.raises(ValueError, match="this scene"):
        current = store.get("scene", "preview-campaign:arrival:gate")
        store.save_story_entity("scene", {**scene_bodies[0], "selectedOutputKey": ready["sourceKeys"][0], "expectedRevision": current["revision"], "operationId": uuid.uuid4().hex})


def test_development_startup_composition_migration_preserves_exact_source_once(tmp_path):
    import hashlib
    import json
    import sqlite3
    path = tmp_path / "old.sqlite"
    previous = {"schemaVersion": 1, "entityType": "Episode", "gameId": "example-game", "id": "arrival", "name": "Arrival", "description": "", "revision": "a" * 32}
    source = json.dumps(previous)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE records (kind TEXT,id TEXT,game TEXT,payload TEXT,PRIMARY KEY(kind,id))")
        db.execute("INSERT INTO records VALUES ('episode','example-game:arrival','example-game',?)", (source,))
        for identity, position in [("river", 1), ("gate", 0)]:
            scene = {"entityType": "Scene", "gameId": "example-game", "id": identity, "episodeId": "arrival", "position": position, "revision": ("b" if position else "c") * 32}
            db.execute("INSERT INTO records VALUES ('scene',?,'example-game',?)", (f"example-game:arrival:{identity}", json.dumps(scene)))
    store = dev.Store(path)
    episode = store.get("episode", "example-game:arrival")
    assert episode["sceneIds"] == ["gate", "river"] and episode["revision"] != previous["revision"]
    assert store.get("scene", "example-game:arrival:gate")["selectedOutputKey"] is None
    audit = store.get("development-migration", "episode-composition-v1")
    entry = next(row for row in audit["sources"] if row["kind"] == "episode")
    assert entry["sourcePayload"] == source and entry["sourceSha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert store.list("episode-history", "example-game")[0]["previousRecord"] == previous
    assert dev.Store(path).get("development-migration", "episode-composition-v1") == audit
    assert dev.Store(path).get("episode", "example-game:arrival") == episode
