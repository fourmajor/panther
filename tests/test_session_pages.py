"""Session page assembly, asset classification, and the sessions route."""

import copy
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "infra/lambda/media-api"))

import session_pages as pages  # noqa: E402

GAME = "curse-of-the-crimson-throne"
SESSION = "harbor-night"


def asset(key, kind, **extra):
    record = {
        "key": f"games/{GAME}/assets/{key}/original/{extra.pop('name', kind + '.bin')}",
        "kind": kind,
        "name": extra.pop("name", kind + ".bin"),
        "size": extra.pop("size", 1280),
        "contentType": extra.pop("contentType", "application/octet-stream"),
        "lastModified": extra.pop("lastModified", "2026-03-02T00:00:00+00:00"),
        "metadata": {"sessionId": SESSION, "title": kind, "characterIds": [], "extra": {}},
    }
    record.update(extra)
    return record


def test_classification_is_explicit_and_keeps_unknown_kinds():
    assert pages.classify({"kind": "tv-episode", "name": "episode.mp4"}) == "final"
    assert pages.classify({"kind": "video-thumbnail", "name": "cover.jpg"}) == "final"
    assert pages.classify({"kind": "transcript-summary", "name": "recap.json"}) == "final"
    assert pages.classify({"kind": "recording-playback", "name": "listen.mp3"}) == "final"
    assert pages.classify({"kind": "novel-chapter", "name": "chapter.json"}) == "final"
    for kind in ("raw-transcript", "transcript", "corrected-transcript", "narration", "speech", "voice-performance", "model-3d", "scene-render", "face-pass", "recording"):
        assert pages.classify({"kind": kind, "name": "file.bin"}) == "intermediary"
    assert pages.classify({"kind": "flux-pass", "name": "mystery.bin"}) == "intermediary"
    assert pages.classify({"kind": "recording-playback", "name": "part-0001.flac"}) == "intermediary"
    assert pages.classify({"kind": "future-cut", "name": "cut.mp4"}, finals=pages.FINAL_KINDS | {"future-cut"}) == "final"


def test_detail_splits_assets_and_does_not_hide_or_mutate_sources():
    video = asset("video", "tv-episode", name="episode.mp4", contentType="video/mp4", size=4096, thumbnailKey=f"games/{GAME}/assets/thumb/original/cover.jpg")
    video["metadata"]["title"] = "Harbor night"
    thumb = asset("thumb", "video-thumbnail", name="cover.jpg", contentType="image/jpeg", size=900)
    playback = asset("listen", "recording-playback", name="listen.mp3", contentType="audio/mpeg", size=2048)
    transcript = asset("raw", "raw-transcript", name="transcript.json", contentType="application/json", size=3000)
    transcript["metadata"]["sessionId"] = None
    transcript["sourceKeys"] = [video["key"]]
    transcript["transcript"] = {"participants": [{"id": "ada", "name": "Ada"}, {"id": "bo", "name": None}]}
    transcript["metadata"]["characterIds"] = ["captain-vell"]
    face = asset("face", "face-pass", name="pass.png", contentType="image/png")
    mystery = asset("mystery", "flux-pass", name="mesh.bin")
    part = asset("part", "recording", name="part-0003.flac", contentType="audio/flac")
    other = asset("other", "map", name="map.png", contentType="image/png")
    other["metadata"] = {"sessionId": "another-session", "title": "Elsewhere", "characterIds": [], "extra": {}}
    original = copy.deepcopy([video, thumb, playback, transcript, face, mystery, part, other])
    runs = [
        {"id": "editorial~job", "kind": "editorial", "status": "FAILED", "title": "Story & screen planning", "createdAt": 1_700_000_000, "completedAt": 1_700_000_900, "note": "Continuity check failed.", "sessionId": SESSION},
        {"id": "playback~job", "kind": "playback", "status": "done", "title": "Continuous audio playback", "createdAt": 1_700_000_100, "completedAt": 1_700_000_400, "sessionId": SESSION},
        {"id": "model~job", "kind": "model", "status": "done", "title": "3D model · captain-vell", "createdAt": 1_700_000_000, "sessionId": None},
        {"id": "model~tied", "kind": "model", "status": "running", "title": "3D model", "createdAt": 1_700_000_500, "updatedAt": 1_700_000_800, "sessionId": SESSION},
        {"id": "scene-render~job", "kind": "scene-render", "status": "QUEUED", "title": "Scene video", "createdAt": 1_700_000_200, "updatedAt": 1_700_000_250, "sessionId": SESSION},
    ]
    listed = pages.assemble(GAME, original, runs, summaries={SESSION: {"text": "The crew reached the harbor before the tide turned."}})
    assert original == [video, thumb, playback, transcript, face, mystery, part, other]
    card = next(item for item in listed["sessions"] if item["id"] == SESSION)
    assert card["title"] == "Harbor night"
    assert card["thumbnailKey"].endswith("cover.jpg")
    assert card["summaryText"].startswith("The crew reached")
    assert card["status"] == "failed"
    assert card["href"] == f"/games/{GAME}/sessions/{SESSION}"
    assert {item["id"] for item in listed["sessions"]} == {SESSION, "another-session"}
    detail = pages.assemble(GAME, original, runs, session_id=SESSION, summaries={SESSION: {"summary": "The crew reached the harbor."}})["session"]
    assert {item["kind"] for item in detail["finalAssets"]} == {"recording-playback", "tv-episode", "video-thumbnail"}
    assert {item["kind"] for item in detail["intermediaryAssets"]} >= {"raw-transcript", "face-pass", "flux-pass", "recording"}
    assert "map" not in {item["kind"] for item in detail["finalAssets"] + detail["intermediaryAssets"]}
    kinds = {run["kind"] for run in detail["pipelines"]}
    assert kinds == {"editorial", "playback", "model", "scene-render"}
    editorial = next(run for run in detail["pipelines"] if run["kind"] == "editorial")
    assert editorial["status"] == "failed"
    assert editorial["startedAt"] == 1_700_000_000
    assert editorial["endedAt"] == 1_700_000_900
    assert editorial["durationSeconds"] == 900
    assert editorial["detailPath"] == f"/games/{GAME}/workflows/editorial/editorial~job"
    assert editorial["message"] == "Continuity check failed."
    model = next(run for run in detail["pipelines"] if run["kind"] == "model")
    assert model["endedAt"] is None and model["durationSeconds"] is None
    render = next(run for run in detail["pipelines"] if run["kind"] == "scene-render")
    assert render["detailPath"] is None
    assert render["pipelinePath"] == f"/games/{GAME}/pipeline/{SESSION}"
    assert render["endedAt"] is None
    assert detail["recordingKey"].endswith("listen.mp3")
    assert detail["players"] == [{"id": "ada", "name": "Ada"}, {"id": "bo", "name": None}]
    assert detail["characters"] == [{"id": "captain-vell"}]
    assert detail["summarySourceKey"].endswith("transcript.json")


def test_pipeline_timing_ignores_an_end_before_the_start_and_empty_recap():
    bare = asset("note", "document", name="notes.txt", contentType="text/plain")
    bare["metadata"] = {"sessionId": SESSION, "title": "notes.txt", "characterIds": [], "extra": {}}
    run = {"id": "playback~early", "kind": "playback", "status": "done", "createdAt": 500, "completedAt": 100, "sessionId": SESSION}
    body = pages.assemble(GAME, [bare], [run], session_id=SESSION)["session"]
    assert body["pipelines"][0]["endedAt"] is None
    assert body["pipelines"][0]["durationSeconds"] is None
    assert body["summaryText"] is None
    assert body["summarySourceKey"] is None
    assert body["finalAssets"] == []
    assert body["intermediaryAssets"][0]["kind"] == "document"


def test_unknown_session_detail_is_empty_rather_than_invented():
    body = pages.assemble(GAME, [], [], session_id="quiet-table")
    assert body["session"]["title"] == "quiet-table"
    assert body["session"]["pipelines"] == []
    assert body["session"]["finalAssets"] == []
    assert body["session"]["intermediaryAssets"] == []
    assert body["session"]["recordingKey"] is None
    with pytest.raises(ValueError):
        pages.assemble(GAME, [], [], session_id="Not a slug")


def test_sessions_route_renders_list_and_detail_for_every_game():
    source = (ROOT / "web/media-explorer/app.js").read_text()
    ui = (ROOT / "web/ui/src/session-pages.jsx").read_text()
    matches = re.findall(r"pathname\.match\((/\^\\/games\\/.*?\$/)\)", source)
    match = next((item for item in matches if "sessions" in item), None)
    assert match, "sessions route pattern missing"
    pattern = match[1:-1].replace("\\/", "/")
    route = re.compile(pattern)
    listed = route.search(f"/games/{GAME}/sessions")
    opened = route.search(f"/games/{GAME}/sessions/{SESSION}")
    assert listed.group(1) == GAME and listed.group(2) == "sessions" and listed.group(3) is None
    assert opened.group(1) == GAME and opened.group(2) == "sessions" and opened.group(3) == SESSION
    assert 'view: "session-pages"' in source
    assert "mountSessionPages" in source
    for heading in ("Final assets", "Intermediary assets", "Pipelines", "Recording", "Session info"):
        assert heading in ui
