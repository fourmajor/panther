import copy
import importlib
import json

import pytest

from panther_journal import editorial as worker
from panther_journal.editorial_contract import (
    PLAN,
    STAGES,
    apply_corrections,
    voice_profile_proposals,
)
from panther_journal.capture_audit import audit, packet_gaps
from test_model_jobs import broker, put, request, unpack  # noqa: F401


@pytest.fixture
def editorial(broker, monkeypatch):  # noqa: F811
    monkeypatch.setenv("EDITORIAL_TABLE", "test-jobs")
    monkeypatch.setenv("EDITORIAL_PLAN", json.dumps(PLAN))
    monkeypatch.delitem(__import__("sys").modules, "editorial_jobs", raising=False)
    return importlib.import_module("editorial_jobs")


def raw():
    return {
        "entityType": "PlayerTranscript",
        "artifactType": "raw-transcript",
        "gameId": "test-game",
        "sessionId": "test-session",
        "recordingId": "recording-" + "a" * 32,
        "sourceParts": [{"file": "part-0000.flac"}],
        "segments": [
            {
                "start": 1,
                "end": 2,
                "playerId": "person",
                "text": "Ask Captain Kade. I have 13 left.",
            }
        ],
    }


def submitted(m):
    key = "games/test-game/assets/test-recording/original/raw.json"
    put(m, key, json.dumps(raw()).encode(), "application/json")
    body = {"gameId": "test-game", "rawKey": key}
    return body, unpack(request(m, "POST /editorial-jobs", body))


def queued(m, stage="context"):
    body, job = submitted(m)
    m.handler(
        {"operation": "dispatch", "jobId": job["jobId"], "stage": stage, "taskToken": "PRIVATE"},
        None,
    )
    return job, unpack(request(m, "POST /editorial-jobs/claim"))


def test_submission_is_idempotent_and_rejects_adaptation_and_cross_game(editorial):
    m = editorial
    body, job = submitted(m)
    assert unpack(request(m, "POST /editorial-jobs", body))["jobId"] == job["jobId"]
    assert request(m, "POST /editorial-jobs", {**body, "gameId": "other-game"})["statusCode"] == 400
    wrong = {**raw(), "artifactType": "corrected-transcript"}
    key = "games/test-game/assets/other/original/derived.json"
    put(m, key, json.dumps(wrong).encode(), "application/json")
    assert request(m, "POST /editorial-jobs", {**body, "rawKey": key})["statusCode"] == 400
    assert request(m, "POST /editorial-jobs", body, username="intruder")["statusCode"] == 403


def test_leases_callback_redaction_and_expiry(editorial):
    m = editorial
    job, claim = queued(m)
    assert "taskToken" not in json.dumps(claim)
    assert unpack(request(m, "POST /editorial-jobs/claim"))["task"] is None
    assert request(m, "POST /editorial-jobs/claim", username="other_stu")["statusCode"] == 403
    body = {"jobId": job["jobId"], "stage": "context", "lease": claim["lease"]}
    assert (
        request(m, "POST /editorial-jobs/heartbeat", body, actor="different")["statusCode"] == 400
    )
    assert unpack(request(m, "POST /editorial-jobs/heartbeat", body))["ok"]
    assert unpack(request(m, "POST /editorial-jobs/defer", body))["ok"]
    assert unpack(request(m, "POST /editorial-jobs/claim"))["task"] is None


def test_complete_only_same_run_checked_artifact_and_no_video_authorization(editorial):
    m = editorial
    job, claim = queued(m)
    body = {"jobId": job["jobId"], "stage": "context", "lease": claim["lease"]}
    key = f"games/test-game/assets/editorial-{job['jobId'][:32]}-attempt/original/context.json"
    envelope = {
        "jobId": job["jobId"],
        "stage": "context",
        "workflowVersion": 1,
        "passed": True,
        "videoGenerationAuthorized": True,
    }
    put(m, key, json.dumps(envelope).encode(), "application/json")
    assert (
        request(m, "POST /editorial-jobs/complete", {**body, "outputKey": key})["statusCode"] == 400
    )
    envelope["videoGenerationAuthorized"] = False
    put(m, key, json.dumps(envelope).encode(), "application/json")
    assert unpack(request(m, "POST /editorial-jobs/complete", {**body, "outputKey": key}))["ok"]
    assert m.read("TASKS", f"{job['jobId']}:context")["status"] == "DONE"
    # Lost acknowledgements cannot mutate completed work under an old lease.
    assert (
        request(m, "POST /editorial-jobs/complete", {**body, "outputKey": key})["statusCode"] == 400
    )


def test_context_excludes_holdouts_adaptations_and_other_games(editorial):
    m = editorial
    for kind, category, game in [
        ("game-context", "reference", "test-game"),
        ("test-script", "reference", "test-game"),
        ("novel-chapter", "grounded-adaptation", "test-game"),
        ("game-context", "reference", "other-game"),
    ]:
        import base64

        key = f"games/{game}/assets/{kind}/original/context.json"
        put(m, key, b"{}", "application/json")
        # Add fixture metadata without changing real assets.
        m.media.s3.put_object(
            Bucket=m.media.BUCKET_NAME,
            Key=key,
            Body=b"{}",
            ChecksumAlgorithm="SHA256",
            Metadata={
                "kind": kind,
                "panther": base64.b64encode(json.dumps({"category": category}).encode()).decode(),
            },
        )
    result = m.context_page("test-game", None, 9999999999)
    assert [c["kind"] for c in result["items"]] == ["game-context"]


def test_corrections_keep_players_timestamps_numbers_and_raw():
    original = raw()
    saved = copy.deepcopy(original)
    edits = {
        "edits": [
            {
                "segmentIndex": 0,
                "before": original["segments"][0]["text"],
                "after": "Ask Captain Cade. I have 13 left.",
                "reason": "Roster spelling",
                "evidenceIds": ["catalog"],
            }
        ]
    }
    result = apply_corrections(original, edits, {"catalog"})
    assert original == saved
    assert result["segments"][0]["playerId"] == "person"
    assert result["segments"][0]["start"] == 1
    edits["edits"][0]["after"] = "Ask Captain Cade. I have 30 left."
    with pytest.raises(ValueError, match="Numerical"):
        apply_corrections(original, edits, {"catalog"})
    with pytest.raises(ValueError, match="pinned evidence"):
        apply_corrections(original, edits, set())


def test_storyboard_is_safe_vector_and_rejects_invalid_coordinates():
    shot = {
        "sceneId": "s1",
        "shotId": "s1-a",
        "durationSeconds": 4,
        "camera": "wide",
        "description": "Door",
        "color": "#223344",
        "subjects": [{"label": "<script>", "x": 0.5, "y": 0.5}],
    }
    svg = worker.storyboard([shot])
    assert "&lt;script&gt;" in svg and "<script>" not in svg and "href=" not in svg
    shot["subjects"][0]["x"] = 2
    with pytest.raises(ValueError):
        worker.storyboard([shot])


def test_plan_has_editorial_order_and_hard_generation_stop():
    assert PLAN["correction"] == ["context", "correction", "corrected-transcript"]
    assert PLAN["novel"].index("novel-developmental-edit") < PLAN["novel"].index("novel-revision")
    assert PLAN["novel"][-1] == "novel-chapter"
    assert PLAN["video"][-1] == "video-preflight"
    assert len(STAGES) == len(set(STAGES))
    assert not any("generate-video" in s for s in STAGES)


def test_capture_audit_detects_pre_encoder_loss(tmp_path):
    (tmp_path / "recording.json").write_text(json.dumps({"parts": [{"duration": 13.5}]}))
    (tmp_path / "segments.csv").write_text("part-0000.wav,0,15\n")
    assert audit(tmp_path)["discrepancySeconds"] == 1.5
    assert audit(tmp_path)["status"] == "warning"
    log = "demuxer+tsfixup -> pkt_pts:0 duration:10666\ndemuxer+tsfixup -> pkt_pts:21333 duration:10666"
    assert packet_gaps(log)["gapCount"] == 1


def test_voice_proposals_separate_people_and_characters_without_inferred_consent():
    profiles = voice_profile_proposals(
        {
            "players": [{"id": "person", "name": "Person"}],
            "characters": [{"id": "hero", "name": "Hero"}],
        }
    )
    assert [p["subjectType"] for p in profiles] == ["player", "character"]
    assert len({p["id"] for p in profiles}) == 2
    assert all(
        p["consent"] == "not-recorded"
        and p["modelReference"] is None
        and p["generationAuthorized"] is False
        for p in profiles
    )


def test_negation_and_spoken_numbers_are_protected():
    original = raw()
    original["segments"][0]["text"] = "I do not have two keys, Kade."
    edit = {
        "segmentIndex": 0,
        "before": original["segments"][0]["text"],
        "after": "I do not have two keys, Cade.",
        "reason": "Name spelling",
        "evidenceIds": ["raw", "catalog"],
    }
    apply_corrections(original, {"edits": [edit]}, {"catalog"})
    for replacement in ["I do have two keys, Cade.", "I do not have three keys, Cade."]:
        with pytest.raises(ValueError, match="Negation"):
            apply_corrections(original, {"edits": [{**edit, "after": replacement}]}, {"catalog"})


def test_all_worker_stages_with_synthetic_artifacts(tmp_path, monkeypatch):
    original = raw()
    storage = {"raw": original}
    completed = []
    catalog = {"players": [{"id": "person", "name": "Person"}], "characters": []}

    def api(config, method, route, **kwargs):
        if route == "/game":
            return catalog
        if route == "/editorial-context":
            return {"items": [], "cursor": None}
        if route.endswith("complete"):
            completed.append(kwargs["json"])
        return {"ok": True}

    # Exercise cloud.api and Requests' real forwarding boundary, not just a permissive API mock.
    from types import SimpleNamespace
    from urllib.parse import urlparse
    import requests

    def transport(self, method, url, *, headers, timeout, allow_redirects, json=None, params=None):
        result = api({}, method, urlparse(url).path, json=json, params=params)
        return SimpleNamespace(status_code=200, json=lambda: result)

    monkeypatch.setattr(requests.Session, "request", transport)
    monkeypatch.setattr(worker.cloud, "token", lambda config: "synthetic-test-token")
    monkeypatch.setattr(
        worker, "fetch", lambda config, ref, *args: copy.deepcopy(storage[ref["key"]])
    )

    def upload(config, file, job, kind, category, sources, suffix):
        key = file.name
        storage[key] = json.loads(file.read_text()) if key.endswith(".json") else file.read_text()
        return key

    monkeypatch.setattr(worker, "upload", upload)
    seen_inputs = {}

    def agent(folder, stage, inputs, heartbeat):
        seen_inputs[stage] = inputs
        report = {
            "passed": True,
            "title": stage,
            "markdown": "Synthetic manuscript",
            "evidenceIds": ["raw", "catalog"],
            "uncertainties": [],
            "selectedKeys": [],
            "shots": [],
            "edits": [],
        }
        if stage in {"video-shot-list", "video-storyboards"}:
            report["shots"] = [
                {
                    "sceneId": "s1",
                    "shotId": "s1-a",
                    "durationSeconds": 5,
                    "description": "Synthetic panel",
                    "camera": "wide",
                    "color": "#223344",
                    "subjects": [],
                }
            ]
        return report

    monkeypatch.setattr(worker, "agent", agent)
    job = {
        "jobId": "a" * 64,
        "gameId": "test-game",
        "sessionId": "test-session",
        "workflowVersion": PLAN["version"],
        "contextCutoff": 1,
        "raw": {"key": "raw"},
    }
    artifacts = {}
    for stage in STAGES:
        worker.process(
            {"apiUrl": "https://synthetic.invalid"},
            tmp_path,
            {
                "job": job,
                "task": {"stage": stage},
                "artifacts": dict(artifacts),
                "lease": "private",
            },
        )
        artifacts[stage] = {"key": completed[-1]["outputKey"]}
    assert len(completed) == len(STAGES)
    assert storage["raw"] == original
    assert (
        storage["corrected-transcript.json"]["payload"]["transcript"]["segments"]
        == original["segments"]
    )
    assert "novel-chapter" not in seen_inputs["video-treatment"]["priorStages"]
    assert storage["video-storyboards.json"]["payload"]["animaticTimeline"][0]["duration"] == 5
    assert (
        storage["video-voice-casting.json"]["payload"]["voiceProfiles"][0]["generationAuthorized"]
        is False
    )
    assert all(storage[f"{stage}.json"]["videoGenerationAuthorized"] is False for stage in STAGES)
