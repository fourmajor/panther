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


def test_detailed_hair_features_remain_data_only():
    value = design()
    value["objects"][0]["features"] += ["curly-hair", "red-hair"]
    assert video.validate_scene(value, 3, ["knight"]) == value


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


def test_complete_source_document_changes_run_identity():
    original = production()
    before = video.source_plan(original, 'games/sample-game/assets/source/original/production.json')
    original['qualityEvidence'] = {'assessment': 'Updated immutable source evidence'}
    after = video.source_plan(original, 'games/sample-game/assets/source/original/production.json')
    assert before['shots'] == after['shots']
    assert before['sourceSha256'] != after['sourceSha256']


@pytest.mark.parametrize('duration', [.001, 31])
def test_source_rejects_unrenderable_duration(duration):
    original = production()
    original['shots'][0].update(inSeconds=0, outSeconds=duration)
    with pytest.raises(ValueError, match='one frame'):
        video.source_plan(original, 'games/sample-game/assets/source/original/production.json')


@pytest.mark.parametrize('identity', ['publication', 'review-assembly'])
def test_source_rejects_stage_identity_collision(identity):
    original = production()
    original['shots'][0]['id'] = identity
    with pytest.raises(ValueError, match='workflow stage'):
        video.source_plan(original, 'games/sample-game/assets/source/original/production.json')


@pytest.mark.parametrize('duration,width', [(1,1920), (float('nan'),1920), (3,640)])
def test_clip_verification_rejects_truncation_or_wrong_dimensions(tmp_path, monkeypatch, duration, width):
    monkeypatch.setattr(video.production, 'probe', lambda *_a: {'format': {'duration': duration},
        'streams': [{'codec_type': 'video', 'width': width, 'height':1080}]})
    with pytest.raises(ValueError, match='selected duration'):
        video.verify_clip(tmp_path/'clip.mp4',tmp_path,3)


def test_clip_verification_accepts_frame_rounding(tmp_path, monkeypatch):
    monkeypatch.setattr(video.production, 'probe', lambda *_a: {'format': {'duration': 3},
        'streams': [{'codec_type': 'video', 'width': 1920, 'height':1080}]})
    assert video.verify_clip(tmp_path/'clip.mp4',tmp_path,3.01) == 3


def test_worker_keeps_processing_after_malformed_packet(tmp_path, monkeypatch):
    monkeypatch.setattr(video.cloud, 'configuration', lambda: {})
    references = [{'key': f'games/sample-game/assets/{name}/original/packet.json', 'jobId':name} for name in ['bad','good']]
    monkeypatch.setattr(video, 'ready_sources', lambda *_a, **_kw: iter(references))
    monkeypatch.setattr(video.model_workflow,'download',lambda _cfg, ref, path: path.write_text(json.dumps({} if ref['jobId']=='bad' else production())))
    rendered=[]
    monkeypatch.setattr(video, 'execute', lambda source,*_a,**_kw: rendered.append(source))
    result=CliRunner().invoke(video.worker,['--work-dir',str(tmp_path),'--completed-after','0','--once'])
    assert result.exit_code == 0, result.output
    assert len(rendered) == 1
    registry=json.loads((tmp_path/'completed-jobs.json').read_text())
    assert registry['bad']['state'] == 'blocked'
    assert registry['good']['state'] == 'published'
    assert list((tmp_path/'inputs').glob('*-blocked.json'))


def test_walking_is_explicit_bounded_actor_data():
    value=design()
    value['objects'][0]['features'].append('walk')
    assert video.validate_scene(value,3,['knight']) == value


def test_native_walking_render_has_real_frames_and_joint_animation(tmp_path):
    import subprocess
    from panther_journal import model_workflow
    try:
        blender=model_workflow.native_blender()
    except Exception as error:
        if 'Install native Blender' not in str(error):
            raise
        pytest.skip('Native Blender not installed on this test host')
    value=design()
    hero=value['objects'][0]
    hero['features'].append('walk')
    hero['keyframes']=[{'time':t,'position':[x,0,1],'rotation':[0,0,0],'scale':[1,1,1]}
        for t,x in [(0,0),(.125,.1),(.25,.2)]]
    video.validate_scene(value,.25,['knight'])
    clip=video.render_shot(tmp_path,value,{'duration':.25})
    assert video.verify_clip(clip,tmp_path,.25) == .25
    assert len(list((tmp_path/'frames').glob('*.png'))) == 6
    check="import bpy; joints=[o for o in bpy.data.objects if o.name.startswith('Hip joint')]; assert len(joints)==2; bpy.context.scene.frame_set(1); first=[o.rotation_euler.x for o in joints]; bpy.context.scene.frame_set(4); last=[o.rotation_euler.x for o in joints]; assert first!=last; assert last[0]*last[1]<0; assert all(o.parent and o.children for o in joints)"
    completed=subprocess.run([str(blender),'--background','--threads','6','--disable-autoexec',str(tmp_path/'scene.blend'),'--python-exit-code','1','--python-expr',check],capture_output=True,text=True,timeout=60)
    assert completed.returncode == 0, completed.stdout+completed.stderr


def test_per_shot_review_does_not_demand_unsupplied_adjacent_cuts():
    scope=video.production.review_scope('procedural-shot-review')
    assert 'separate final assembled-film review' in scope
    assert 'requested action still fails' in scope
    final=video.production.review_scope('procedural-final-continuity')
    assert 'single-shot film has no cuts' in final


def review_report(status='pass'):
    return {'checks':[{'category':c,'status':status,'evidence':'Synthetic review evidence'} for c in video.production.CHECKS],
        'notes':[],'trimStart':0,'trimEnd':0,'brightness':0,'contrast':1,'saturation':1,'reason':'Synthetic review'}


def setup_candidates(monkeypatch, *, all_fail=False):
    attempts=[]
    def compile_scene(folder, source, shot, *, previous=None):
        attempts.append(previous)
        value=design()
        (folder/'scene.json').write_text(json.dumps(value))
        return value
    def render_scene(folder, value, shot):
        clip=folder/'clip.mp4'
        clip.write_bytes(folder.name.encode())
        (folder/'rendered.json').write_text(json.dumps({'sha256':video.production.digest(clip)}))
        return clip
    def review_scene(folder, source, shot):
        report=review_report('fail' if all_fail or folder.name=='01' else 'pass')
        directory=folder/'review'
        directory.mkdir(exist_ok=True)
        (directory/'review.json').write_text(json.dumps(report))
        return report
    monkeypatch.setattr(video,'compile_shot',compile_scene)
    monkeypatch.setattr(video,'render_shot',render_scene)
    monkeypatch.setattr(video,'review_shot',review_scene)
    return attempts


def test_failed_candidate_is_retained_and_actual_revision_is_selected(tmp_path,monkeypatch):
    attempts=setup_candidates(monkeypatch)
    source=video.source_plan(production(),'games/sample-game/assets/source/original/production.json')
    shot=source['shots'][0]
    selected=video.execute_shot(tmp_path,source,shot)
    assert selected.name=='02'
    assert (tmp_path/'entrance/attempts/01/failed.json').exists()
    assert attempts[0] is None and attempts[1]['review']['checks'][0]['status']=='fail'
    assert video.selected_target(tmp_path,shot)==selected
    assert json.loads((tmp_path/'entrance/selected.json').read_text())['attempt']==2
    (selected/'review/review.json').write_text(json.dumps(review_report('fail')))
    with pytest.raises(ValueError,match='review changed'):
        video.selected_target(tmp_path,shot)


def test_failed_candidates_stop_after_three_without_selection(tmp_path,monkeypatch):
    attempts=setup_candidates(monkeypatch,all_fail=True)
    source=video.source_plan(production(),'games/sample-game/assets/source/original/production.json')
    import click
    with pytest.raises(click.ClickException,match='Three procedural'):
        video.execute_shot(tmp_path,source,source['shots'][0])
    assert len(attempts)==3
    assert len(list((tmp_path/'entrance').glob('attempts/*/failed.json')))==3
    assert not (tmp_path/'entrance/selected.json').exists()
    # A resume uses the retained evidence rather than generating three more candidates.
    with pytest.raises(click.ClickException,match='Three procedural'):
        video.execute_shot(tmp_path,source,source['shots'][0])
    assert len(attempts)==3
