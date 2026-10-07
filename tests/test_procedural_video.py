"""Synthetic contract tests; no private cast, provider or Blender calls."""

import copy
import json

import pytest
from click.testing import CliRunner

from panther_journal import procedural_video as video


def production():
    return {"gameId": "sample-game", "sessionId": "sample-session", "title": "A tower",
        "shots": [{"id": "entrance", "sceneId": "tower", "prompt": "The knight enters.",
                   "continuity": "One knight, unchanged shield.", "inSeconds": 1, "outSeconds": 4,
                   "appearances": [{"characterId": "knight"}]}]}


def design():
    return {"objects": [{"id": "hero", "shape": "actor", "color": [.2,.3,.4], "emission": 0,
                         "position": [0,0,1], "rotation": [0,0,0], "scale": [1,1,1], "points": [],
                         "characterId": "knight", "features": ["shield"], "keyframes": []}],
            "camera": {"position": [3,-6,3], "target": [0,0,1], "endPosition": [3,-5,3], "lens": 35},
            "lighting": {"warm": True, "power": 800}, "notes": []}


def test_defaults_keep_both_editions():
    assert video.DEFAULT_EDITIONS == ("procedural", "model-generated")


def test_finished_manifest_preserves_order_scene_and_duration():
    p = production()
    p["shots"].append({**p["shots"][0], "id": "closing", "sceneId": "hall"})
    source = video.source_plan({"entityType": "VideoProductionResult", "manifest": p}, "games/sample-game/assets/source/original/production.json")
    assert source["sceneIds"] == ["tower", "hall"]
    assert [s["id"] for s in source["shots"]] == ["entrance", "closing"]
    assert source["shots"][0]["duration"] == 3
    assert "The knight enters" in source["shots"][0]["direction"]
    assert source["edition"] == "procedural"


@pytest.mark.parametrize("change", ["foreign", "duplicate", "nan", "negative"])
def test_invalid_source_fails_closed(change):
    p, key = production(), "games/sample-game/assets/source/original/production.json"
    if change == "foreign":
        key = "games/foreign-game/assets/source/original/production.json"
    elif change == "duplicate":
        p["shots"] *= 2
    else:
        p["shots"][0]["outSeconds"] = float("nan") if change == "nan" else -1
    with pytest.raises(ValueError):
        video.source_plan(p, key)


def test_no_executable_or_external_asset_fields():
    value = design()
    value["objects"][0]["script"] = "untrusted code"
    from jsonschema import ValidationError
    with pytest.raises(ValidationError):
        video.validate_scene(value, 3, ["knight"])


@pytest.mark.parametrize("change", ["foreign-cast", "duplicate", "past-end", "negative-scale"])
def test_scene_identity_and_animation_guards(change):
    value = design()
    obj = value["objects"][0]
    if change == "foreign-cast":
        obj["characterId"] = "other-knight"
    elif change == "duplicate":
        value["objects"].append(copy.deepcopy(obj))
    elif change == "negative-scale":
        obj["scale"][0] = -1
    else:
        obj["keyframes"] = [{"time": 4, "position": [0,0,1], "rotation": [0,0,0], "scale": [1,1,1]}]
    with pytest.raises(ValueError):
        video.validate_scene(value, 3, ["knight"])


def test_nonfinite_scene_data_is_rejected():
    value = design()
    value["objects"][0]["position"][0] = float("nan")
    with pytest.raises(ValueError, match="Nonfinite"):
        video.validate_scene(value, 3, ["knight"])


@pytest.mark.parametrize("field", ["camera", "lighting"])
def test_nonfinite_camera_and_lighting_rejected(field):
    value = design()
    if field == "camera":
        value[field]["position"][0] = float("nan")
    else:
        value[field]["power"] = float("nan")
    with pytest.raises(ValueError, match="Nonfinite"):
        video.validate_scene(value, 3, ["knight"])


def test_ready_queue_only_uses_completed_preflight(monkeypatch):
    from panther_journal import character_details
    def api(_config, _method, endpoint, **_kw):
        if endpoint == "/games":
            return {"games": [{"id": "sample-game"}]}
        return {"tasks": [{"stage": "video-generation-packets", "status": "DONE", "output": {"key": "pin"}},
                          {"stage": "video-preflight", "status": "RUNNING"}]}
    monkeypatch.setattr(video.cloud, "api", api)
    monkeypatch.setattr(character_details, "pages", lambda *_a: [{"status": "READY_FOR_VIDEO_DISCUSSION", "episodeDestination": True, "jobId": "job", "raw": {"key": "raw"}, "createdAt": 10}])
    assert list(video.ready_sources({})) == []


def test_queue_activation_and_terminal_cache_skip_historical_work(monkeypatch):
    from panther_journal import character_details
    def api(_config, _method, endpoint, **_kw):
        if endpoint == "/games":
            return {"games": [{"id": "sample-game"}]}
        pytest.fail("Must not request already handled/historical jobs")
    monkeypatch.setattr(video.cloud, "api", api)
    monkeypatch.setattr(character_details, "pages", lambda *_a: [{"status": "READY_FOR_VIDEO_DISCUSSION", "episodeDestination": True, "jobId": "job", "createdAt": 10, "raw": {"key": "raw"}}])
    assert list(video.ready_sources({}, completed_after=11)) == []
    assert list(video.ready_sources({}, completed_jobs={"job": "done"})) == []


def test_publication_verifies_immutable_source_before_render(tmp_path, monkeypatch):
    p = tmp_path / "source.json"
    p.write_text(json.dumps(production()))
    monkeypatch.setattr(video.cloud, "configuration", lambda: {})
    monkeypatch.setattr(video.cloud, "api", lambda *_a, **_kw: {"size": 1, "sha256": "changed"})
    monkeypatch.setattr(video, "execute", lambda *_a, **_kw: pytest.fail("Must not render changed input"))
    result = CliRunner().invoke(video.render, [str(p), "--source-key", "games/sample-game/assets/p/original/p.json", "--work-dir", str(tmp_path)])
    assert result.exit_code != 0
    assert "immutable Panther source" in result.output


def test_procedural_score_is_real_stereo_pcm(tmp_path):
    import wave
    source = {"shots": [{"duration": .1}]}
    path = video.soundtrack(tmp_path, source)
    with wave.open(str(path)) as stream:
        assert stream.getnchannels() == 2
        assert stream.getnframes() == 2400
        assert any(stream.readframes(2400))


def test_review_failure_never_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "finish", lambda *_a: (_ for _ in ()).throw(ValueError("Rejected")))
    monkeypatch.setattr(video.cloud.upload, "callback", lambda *_a: pytest.fail("Must not upload"))
    with pytest.raises(ValueError, match="Rejected"):
        video.publish(tmp_path, {})


def test_procedural_installer_is_separate_pinned_worker(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("editorial_installer", Path(__file__).parents[1] / "ops/editorial-worker/install.py")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    definition = installer.service_definition(tmp_path / "release", tmp_path / "state", tmp_path, "procedural")
    assert definition["Label"] == "place.panther.procedural-worker"
    assert definition["ProgramArguments"][1:3] == ["videos", "procedural-worker"]
    assert definition["StartInterval"] == 300
    assert set(definition["EnvironmentVariables"]) == {"PATH", "HOME", "PYTHONUNBUFFERED"}
    assert installer.service_definition(tmp_path, tmp_path, tmp_path)["Label"] == "place.panther.editorial-worker"


def test_completed_packet_uses_owned_scenes_not_unowned_labels():
    packet = {"entityType": "EditorialArtifact", "stage": "video-generation-packets", "structuralValidation": "passed",
        "gameId": "sample-game", "sessionId": "sample-session", "payload": {
            "episode": {"title": "The tower", "scenes": [{"id": "tower", "prompt": "Enter", "characterIds": ["knight"], "shotIds": ["01A-entrance"]}]},
            "shots": [{"shotId": "01A-entrance", "description": "The knight walks.", "durationSeconds": 3}]}}
    source = video.source_plan(packet, "games/sample-game/assets/packet/original/packet.json")
    assert source["sceneIds"] == ["tower"]
    assert source["shots"][0]["id"] == "01a-entrance"
    packet["payload"]["shots"].append({"shotId": "02A-extra", "description": "Unused", "durationSeconds": 3})
    with pytest.raises(ValueError, match="unowned"):
        video.source_plan(packet, "games/sample-game/assets/packet/original/packet.json")
