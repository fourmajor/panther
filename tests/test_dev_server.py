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


def test_sessions_local_filter_matches_union_and_export_suppression():
    audio = {"key": "audio.flac", "name": "audio.flac", "kind": "recording", "contentType": "audio/flac"}
    raw = {"key": "raw.json", "name": "raw.json", "kind": "raw-transcript", "contentType": "application/json"}
    export = {**raw, "key": "raw.md", "name": "raw.md", "contentType": "text/markdown"}
    chunk = {**audio, "key": "part.flac", "name": "part-0001.flac"}
    internal = {**audio, "key": "checkpoint.json", "kind": "recording-checkpoint"}
    processing = {**raw, "key": "working.json", "metadata": {"extra": {"relationshipRole": "intermediate"}}}
    video = {"key": "video.mp4", "name": "video.mp4", "kind": "video-master", "contentType": "video/mp4"}
    values = [audio, raw, export, chunk, internal, processing, video]
    assert dev.local_assets(values, "sessions") == [audio, raw]
    assert dev.local_assets(values, "all") == values
    assert dev.local_assets(values, "videos") == [video]



def test_sessions_local_hides_browser_wav_chunk_without_parent_manifest():
    part = {"key": "part-0001.wav", "name": "part-0001.wav", "kind": "recording", "contentType": "audio/wav",
        "metadata": {"extra": {"browserPart": {"chunkSetId": "synthetic-chunks", "index": 1}}}}
    assert dev.local_assets([part], "sessions") == []
    assert dev.local_assets([part], "audio") == [part]


def map_scene_store(tmp_path):
    import json
    store = dev.Store(tmp_path / "map-scenes.sqlite")
    store.seed()
    episode = store.save_story_entity("episode", {"gameId": "preview-campaign", "id": "journey", "name": "Journey", "expectedRevision": None, "operationId": "a" * 32})["record"]
    key = "games/preview-campaign/assets/route-map/original/map.png"
    with store.connect() as db:
        db.execute("INSERT INTO objects VALUES (?,?,?,?,?)", (key, "preview-campaign", json.dumps({"kind": "map", "contentType": "image/png", "extra": {"relationshipRole": "finished"}}), b"original-map-bytes", "now"))
    body = {"gameId": "preview-campaign", "episodeId": episode["id"], "id": "road", "name": "Travelers move from the city to the badlands", "type": "map", "expectedRevision": None, "operationId": "b" * 32}
    return store, key, body


def test_map_scene_title_only_then_selection_pins_exact_local_image(tmp_path):
    import base64
    import hashlib
    from types import SimpleNamespace
    store, key, body = map_scene_store(tmp_path)
    draft = store.save_story_entity("scene", body)["record"]
    assert draft["description"] == "" and "mapAssetKey" not in draft
    handler = dev.Handler.__new__(dev.Handler)
    handler.server = SimpleNamespace(store=store)
    handler.send = lambda response: response
    creation = {"schemaVersion": 2, "target": "video", "characterIds": [], "sourceKeys": [], "contextKeys": [], "sceneRef": {"episodeId": draft["episodeId"], "sceneId": draft["id"], "revision": draft["revision"]}}
    with pytest.raises(ValueError, match="map image"):
        handler.post("/editorial-jobs", {"gameId": "preview-campaign", "creation": creation})
    selected = store.save_story_entity("scene", {**body, "mapAssetKey": key, "expectedRevision": draft["revision"], "operationId": "c" * 32})["record"]
    # The chosen historical scene stays pinned after a later edit removes its map.
    store.save_story_entity("scene", {**body, "mapAssetKey": None, "expectedRevision": selected["revision"], "operationId": "d" * 32})
    creation["sceneRef"]["revision"] = selected["revision"]
    job = handler.post("/editorial-jobs", {"gameId": "preview-campaign", "creation": creation})
    assert job["selectedScene"] == selected
    assert job["selectedMap"] == {"schemaVersion": 1, "key": key, "sha256": base64.b64encode(hashlib.sha256(b"original-map-bytes").digest()).decode(), "size": len(b"original-map-bytes"), "contentType": "image/png", "role": "first-frame", "instructions": dev.production_asset_views().MAP_SCENE_INSTRUCTIONS}
    assert "red footprints" in job["selectedMap"]["instructions"]
    assert job["status"] == "BLOCKED" and "not connected" in job["message"] and job["videoGenerationAuthorized"] is False
    assert handler.post("/editorial-jobs", {"gameId": "preview-campaign", "creation": creation}) == job
    assert store.get("scene", "preview-campaign:journey:road")["mapAssetKey"] is None


@pytest.mark.parametrize("changes", [
    {"contentType": "image/svg+xml"},
    {"kind": "editorial-plan"},
    {"extra": {"relationshipRole": "processing"}},
    {"extra": {"relationshipRole": "internal"}},
    {"extra": {"relationshipRole": "intermediate"}},
    {"lineageWarning": "Unverified"},
])
def test_local_map_selection_rejects_unsupported_and_processing_assets(tmp_path, changes):
    import json
    store, key, body = map_scene_store(tmp_path)
    metadata, _ = store.object(key)
    with store.connect() as db:
        db.execute("UPDATE objects SET metadata=? WHERE key=?", (json.dumps({**metadata, **changes}), key))
    with pytest.raises(ValueError, match="finished.*map image"):
        store.save_story_entity("scene", {**body, "mapAssetKey": key})
    assert store.list("scene", "preview-campaign") == []
    assert store.get("episode", "preview-campaign:journey")["sceneIds"] == []


def test_local_map_selection_rejects_cross_game_and_missing_images(tmp_path):
    store, key, body = map_scene_store(tmp_path)
    for invalid in (key.replace("preview-campaign", "preview-sandbox"), key.replace("map.png", "missing.png"), "https://example.test/map.png"):
        with pytest.raises(ValueError, match="map image|unavailable"):
            store.save_story_entity("scene", {**body, "mapAssetKey": invalid})
    assert store.list("scene", "preview-campaign") == []


def test_local_map_generation_rejects_empty_image(tmp_path):
    store, key, body = map_scene_store(tmp_path)
    scene = store.save_story_entity("scene", {**body, "mapAssetKey": key})["record"]
    with store.connect() as db:
        db.execute("UPDATE objects SET data=? WHERE key=?", (b"", key))
    with pytest.raises(ValueError, match="20 MiB"):
        store.pin_map("preview-campaign", scene)


@pytest.mark.parametrize("mime", ["image/png", "image/jpeg", "image/webp"])
def test_local_map_selection_accepts_ordinary_images_without_guessing_kind(tmp_path, mime):
    import json
    store, key, body = map_scene_store(tmp_path)
    with store.connect() as db:
        db.execute("UPDATE objects SET metadata=? WHERE key=?", (json.dumps({"kind": "document", "contentType": mime}), key))
    scene = store.save_story_entity("scene", {**body, "mapAssetKey": key})["record"]
    assert scene["mapAssetKey"] == key
    assert store.pin_map("preview-campaign", scene)["contentType"] == mime


def test_local_exact_asset_detail_opens_unknown_binary_without_listing(tmp_path, monkeypatch):
    import json
    store = dev.Store(tmp_path / "asset-details.sqlite")
    store.seed()
    key = "games/preview-campaign/assets/room-take/original/take.wav"
    data = b"RIFF\x00\xffWAVE"
    with store.connect() as db:
        db.execute("INSERT INTO objects VALUES (?,?,?,?,?)", (key, "preview-campaign", json.dumps({"contentType": "audio/wav"}), data, "now"))
    monkeypatch.setattr(store, "objects", lambda *_: pytest.fail("A detail must not enumerate the browse catalog"))
    detail = store.describe_asset("preview-campaign", key)
    assert detail == {"key": key, "name": "take.wav", "size": len(data), "contentType": "audio/wav", "kind": "unclassified", "metadata": {"contentType": "audio/wav"}, "lastModified": "now", "document": None, "sourceKeys": []}
    assert store.object(key)[1] == data
    with pytest.raises(ValueError, match="Invalid asset"):
        store.describe_asset("preview-sandbox", key)
    with pytest.raises(LookupError, match="not found"):
        store.describe_asset("preview-campaign", key.replace("take.wav", "missing.wav"))


def test_local_unknown_structured_detail_preserves_observed_content(tmp_path):
    import json
    store = dev.Store(tmp_path / "structured-detail.sqlite")
    store.seed()
    key = "games/preview-campaign/assets/notes/original/notes.json"
    doc = {"gameId": "preview-campaign", "customField": "Actual source data"}
    with store.connect() as db:
        db.execute("INSERT INTO objects VALUES (?,?,?,?,?)", (key, "preview-campaign", '{}', json.dumps(doc).encode(), "now"))
    assert store.describe_asset("preview-campaign", key)["document"] == doc


def test_local_asset_generation_persists_real_queue_and_rejects_changed_retry(tmp_path):
    store = dev.Store(tmp_path / "generation.sqlite")
    store.seed()
    body = {"gameId": "preview-campaign", "type": "map", "name": "Coast", "prompt": "A detailed coastline map", "operationId": "a" * 32}
    job = store.submit_asset_generation(body)
    assert job["status"] == "QUEUED" and job["assetKey"] is None
    assert dev.Store(store.path).submit_asset_generation(body) == job
    with pytest.raises(ValueError, match="Operation reused"):
        store.submit_asset_generation({**body, "prompt": "Another map"})
    assert store.objects("preview-campaign") == []
    assert store.asset_generation_page("preview-campaign")["jobs"] == [job]
    assert store.asset_generation_page("preview-sandbox")["jobs"] == []


def test_local_asset_generation_pages_are_bounded_and_game_scoped(tmp_path):
    import uuid
    store = dev.Store(tmp_path / "generation-pages.sqlite")
    store.seed()
    for i in range(26):
        store.submit_asset_generation({"gameId": "preview-campaign", "type": "location", "name": str(i), "prompt": "A location image", "operationId": uuid.uuid4().hex})
    first = store.asset_generation_page("preview-campaign")
    assert len(first["jobs"]) == 25 and first["cursor"]
    second = store.asset_generation_page("preview-campaign", first["cursor"])
    assert len(second["jobs"]) == 1 and second["cursor"] is None
    with pytest.raises(ValueError, match="cursor"):
        store.asset_generation_page("preview-sandbox", first["cursor"])


def test_local_browser_upload_verifies_bytes_and_remains_create_only(tmp_path):
    import base64
    import hashlib
    import json
    import threading
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    store = dev.Store(tmp_path / "uploads.sqlite")
    store.seed()
    server = dev.Server(("127.0.0.1", 0), store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    raw = b"original uploaded map bytes"
    body = {"gameId": "preview-campaign", "assetId": "coast-map", "kind": "map", "filename": "coast.png", "size": len(raw), "contentType": "image/png", "sha256": base64.b64encode(hashlib.sha256(raw).digest()).decode(), "metadata": {"title": "Coast", "extra": {"relationshipRole": "finished"}}}
    try:
        request = Request(origin + "/uploads", data=json.dumps(body).encode(), headers={"Authorization": "Bearer local", "Content-Type": "application/json"})
        signed = json.load(urlopen(request))
        assert signed["key"] == "games/preview-campaign/assets/coast-map/original/coast.png"
        with pytest.raises(HTTPError) as missing:
            urlopen(Request(origin + "/object-url?key=" + signed["key"], headers={"Authorization": "Bearer local"}))
        assert missing.value.code == 404
        with pytest.raises(HTTPError) as bad:
            urlopen(Request(signed["url"], data=b"x" * len(raw), headers=signed["headers"], method="PUT"))
        assert bad.value.code == 400 and store.objects("preview-campaign") == []
        urlopen(Request(signed["url"], data=raw, headers=signed["headers"], method="PUT")).close()
        detail = json.load(urlopen(Request(origin + "/object-url?key=" + signed["key"], headers={"Authorization": "Bearer local"})))
        assert detail["sha256"] == body["sha256"] and detail["size"] == len(raw) and detail["key"] == signed["key"] and detail["kind"] == "map"
        with pytest.raises(HTTPError) as duplicate:
            urlopen(Request(signed["url"], data=raw, headers=signed["headers"], method="PUT"))
        assert duplicate.value.code == 412 and store.object(signed["key"])[1] == raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_local_recording_reports_unavailable_services_and_existing_queued_audio(tmp_path):
    import json
    import threading
    from urllib.request import Request, urlopen
    store = dev.Store(tmp_path / "recording.sqlite")
    store.seed()
    store.put("playback", "retained-audio", {"status": "SUBMITTED"}, "preview-campaign")
    server = dev.Server(("127.0.0.1", 0), store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        def get(path):
            return json.load(urlopen(Request(origin + path, headers={"Authorization": "Bearer local"})))
        capability = get("/browser-recording/capabilities")
        assert capability["canRecord"] and not capability["transcriptionAvailable"] and not capability["playbackAvailable"]
        assert "not configured" in capability["transcriptionUnavailableReason"]
        result = get("/browser-transcriptions?gameId=preview-campaign&playbackJobId=retained-audio")
        assert result["playback"]["status"] == "BLOCKED" and "local development" in result["playback"]["message"]
        assert result["jobs"] == [] and result["transcriptKey"] is None
        assert store.get("playback", "retained-audio")["status"] == "SUBMITTED"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_local_transcript_summaries_pin_real_evidence_and_report_missing_worker(tmp_path):
    import base64
    import hashlib
    import json
    store = dev.Store(tmp_path / "summaries.sqlite")
    store.seed()
    key = "games/preview-campaign/assets/speech/original/transcript.json"
    document = {"schemaVersion": 1, "entityType": "PlayerTranscript", "gameId": "preview-campaign", "recordedAt": "2026-10-01T09:00:00Z", "players": [{"id": "player-1", "name": "Example Player"}], "segments": [{"text": "We reached the gate.", "playerId": "player-1"}, {"text": "It was closed.", "playerId": "player-2", "uncertainty": "quiet"}]}
    raw = json.dumps(document).encode()
    with store.connect() as db:
        db.execute("INSERT INTO objects VALUES (?,?,?,?,?)", (key, "preview-campaign", '{"kind":"raw-transcript"}', raw, "now"))
    assert store.transcript_summary_view("preview-campaign", key)["status"] == "MISSING"
    body = {"gameId": "preview-campaign", "key": key}
    first = store.submit_transcript_summary(body)
    assert first["status"] == "ATTENTION" and "not configured" in first["message"]
    assert first["source"] == {"key": key, "sha256": base64.b64encode(hashlib.sha256(raw).digest()).decode(), "size": len(raw)}
    assert first["participants"] == [{"id": "player-1", "name": "Example Player"}, {"id": "player-2"}]
    assert first["recordedAt"] == document["recordedAt"] and first["summary"] is None
    second = store.submit_transcript_summary({**body, "operationId": "1" * 32})
    assert second["jobId"] != first["jobId"]
    assert store.submit_transcript_summary(body) == second
    assert store.get("transcript-summary", first["jobId"]) == first
    assert dev.Store(store.path).transcript_summary_view("preview-campaign", key) == second
    assert store.object(key)[1] == raw
    with pytest.raises(ValueError):
        store.submit_transcript_summary({**body, "gameId": "preview-sandbox"})
    with pytest.raises(ValueError):
        store.submit_transcript_summary({**body, "operationId": "bad"})


def test_local_novel_accepts_prompt_without_sources_or_title(tmp_path):
    from types import SimpleNamespace
    store = dev.Store(tmp_path / "novel.sqlite")
    store.seed()
    handler = dev.Handler.__new__(dev.Handler)
    handler.server = SimpleNamespace(store=store)
    handler.send = lambda response: response
    creation = {"schemaVersion": 3, "target": "novel", "brief": "A traveler discovers a lost gate", "sourceKeys": [], "contextKeys": []}
    body = {"gameId": "preview-campaign", "creation": creation}
    job = handler.post("/editorial-jobs", body)
    assert job["creation"]["title"] == creation["brief"]
    assert handler.post("/editorial-jobs", body) == job
    with pytest.raises(ValueError, match="prompt"):
        handler.post("/editorial-jobs", {**body, "creation": {**creation, "brief": ""}})


def test_local_editorial_queue_reports_missing_worker_without_mutating_history(tmp_path):
    import json
    import threading
    from urllib.request import Request, urlopen
    store = dev.Store(tmp_path / "editorial.sqlite")
    store.put("editorial", "prior-job", {"jobId": "prior-job", "status": "SUBMITTED", "creation": {"target": "novel", "brief": "A fictional river crossing"}}, "fictional-game")
    server = dev.Server(("127.0.0.1", 0), store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = json.load(urlopen(Request(f"http://127.0.0.1:{server.server_port}/editorial-jobs?jobId=prior-job", headers={"Authorization": "Bearer local"})))
        assert response["job"]["status"] == "BLOCKED"
        assert "not connected" in response["job"]["message"]
        assert response["tasks"] == []
        assert store.get("editorial", "prior-job")["status"] == "SUBMITTED"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
