import copy
import importlib
import hashlib
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
    monkeypatch.setenv("CATALOG_READERS", "example-operator,example-editor,example-reader")
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
    return job, unpack(
        request(m, "POST /editorial-jobs/claim", {"workflowVersion": PLAN["version"]})
    )


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


def test_large_preserved_word_evidence_can_start_editorial_without_truncation(editorial):
    m = editorial
    original = raw()
    original["segments"][0]["wordAttribution"] = {"evidence": "x" * (3 * 1024**2)}
    key = "games/test-game/assets/test-recording/original/detailed-raw.json"
    put(m, key, json.dumps(original).encode(), "application/json")
    result = request(m, "POST /editorial-jobs", {"gameId": "test-game", "rawKey": key})
    assert result["statusCode"] == 200
    job = unpack(result)
    assert job["raw"]["size"] > 2 * 1024**2


def test_leases_callback_redaction_and_expiry(editorial):
    m = editorial
    job, claim = queued(m)
    assert "taskToken" not in json.dumps(claim)
    assert unpack(request(m, "POST /editorial-jobs/claim"))["task"] is None
    assert request(m, "POST /editorial-jobs/claim", username="example-editor")["statusCode"] == 403
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
        "workflowVersion": PLAN["version"],
        "publicationStatus": "accepted",
        "structuralValidation": "passed",
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
    import browse_index

    db = browse_index.table()
    db.delete_item(
        Key={
            "pk": browse_index.partition("test-game", "all"),
            "sk": "games/other-game/assets/game-context/original/context.json",
        }
    )
    db.put_item(Item={"pk": f"v{browse_index.VERSION}#catalog", "sk": "ready"})
    for kind, category in [
        ("game-context", "reference"),
        ("test-script", "reference"),
        ("novel-chapter", "grounded-adaptation"),
    ]:
        key = f"games/test-game/assets/{kind}/original/context.json"
        db.put_item(
            Item={
                "pk": browse_index.partition("test-game", "all"),
                "sk": key,
                "payload": json.dumps(
                    {"key": key, "kind": kind, "size": 2, "metadata": {"category": category}}
                ),
            }
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


def test_context_schema_cannot_select_catalog_paths_or_invent_asset_keys():
    import jsonschema

    empty = worker.stage_schema("context", {"candidates": [], "raw": {}})["properties"]["selectedKeys"]
    jsonschema.validate([], empty)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(["catalog.players"], empty)
    bounded = worker.stage_schema("context", {"candidates": [{"key": "exact-key"}]})["properties"][
        "selectedKeys"
    ]
    jsonschema.validate(["exact-key"], bounded)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(["invented-key"], bounded)


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


@pytest.mark.parametrize("multi_source", [False, True])
def test_all_worker_stages_with_synthetic_artifacts(tmp_path, monkeypatch, multi_source):
    original = raw()
    storage = {"raw": original}
    completed = []
    catalog = {
        "players": [{"id": "person", "name": "Person"}],
        "characters": [{"id": "hero", "name": "Synthetic Hero"}],
    }
    selected = {
        "id": "official-pair",
        "appearanceId": "ordinary",
        "appearanceRevision": "b" * 32,
        "revision": "c" * 32,
        "portraitKey": "games/test-game/assets/portrait/original/portrait.png",
        "modelKey": None,
        "sourceKey": None,
        "provenanceKey": None,
    }

    def api(config, method, route, **kwargs):
        if route == "/game":
            return catalog
        if route == "/editorial-context":
            return {"items": [], "cursor": None}
        if route == "/character-versions":
            return {"schemaVersion": 2, "current": selected["id"], "selections": [selected]}
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
            "uncertainties": ["Separate synthetic editorial note"],
            "decisions": [],
            "selectedKeys": [],
            "shots": [],
            "edits": [],
        }
        if stage in PLAN["video"]:
            report["evidenceIds"] = ["catalog"]
        if stage == "video-source-brief":
            report["sourceFacts"] = []
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
    if multi_source:
        second = copy.deepcopy(original)
        second["segments"][0]["playerId"] = None
        storage["second.json"] = second
        storage["selected-context.json"] = {"lore": "Synthetic source fact."}
        job.update(
            rawSources=[{"key": "raw"}, {"key": "second.json"}],
            selectedContext=[{"key": "selected-context.json"}],
            creation={
                "schemaVersion": 1,
                "target": "video",
                "title": "River crossing",
                "brief": "A dramatic scene.",
            },
        )
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
    assert seen_inputs["context"]["catalog"]["officialArtwork"]["hero"] == selected
    assert (
        storage["context.json"]["payload"]["evidence"]["catalog"]["officialArtwork"]["hero"]
        == selected
    )
    assert storage["novel-chapter.md"] == storage["novel-chapter.json"]["payload"]["chapter"]
    assert "Separate synthetic editorial note" not in storage["novel-chapter.md"]
    assert storage["novel-chapter.json"]["payload"]["review"]["uncertainties"]
    assert storage["raw"] == original
    corrected = storage["corrected-transcript.json"]["payload"]["transcript"]
    if multi_source:
        assert corrected["sourceTranscripts"][0]["transcript"] == original
        assert corrected["segments"][1]["playerId"] is None
        assert (
            storage["context.json"]["payload"]["evidence"]["selected-context.json"]["content"]
            == storage["selected-context.json"]
        )
        assert "selected-context.json" in storage["context.json"]["sourceKeys"]
        assert all("second.json" in storage[f"{stage}.json"]["sourceKeys"] for stage in STAGES)
        assert seen_inputs["video-treatment"]["creation"]["title"] == "River crossing"
    else:
        assert corrected["segments"] == original["segments"]
    assert "novel-chapter" not in seen_inputs["video-treatment"]["priorStages"]
    assert storage["video-storyboards.json"]["payload"]["animaticTimeline"][0]["duration"] == 5
    assert (
        storage["video-voice-casting.json"]["payload"]["voiceProfiles"][0]["generationAuthorized"]
        is False
    )
    assert all(storage[f"{stage}.json"]["videoGenerationAuthorized"] is False for stage in STAGES)
    assert all(storage[f"{stage}.json"]["publicationStatus"] == "accepted" for stage in STAGES)


def report(**changes):
    return {
        "passed": True,
        "title": "Synthetic",
        "markdown": "Working text",
        "evidenceIds": ["raw"],
        "uncertainties": [],
        "decisions": [],
        "selectedKeys": [],
        "shots": [],
        "edits": [],
        **changes,
    }


def test_review_revises_actual_transcript_and_preserves_history(tmp_path, monkeypatch):
    original = raw()
    original["segments"].append({**original["segments"][0], "start": 3, "end": 4})
    edit = {
        "segmentIndex": 0,
        "before": original["segments"][0]["text"],
        "after": "Ask Captain Cade. I have 13 left.",
        "reason": "Roster spelling",
        "evidenceIds": ["catalog"],
    }
    proposal = report(edits=[edit])
    initial = apply_corrections(original, proposal, {"catalog"})
    calls = []

    def ai(folder, stage, inputs, heartbeat):
        calls.append(stage)
        if stage == "correction":
            assert inputs["revisionFeedback"]["review"]["passed"] is False
            return report(edits=[edit, {**edit, "segmentIndex": 1}])
        consistent = all("Cade" in s["text"] for s in inputs["candidate"]["segments"])
        return report(
            passed=consistent, markdown="Fix all occurrences" if not consistent else "Consistent"
        )

    monkeypatch.setattr(worker, "agent", ai)
    result, candidate, history, status = worker.autonomous_stage(
        tmp_path,
        "corrected-transcript",
        {
            "raw": original,
            "context": {"catalog": {}},
            "candidate": initial,
            "priorStages": {"correction": proposal},
        },
        lambda: None,
    )
    assert calls == ["corrected-transcript", "correction", "corrected-transcript"]
    assert result["passed"] and status == "accepted"
    assert history[0]["result"]["passed"] is False
    assert all("Cade" in s["text"] for s in candidate["segments"])
    assert all("Kade" in s["text"] for s in original["segments"])


def test_chapter_review_revises_manuscript_not_just_pass_flag(tmp_path, monkeypatch):
    seen = []

    def ai(folder, stage, inputs, heartbeat):
        if stage == "novel-proof":
            return report(markdown="Revised complete chapter")
        seen.append(inputs["candidate"])
        return report(passed=inputs["candidate"].startswith("Revised"))

    monkeypatch.setattr(worker, "agent", ai)
    result, candidate, history, status = worker.autonomous_stage(
        tmp_path,
        "novel-chapter",
        {
            "raw": raw(),
            "context": {"catalog": {}},
            "candidate": "Original chapter",
            "priorStages": {},
        },
        lambda: None,
    )
    assert seen == ["Original chapter", "Revised complete chapter"]
    assert candidate == "Revised complete chapter" and status == "accepted"
    assert len(history) == 3


@pytest.mark.parametrize(
    "stage", ["correction", "corrected-transcript", "novel-chapter", "video-preflight"]
)
def test_persistent_disagreement_continues_honestly_with_notes(tmp_path, monkeypatch, stage):
    monkeypatch.setattr(
        worker, "agent", lambda *args: report(passed=False, markdown="Needs improvement")
    )
    original = raw()
    result, candidate, history, status = worker.autonomous_stage(
        tmp_path,
        stage,
        {
            "raw": original,
            "context": {"catalog": {}},
            "candidate": original if stage == "corrected-transcript" else "Chapter",
            "priorStages": {},
        },
        lambda: None,
    )
    assert status == "accepted-with-notes" and not result["passed"]
    assert len(history) == (5 if stage in {"corrected-transcript", "novel-chapter"} else 3)
    if stage in {"correction", "corrected-transcript"}:
        assert candidate["segments"] == original["segments"]
        assert not candidate["corrections"]


def test_invalid_ai_edits_cannot_escape_guards(tmp_path, monkeypatch):
    original = raw()
    invalid = report(
        edits=[
            {
                "segmentIndex": 0,
                "before": original["segments"][0]["text"],
                "after": "Ask Captain Cade. I have 30 left.",
                "reason": "Guess",
                "evidenceIds": ["catalog"],
            }
        ]
    )
    monkeypatch.setattr(worker, "agent", lambda *args: invalid)
    result, _, history, status = worker.autonomous_stage(
        tmp_path,
        "correction",
        {"raw": original, "context": {"catalog": {}}, "priorStages": {}},
        lambda: None,
    )
    assert result["edits"] == [] and status == "accepted-with-notes"
    assert all("Numerical" in h["validationError"] for h in history)


def test_invalid_output_defers_automatically_instead_of_accepting(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "agent", lambda *args: report(evidenceIds=["invented-source"]))
    with pytest.raises(worker.local.Deferred):
        worker.autonomous_stage(
            tmp_path, "novel-draft", {"raw": raw(), "priorStages": {}}, lambda: None
        )


def test_context_schema_does_not_constrain_other_string_fields():
    import jsonschema

    schema = worker.stage_schema("context", {"candidates": [], "raw": {}})
    jsonschema.validate(
        report(evidenceIds=["raw", "catalog"], uncertainties=["Ambiguous name"]), schema
    )


def test_old_worker_cannot_claim_new_workflow(editorial):
    job, claimed = queued(editorial)
    lease = {"jobId": job["jobId"], "stage": "context", "lease": claimed["lease"]}
    unpack(request(editorial, "POST /editorial-jobs/defer", lease))
    editorial.table.update_item(
        Key={"pk": "TASKS", "sk": f"{job['jobId']}:context"},
        UpdateExpression="SET notBefore = :zero",
        ExpressionAttributeValues={":zero": 0},
    )
    assert unpack(request(editorial, "POST /editorial-jobs/claim"))["task"] is None
    assert unpack(
        request(editorial, "POST /editorial-jobs/claim", {"workflowVersion": PLAN["version"]})
    )["task"]


def test_cloud_accepts_notes_without_falsifying_review(editorial):
    job, claim = queued(editorial)
    key = f"games/test-game/assets/editorial-{job['jobId'][:32]}-notes/original/context.json"
    envelope = {
        "jobId": job["jobId"],
        "stage": "context",
        "workflowVersion": PLAN["version"],
        "passed": False,
        "publicationStatus": "accepted",
        "structuralValidation": "passed",
        "videoGenerationAuthorized": False,
    }
    body = {"jobId": job["jobId"], "stage": "context", "lease": claim["lease"], "outputKey": key}
    put(editorial, key, json.dumps(envelope).encode(), "application/json")
    assert request(editorial, "POST /editorial-jobs/complete", body)["statusCode"] == 400
    envelope["publicationStatus"] = "accepted-with-notes"
    put(editorial, key, json.dumps(envelope).encode(), "application/json")
    assert unpack(request(editorial, "POST /editorial-jobs/complete", body))["ok"]
    assert editorial.read("TASKS", f"{job['jobId']}:context")["status"] == "DONE"


def test_creation_pins_multiple_sources_and_context_idempotently(editorial):
    m = editorial
    keys = []
    for number in range(2):
        key = f"games/test-game/assets/source-{number}/original/raw.json"
        value = raw()
        if number:
            value.update(entityType="BrowserTranscript", mode="final", sourceKeys=["audio-source"])
            value["segments"][0]["playerId"] = None
        put(m, key, json.dumps(value).encode(), "application/json")
        keys.append(key)
    context = "games/test-game/assets/context/original/context.json"
    put(m, context, b"{}", "application/json")
    import base64

    m.media.s3.put_object(
        Bucket=m.media.BUCKET_NAME,
        Key=context,
        Body=b"{}",
        ChecksumAlgorithm="SHA256",
        Metadata={
            "kind": "game-context",
            "panther": base64.b64encode(json.dumps({"category": "reference"}).encode()).decode(),
        },
    )
    creation = {
        "schemaVersion": 1,
        "target": "novel",
        "title": "The crossing",
        "brief": "An intimate point of view.",
        "sourceKeys": keys,
        "contextKeys": [context],
    }
    first = unpack(
        request(m, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})
    )
    second = unpack(
        request(m, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})
    )
    assert first["jobId"] == second["jobId"]
    assert first["workflowVersion"] == PLAN["version"]
    assert [ref["key"] for ref in first["rawSources"]] == keys
    assert first["selectedContext"][0]["key"] == context
    assert first["videoGenerationAuthorized"] is False
    creation["brief"] = "A different direction."
    revised = unpack(
        request(m, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})
    )
    assert revised["jobId"] != first["jobId"]
    m.internal({"operation": "finish", "jobId": first["jobId"]})
    assert m.read("RUNS", first["jobId"])["status"] == "NOVEL_READY"


def test_creation_rejects_repeated_foreign_or_unfinished_inputs(editorial):
    m = editorial
    body, job = submitted(m)
    creation = {
        "schemaVersion": 1,
        "target": "video",
        "title": "Project",
        "brief": "",
        "sourceKeys": [body["rawKey"], body["rawKey"]],
        "contextKeys": [],
    }
    assert (
        request(m, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})[
            "statusCode"
        ]
        == 400
    )
    creation["sourceKeys"] = ["games/other-game/assets/source/original/raw.json"]
    assert (
        request(m, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})[
            "statusCode"
        ]
        == 400
    )
    value = raw()
    value.update(entityType="BrowserTranscript", mode="live", sourceKeys=["audio"])
    key = "games/test-game/assets/source/original/browser.json"
    put(m, key, json.dumps(value).encode(), "application/json")
    creation["sourceKeys"] = [key]
    assert (
        request(m, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})[
            "statusCode"
        ]
        == 400
    )
    assert (
        request(
            m,
            "POST /editorial-jobs",
            {"gameId": "test-game", "creation": creation},
            username="unknown-reader",
        )["statusCode"]
        == 403
    )


def test_source_bundle_preserves_local_time_unknown_speakers_and_raw_bytes():
    first = raw()
    second = raw()
    second["segments"][0]["playerId"] = None
    originals = copy.deepcopy([first, second])
    refs = [{"key": "first"}, {"key": "second"}]
    bundle = worker.transcript_bundle(
        [first, second], refs, {"jobId": "a" * 64, "gameId": "test-game", "sessionId": "collection"}
    )
    assert [segment["start"] for segment in bundle["segments"]] == [1, 1]
    assert bundle["segments"][1]["playerId"] is None
    assert bundle["segments"][1]["sourceKey"] == "second"
    assert bundle["segments"][1]["sourceSegmentIndex"] == 0
    assert [first, second] == originals
    corrected = apply_corrections(bundle, {"edits": [], "uncertainties": []}, {})
    assert corrected["sourceTranscripts"][1]["transcript"] == second


def test_catalog_reader_can_follow_progress_but_cannot_create(editorial):
    m = editorial
    body, job = submitted(m)
    result = unpack(
        request(m, "GET /editorial-jobs", username="example-reader", query={"jobId": job["jobId"]})
    )
    assert result["job"]["jobId"] == job["jobId"]
    assert "taskToken" not in json.dumps(result)
    assert request(m, "POST /editorial-jobs", body, username="example-reader")["statusCode"] == 403
    listed = unpack(
        request(m, "GET /editorial-jobs", username="example-reader", query={"gameId": "test-game"})
    )
    assert [value["jobId"] for value in listed["jobs"]] == [job["jobId"]]


def scene_creation_fixture(editorial, monkeypatch):
    import boto3
    from types import SimpleNamespace
    import sys

    game = {
        "id": "test-game",
        "name": "Synthetic game",
        "ruleset": "Synthetic system",
        "visualStyle": "anime",
    }
    boto3.resource("dynamodb").Table("test-job-catalog").put_item(
        Item={"pk": "GAMES", "sk": "test-game", **game}
    )
    scene = {
        "schemaVersion": 1,
        "entityType": "Scene",
        "gameId": "test-game",
        "episodeId": "episode-one",
        "id": "scene-one",
        "name": "Cross the river",
        "description": "A storm approaches.",
        "revision": "c" * 32,
    }

    def pin(game_id, reference):
        if game_id != scene["gameId"] or reference != {
            "episodeId": scene["episodeId"],
            "sceneId": scene["id"],
            "revision": scene["revision"],
        }:
            raise ValueError("Unknown scene revision")
        return copy.deepcopy(scene)

    monkeypatch.setitem(sys.modules, "video_scenes", SimpleNamespace(pin_scene=pin))
    creation = {
        "schemaVersion": 2,
        "target": "video",
        "sceneRef": {"episodeId": "episode-one", "sceneId": "scene-one", "revision": "c" * 32},
        "characterIds": [],
        "sourceKeys": [],
        "contextKeys": [],
    }
    return creation, scene


def test_prompt_only_video_pins_scene_without_inventing_transcript(editorial, monkeypatch):
    creation, scene = scene_creation_fixture(editorial, monkeypatch)
    first = unpack(
        request(editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})
    )
    second = unpack(
        request(editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})
    )
    assert first["jobId"] == second["jobId"]
    # Adding map support must not re-identify existing non-map jobs on retry.
    normalized = {**creation, "title": scene["name"], "brief": scene["name"]}
    old_identity = [[], [], normalized, [], editorial.pin_game("test-game"), scene, PLAN["version"]]
    assert (
        first["jobId"]
        == hashlib.sha256(json.dumps(old_identity, sort_keys=True).encode()).hexdigest()
    )
    assert first["raw"] is None and first["rawSources"] == []
    assert first["sourceMode"] == "prompt"
    assert first["creation"]["brief"] == scene["name"]
    assert first["creation"]["title"] == scene["name"]
    assert first["selectedScene"] == scene
    assert first["videoGenerationAuthorized"] is False
    assert first["gameContext"]["visualStyles"][0]["id"] == "anime"
    assert first["workflowVersion"] == PLAN["version"]
    creation["brief"] = "Cross at dusk, in a tense silence."
    revised = unpack(
        request(editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})
    )
    assert revised["jobId"] != first["jobId"]
    assert revised["selectedScene"] == first["selectedScene"]
    invalid = {**creation, "sceneRef": {**creation["sceneRef"], "revision": "d" * 32}}
    assert (
        request(editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": invalid})[
            "statusCode"
        ]
        == 400
    )
    invalid = {k: v for k, v in creation.items() if k != "sceneRef"}
    assert (
        request(editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": invalid})[
            "statusCode"
        ]
        == 400
    )


def test_selected_cast_pins_structured_revision_and_official_appearance(editorial, monkeypatch):
    import boto3
    import character_details
    import character_appearances as looks

    creation, _ = scene_creation_fixture(editorial, monkeypatch)
    creation["characterIds"] = ["hero"]
    db = boto3.resource("dynamodb").Table("test-job-catalog")
    db.put_item(
        Item={
            "pk": "GAME#test-game",
            "sk": "CHARACTER#hero",
            "entityType": "Character",
            "schemaVersion": 2,
            "gameId": "test-game",
            "id": "hero",
            "name": "Synthetic hero",
            "detailsRevision": "a" * 32,
            "detailsJson": json.dumps(character_details.empty_details()),
        }
    )
    browse = looks.browse_index.table()
    browse.put_item(Item={"pk": "character-looks-migration#test-game#hero", "sk": "complete"})
    portrait = "games/test-game/assets/portrait/original/image.png"
    import base64

    editorial.media.s3.put_object(
        Bucket=editorial.media.BUCKET_NAME,
        Key=portrait,
        Body=b"synthetic-image",
        ContentType="image/png",
        ChecksumAlgorithm="SHA256",
        Metadata={
            "panther": base64.b64encode(json.dumps({"characterIds": ["hero"]}).encode()).decode()
        },
    )
    physical = {
        "id": "ordinary",
        "name": "Ordinary",
        "revision": "b" * 32,
        "description": "Recorded appearance",
        "state": {},
        "developedFrom": None,
        "story": {"date": None, "eventId": None, "sessionId": None},
    }
    selection = {
        "id": "pair-one",
        "appearanceId": "ordinary",
        "appearanceRevision": "b" * 32,
        "portraitKey": portrait,
        "modelKey": None,
        "revision": "e" * 32,
    }
    browse.put_item(
        Item={
            **looks.records.pointer(
                looks.PREFIX, "test-game", looks.kind("activation", "hero"), "current"
            ),
            "payload": json.dumps({"appearanceId": "ordinary", "selectionId": "pair-one"}),
        }
    )
    browse.put_item(
        Item={
            **looks.records.pointer(
                looks.PREFIX, "test-game", looks.kind("selection", "hero"), "pair-one"
            ),
            "payload": json.dumps(selection),
        }
    )
    browse.put_item(
        Item={
            "pk": f"{looks.PREFIX}-history#{looks.kind('appearance', 'hero')}#test-game#ordinary",
            "sk": "b" * 32,
            "payload": json.dumps(physical),
        }
    )
    job = unpack(
        request(editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})
    )
    pin = job["selectedCharacters"][0]
    assert pin["detailsRevision"] == "a" * 32
    assert pin["appearance"]["selection"] == selection
    assert pin["appearanceAssets"][0]["key"] == portrait
    assert pin["appearanceAssets"][0]["sha256"]
    changed = {**creation, "characterIds": ["unknown-hero"]}
    assert (
        request(editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": changed})[
            "statusCode"
        ]
        == 400
    )


def test_creative_context_excludes_technical_reference_categories(editorial):
    from creative_context import eligible

    for kind in ("provenance", "migration-audit", "generation-verification"):
        assert not eligible(kind, {"category": "reference"})
        assert not eligible(
            "game-context", {"category": "reference", "extra": {"artifactType": kind}}
        )
        assert not eligible(kind, {"extra": {"contextUse": "creative-evidence"}})
    assert not eligible("document", {"category": "reference", "extra": {"contextUse": "evidence"}})
    assert eligible("game-context", {"category": "reference"})
    assert eligible("document", {"extra": {"contextUse": "creative-evidence"}})
    assert not eligible("lore", {"extra": {"relationshipRole": "intermediate"}})
    assert not eligible("lore", {"category": "creative-reimagining"})
    body, _ = submitted(editorial)
    import base64

    for kind in ("provenance", "migration-audit", "generation-verification"):
        key = f"games/test-game/assets/{kind}/original/context.json"
        editorial.media.s3.put_object(
            Bucket=editorial.media.BUCKET_NAME,
            Key=key,
            Body=b"{}",
            ContentType="application/json",
            ChecksumAlgorithm="SHA256",
            Metadata={
                "kind": kind,
                "panther": base64.b64encode(
                    json.dumps({"category": "reference"}).encode()
                ).decode(),
            },
        )
        creation = {
            "schemaVersion": 1,
            "target": "novel",
            "title": "Chapter",
            "brief": "",
            "sourceKeys": [body["rawKey"]],
            "contextKeys": [key],
        }
        assert (
            request(
                editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation}
            )["statusCode"]
            == 400
        )


def test_automatic_creative_context_ignores_technical_indexed_records(editorial, monkeypatch):
    import base64
    import browse_index
    from unittest.mock import Mock

    db = browse_index.table()
    db.put_item(Item={"pk": f"v{browse_index.VERSION}#catalog", "sk": "ready"})
    for kind in ("game-context", "provenance", "migration-audit", "generation-verification"):
        key = f"games/test-game/assets/{kind}/original/context.json"
        metadata = {"category": "reference"}
        editorial.media.s3.put_object(
            Bucket=editorial.media.BUCKET_NAME,
            Key=key,
            Body=b"{}",
            ChecksumAlgorithm="SHA256",
            Metadata={
                "kind": kind,
                "panther": base64.b64encode(json.dumps(metadata).encode()).decode(),
            },
        )
        db.put_item(
            Item={
                "pk": browse_index.partition("test-game", "all"),
                "sk": key,
                "payload": json.dumps({"key": key, "size": 2, "kind": kind, "metadata": metadata}),
            }
        )
    head = Mock(wraps=editorial.media.s3.head_object)
    monkeypatch.setattr(editorial.media.s3, "head_object", head)
    page = editorial.context_page("test-game", None, 9999999999)
    assert [item["kind"] for item in page["items"]] == ["game-context"]
    assert head.call_count == 1


@pytest.mark.parametrize("with_transcript", [False, True])
@pytest.mark.parametrize("with_map", [False, True])
def test_prompt_led_scene_planning_preprocesses_optional_sources_and_pins_cast(
    tmp_path, monkeypatch, with_transcript, with_map
):
    scene = {
        "episodeId": "pilot",
        "sceneId": "arrival",
        "revision": "b" * 32,
        "name": "A lantern on the quay",
        "description": "A scout arrives in the rain.",
        "type": "map" if with_map else "opener",
    }
    portrait = "games/test-game/assets/scout-portrait/original/portrait.png"
    cast = [
        {
            "characterId": "scout",
            "name": "Lantern Scout",
            "detailsRevision": "c" * 32,
            "details": {
                "overview": "A cautious fictional scout.",
                "backstory": "Raised near the quay.",
            },
            "appearance": {
                "appearance": {"id": "raincoat", "description": "A blue raincoat"},
                "selection": {"id": "pair-one", "revision": "d" * 32, "portraitKey": portrait},
            },
            "appearanceAssets": [
                {"key": portrait, "sha256": "e" * 64, "size": 100, "contentType": "image/png"}
            ],
        }
    ]
    source_key = "games/test-game/assets/source/original/raw.json"
    original = raw()
    original["providerResponse"] = {"audit": "DO NOT ADD THIS TO THE STORY"}
    reference = {"key": source_key, "sha256": "f" * 64, "size": 100}
    storage, fetched, completed, seen = {source_key: copy.deepcopy(original)}, [], [], {}
    job = {
        "jobId": "a" * 64,
        "gameId": "test-game",
        "sessionId": None,
        "workflowVersion": PLAN["version"],
        "contextCutoff": 1,
        "sourceMode": "transcript" if with_transcript else "prompt",
        "raw": reference if with_transcript else None,
        "rawSources": [reference] if with_transcript else [],
        "selectedContext": [],
        "selectedCharacters": cast,
        "selectedScene": scene,
        "creation": {
            "schemaVersion": 2,
            "target": "video",
            "title": scene["name"],
            "brief": "Open on the scout arriving by the quay.",
        },
    }

    map_reference = {
        "key": "games/test-game/assets/map/original/map.png",
        "sha256": "map-checksum",
        "size": 100,
        "contentType": "image/png",
        "role": "first-frame",
        "instructions": "Treat the input image as a map. Show red footprints.",
    }
    if with_map:
        job["selectedMap"] = map_reference
        job["creation"]["sceneRef"] = {
            "episodeId": "pilot",
            "sceneId": "arrival",
            "revision": "b" * 32,
        }
    downloaded_maps = []

    def download(config, ref, destination):
        downloaded_maps.append(ref)
        destination.write_bytes(b"verified-map-fixture")

    def api(config, method, route, **kwargs):
        assert route in {"/editorial-jobs/heartbeat", "/editorial-jobs/complete"}
        if route.endswith("complete"):
            completed.append(kwargs["json"])
        return {}

    def fetch(config, ref, *args):
        fetched.append(ref["key"])
        return copy.deepcopy(storage[ref["key"]])

    def upload(config, file, job, kind, category, sources, suffix):
        key = file.name
        storage[key] = json.loads(file.read_text()) if key.endswith(".json") else file.read_text()
        return key

    def agent(folder, stage, inputs, heartbeat):
        seen[stage] = copy.deepcopy(inputs)
        if with_map and stage in PLAN["video"]:
            assert inputs["mapInput"] == map_reference
            assert (folder.parent / "map-first-frame.png").read_bytes() == b"verified-map-fixture"
        value = report(
            evidenceIds=["creation", "catalog"], markdown="A source-attributed scene plan."
        )
        if stage == "video-generation-packets" and with_map:
            value["renderPrompt"] = "Red footprints move along the marked road."
        if stage == "video-source-brief":
            value["sourceFacts"] = (
                [
                    {
                        "sourceKey": source_key,
                        "segmentIndex": 0,
                        "fact": "An explicitly supplied source event.",
                        "uncertainty": "Speech remains unverified.",
                    }
                ]
                if with_transcript
                else []
            )
        if stage in {"video-shot-list", "video-storyboards"}:
            value["shots"] = [
                {
                    "sceneId": "arrival",
                    "shotId": "arrival-1",
                    "durationSeconds": 4,
                    "description": "Scout on the quay",
                    "camera": "wide",
                    "color": "#223344",
                    "subjects": [],
                }
            ]
        return value

    monkeypatch.setattr(worker.cloud, "api", api)
    monkeypatch.setattr(worker, "fetch", fetch)
    monkeypatch.setattr(worker, "upload", upload)
    monkeypatch.setattr(worker, "agent", agent)
    monkeypatch.setattr(worker.local, "download", download)
    artifacts = {}
    for stage in ["context", *PLAN["video"]]:
        worker.process(
            {},
            tmp_path,
            {
                "job": job,
                "task": {"stage": stage},
                "artifacts": dict(artifacts),
                "lease": "synthetic",
            },
        )
        artifacts[stage] = {"key": completed[-1]["outputKey"]}
    assert storage[source_key] == original
    assert "correction" not in seen and "corrected-transcript" not in seen
    assert (
        "raw" not in seen["video-treatment"] and "sourceTranscripts" not in seen["video-treatment"]
    )
    assert "providerResponse" not in json.dumps(seen["video-source-brief"])
    assert "detailsRevision" not in json.dumps(seen["video-treatment"]["context"])
    assert seen["video-treatment"]["context"]["catalog"]["characters"][0]["name"] == "Lantern Scout"
    assert seen["video-treatment"]["context"]["catalog"]["scene"]["type"] == (
        "map" if with_map else "opener"
    )
    assert "passed" not in seen["video-treatment"]["priorStages"]["video-source-brief"]
    final = storage["video-generation-packets.json"]
    assert final["characterReferences"] == cast and final["sceneReference"] == scene
    if with_map:
        assert len(downloaded_maps) == len(PLAN["video"])
        assert map_reference["key"] in final["sourceKeys"]
        assert final["mapReference"] == map_reference
        assert final["payload"]["mapGenerationPacket"]["firstFrame"]["sha256"] == "map-checksum"
    assert portrait in final["sourceKeys"] and final["videoGenerationAuthorized"] is False
    assert final["rawReference"] == (reference if with_transcript else None)
    if with_transcript:
        fact = storage["video-source-brief.json"]["payload"]["sourceFacts"][0]
        assert (
            fact["start"] == original["segments"][0]["start"]
            and fact["playerId"] == original["segments"][0]["playerId"]
        )
        assert (
            fetched.count(source_key) == 1
        )  # context and preprocessing; never later composition stages.
    else:
        assert seen["context"]["raw"] is None
        assert seen["video-source-brief"]["sourceTranscripts"] == []
        assert final["rawReferences"] == []


def test_source_preprocessing_cannot_cite_invented_transcript_segments(tmp_path, monkeypatch):
    monkeypatch.setattr(
        worker,
        "agent",
        lambda *args: report(
            evidenceIds=["creation"],
            sourceFacts=[
                {
                    "sourceKey": "invented",
                    "segmentIndex": 0,
                    "fact": "Not observed",
                    "uncertainty": "",
                }
            ],
        ),
    )
    with pytest.raises(worker.local.Deferred, match="No structurally valid"):
        worker.autonomous_stage(
            tmp_path,
            "video-source-brief",
            {
                "creation": {"brief": "A scene"},
                "context": {},
                "sourceTranscripts": [],
                "priorStages": {},
            },
            lambda: None,
        )


def test_scene_planning_upload_keeps_exact_scene_metadata(tmp_path, monkeypatch):
    output = tmp_path / "video-generation-packets.json"
    output.write_text('{"shots": []}')
    scene_ref = {"episodeId": "episode-one", "sceneId": "scene-one", "revision": "c" * 32}
    captured = {}

    def callback(**kwargs):
        captured.update(json.loads(kwargs["metadata"].read_text()))

    monkeypatch.setattr(worker.cloud.upload, "callback", callback)
    job = {
        "jobId": "a" * 64,
        "gameId": "test-game",
        "sessionId": None,
        "creation": {"schemaVersion": 2, "sceneRef": scene_ref},
    }
    source = "games/test-game/assets/portrait/original/front.png"
    worker.upload({}, output, job, "video-generation-packets", "video", [source], "test-run")
    extra = captured["extra"]
    assert extra["sceneRef"] == scene_ref
    assert extra["episodeId"] == "episode-one" and extra["sceneId"] == "scene-one"
    assert captured["sourceKeys"] == [source]
    assert captured["sessionId"] is None


def test_map_generation_pins_actual_image_and_requires_reference(editorial, monkeypatch):
    import video_scenes

    creation, scene = scene_creation_fixture(editorial, monkeypatch)
    scene["type"] = "map"
    # Restore the real bounded image validator to the scene-reference fixture module.
    __import__("sys").modules["video_scenes"].map_asset = video_scenes.map_asset
    assert (
        request(editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})[
            "statusCode"
        ]
        == 400
    )
    key = "games/test-game/assets/journey-map/original/map.png"
    put(editorial, key, b"synthetic-map-image", "image/png")
    scene["mapAssetKey"] = key
    first = unpack(
        request(editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})
    )
    ref = first["selectedMap"]
    assert ref["key"] == key and ref["role"] == "first-frame"
    assert ref["sha256"] and ref["size"] == len(b"synthetic-map-image")
    assert "Treat the input image as a map" in ref["instructions"]
    assert "red footprints" in ref["instructions"] and "red dot" in ref["instructions"]
    assert first["videoGenerationAuthorized"] is False
    assert (
        unpack(
            request(
                editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation}
            )
        )["jobId"]
        == first["jobId"]
    )
    # A checksummed change cannot silently reuse the old job; its pinned reference is unchanged.
    put(editorial, key, b"changed-map-bytes", "image/png")
    changed = unpack(
        request(editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})
    )
    assert changed["jobId"] != first["jobId"]
    assert first["selectedMap"]["sha256"] != changed["selectedMap"]["sha256"]


def test_map_planning_contract_preserves_actual_visual_reference():
    from panther_journal.editorial_contract import BRIEFS

    reference = {
        "key": "games/test-game/assets/map/original/map.png",
        "sha256": "exact",
        "role": "first-frame",
    }
    catalog = worker.pinned_cast({"gameId": "test-game", "selectedMap": reference})
    assert catalog["mapInput"] == reference
    assert "mapInput.key and sha256" in BRIEFS["video-generation-packets"]
    assert "red footprints" in BRIEFS["video-generation-packets"]


def test_map_packet_binds_first_frame_without_a_second_asset_selection():
    reference = {
        "key": "games/test-game/assets/map/original/map.png",
        "sha256": "exact",
        "size": 100,
        "contentType": "image/png",
        "instructions": "Treat the input image as a map. Show a red dot and red footprints.",
    }
    job = {
        "selectedMap": reference,
        "creation": {
            "sceneRef": {"episodeId": "trip", "sceneId": "route", "revision": "a" * 32},
            "brief": "Travel from the harbor to the hills",
        },
    }
    packet = worker.map_generation_packet(job, {"renderPrompt": "Follow the marked road"})
    assert packet["firstFrame"] == {
        k: reference[k] for k in ("key", "sha256", "size", "contentType")
    }
    assert packet["sourceKeys"] == [reference["key"]]
    assert "Travel from the harbor to the hills" in packet["prompt"]
    assert "red footprints" in packet["prompt"] and "marked road" in packet["prompt"]
    assert packet["generationAuthorized"] is False


def test_map_agent_attaches_verified_image_to_codex(tmp_path, monkeypatch):
    attempt = tmp_path / "revision-01-video-treatment"
    attempt.mkdir()
    image = tmp_path / "map-first-frame.png"
    image.write_bytes(b"synthetic-verified-raster")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        (attempt / "agent-result.json").write_text(json.dumps(report()))
        return 0

    monkeypatch.setattr(worker.local, "codex_base", lambda: ["codex"])
    monkeypatch.setattr(worker.local, "run_process", run)
    inputs = {"context": {}, "creation": {}, "mapInput": {"key":"games/test-game/assets/map/original/map.png", "contentType": "image/png"}}
    worker.agent(attempt, "video-treatment", inputs, lambda: None)
    assert commands[0][commands[0].index("--image") + 1] == str(image)
    image.unlink()
    missing_attempt = tmp_path / "revision-02-video-treatment"
    missing_attempt.mkdir()
    with pytest.raises(ValueError, match="Pinned map image is missing"):
        worker.agent(missing_attempt, "video-treatment", inputs, lambda: None)


def test_prompt_led_novel_has_optional_sources_and_no_required_title(editorial):
    creation = {
        "schemaVersion": 3,
        "target": "novel",
        "brief": "Write a tense chapter about the harbor crossing.",
        "sourceKeys": [],
        "contextKeys": [],
    }
    job = unpack(
        request(editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation})
    )
    assert job["creation"]["title"] == creation["brief"]
    assert job["raw"] is None and job["sourceMode"] == "prompt"
    assert (
        unpack(
            request(
                editorial, "POST /editorial-jobs", {"gameId": "test-game", "creation": creation}
            )
        )["jobId"]
        == job["jobId"]
    )
    for change in [{"brief": ""}, {"target": "video"}, {"title": ""}]:
        assert (
            request(
                editorial,
                "POST /editorial-jobs",
                {"gameId": "test-game", "creation": {**creation, **change}},
            )["statusCode"]
            == 400
        )

def test_prompt_overlay_reconstructs_complete_candidate_without_duplicate_speech():
    from panther_journal import editorial as worker
    original = raw()
    original['segments'][0]['text'] = 'Long original speech. ' * 20000
    original['segments'][0]['timingNote'] = 'Approximate source interval.'
    corrected = copy.deepcopy(original)
    corrected.update(artifactType='corrected-transcript', corrections=[{
        'segmentIndex': 0, 'before': original['segments'][0]['text'], 'after': 'Corrected speech.'}],
        uncertainties=['Identity remains provisional.'])
    corrected['segments'][0]['text'] = 'Corrected speech.'
    inputs = {'raw': original, 'candidate': corrected,
              'priorStages': {'corrected-transcript': {'transcript': corrected}}}
    before = copy.deepcopy(inputs)
    result = worker.prompt_projection(inputs)
    overlay = result['candidate']
    assert overlay['entityType'] == 'TranscriptCorrectionOverlay'
    assert overlay['readingBase'] == 'raw' and 'segments' not in overlay
    rows = [dict(zip(result['raw']['segmentFields'], row, strict=True)) for row in result['raw']['segments']]
    for edit in overlay['corrections']:
        assert rows[edit['segmentIndex']]['text'] == edit['before']
        rows[edit['segmentIndex']]['text'] = edit['after']
    assert rows == worker.reading_transcript(corrected)['segments']
    assert result['priorStages']['corrected-transcript']['transcript']['entityType'] == 'TranscriptCorrectionOverlay'
    assert overlay['uncertainties'] == corrected['uncertainties']
    assert inputs == before
    # Identity/timing/text changes not represented by validated deltas cannot
    # masquerade as an equivalent projection against this base.
    for field, value in [('playerId', None), ('start', 100), ('text', 'Unaccounted change')]:
        changed = copy.deepcopy(corrected)
        changed['segments'][0][field] = value
        assert worker.correction_overlay(changed, original) is None
    changed = copy.deepcopy(corrected)
    changed['players'] = [{'id': 'someone-else', 'name': 'Different fictional person'}]
    assert worker.correction_overlay(changed, original) is None


def test_prompt_projection_keeps_multisource_timing_identity_and_prompt_only_inputs():
    from panther_journal import editorial as worker

    first, second = raw(), raw()
    second["segments"][0]["playerId"] = None
    second["segments"][0]["timingNote"] = "Source-local interval."
    refs = [{"key": "first"}, {"key": "second"}]
    bundle = worker.transcript_bundle(
        [first, second], refs,
        {"jobId": "a" * 64, "gameId": "test-game", "sessionId": "collection"},
    )
    before = copy.deepcopy(bundle)
    projected = worker.prompt_projection({"raw": bundle})["raw"]
    rows = [
        dict(zip(projected["segmentFields"], row, strict=True))
        for row in projected["segments"]
    ]
    # Missing fields use null in positional rows; every present speech fact is exact.
    for source, projected_row in zip(bundle["segments"], rows, strict=True):
        assert all(projected_row[key] == value for key, value in source.items())
    assert [row["sourceKey"] for row in rows] == ["first", "second"]
    assert rows[1]["playerId"] is None
    assert projected["sourceKeys"] == ["first", "second"]
    assert bundle == before
    prompt_only = {"raw": None, "creation": {"brief": "A river crossing."}}
    assert worker.prompt_projection(prompt_only) == prompt_only


def test_cloud_publication_uses_canonical_episode_store_and_live_lease(editorial):
    import time
    import organization_records
    import browse_index
    from botocore.exceptions import ClientError
    m = editorial
    _, job = submitted(m)
    assert job['episodeDestination'] and job['episodeRef']
    stage = 'video-generation-packets'
    task = {'pk': 'TASKS', 'sk': job['jobId'] + ':' + stage, 'jobId': job['jobId'], 'gameId': job['gameId'],
            'stage': stage, 'status': 'RUNNING', 'lease': 'exact-lease', 'leaseUntil': int(time.time()) + 600, 'actor': 'fictional-worker'}
    m.table.put_item(Item=task)
    packet = {'gameId': job['gameId'], 'jobId': job['jobId'], 'stage': stage, 'workflowVersion': PLAN['version'],
              'passed': True, 'structuralValidation': 'passed', 'publicationStatus': 'accepted', 'videoGenerationAuthorized': False,
              'sourceKeys': [job['raw']['key']], 'payload': {
                'shots': [{'shotId': 'SC01_SH01', 'sceneId': 'SC01', 'durationSeconds': 8, 'description': 'The gates open.', 'camera': 'Wide', 'color': '#223344', 'subjects': []}],
                'episode': {'schemaVersion': 1, 'title': 'Arrival', 'synopsis': 'The party reaches the gate.', 'scenes': [
                    {'id': 'arrival', 'title': 'Arrival', 'type': 'general', 'prompt': 'The gates open.', 'narration': 'At dusk, they arrived.',
                     'characterIds': [], 'referenceKeys': [job['raw']['key']], 'shotIds': ['SC01_SH01']}]}}}
    key = f"games/test-game/assets/editorial-{job['jobId'][:32]}-packet/original/packet.json"
    put(m, key, json.dumps(packet).encode(), 'application/json')
    body = {'jobId': job['jobId'], 'stage': stage, 'lease': task['lease'], 'outputKey': key}
    expired = {**task, 'leaseUntil': 0}
    m.table.put_item(Item=expired)
    with pytest.raises(ClientError):
        m.update(task, body, 'complete')
    db = browse_index.table()
    target = organization_records.pointer('episode-scenes-v1', job['gameId'], 'episode', job['episodeRef']['episodeId'])
    assert organization_records.decode(db.get_item(Key=target)['Item'])['sceneIds'] == []
    m.table.put_item(Item=task)
    assert m.update(task, body, 'complete') == {'ok': True}
    episode = organization_records.decode(db.get_item(Key=target)['Item'])
    assert episode['sceneIds'] == ['arrival']
    scene = organization_records.decode(db.get_item(Key=organization_records.pointer('episode-scenes-v1', job['gameId'], 'scene#' + episode['id'], 'arrival'))['Item'])
    assert scene['planningState'] == 'needs-approval' and scene['selectedOutputKey'] is None
    # A replay between publication and task completion must preserve later edits.
    m.table.put_item(Item=task)
    changed = {**episode, 'name': 'Human edited title', 'revision': 'f' * 32}
    db.put_item(Item={**target, 'revision': changed['revision'], 'payload': json.dumps(changed)})
    assert m.update(task, body, 'complete') == {'ok': True}
    assert organization_records.decode(db.get_item(Key=target)['Item'])['name'] == 'Human edited title'


def test_cloud_chapter_adaptation_pins_canonical_bytes_and_creates_one_episode(editorial, monkeypatch):
    import manual_chapters
    import browse_index
    import organization_records
    m = editorial
    __import__('boto3').resource('dynamodb').Table('test-job-catalog').put_item(Item={'pk':'GAMES','sk':'test-game','id':'test-game','name':'Fictional campaign'})
    catalog_db = __import__('boto3').resource('dynamodb').Table('test-job-catalog')
    catalog_db.put_item(Item={'pk':'GAME#test-game','sk':'CHARACTER#fictional-hero','id':'fictional-hero'})
    monkeypatch.setattr(m,'pin_cast',lambda game, ids:[{'characterId':identity,'name':'Fictional hero','details':{},'appearanceAssets':[]} for identity in ids])
    identity = 'c' * 64
    key = 'games/test-game/assets/chapter-source/original/chapter.json'
    original = json.dumps({'gameId': 'test-game', 'markdown': 'The travelers arrive at dusk.'}).encode()
    put(m, key, original, 'application/json')
    monkeypatch.setattr(manual_chapters, 'read', lambda game, chapter, media: {'id': identity, 'gameId': 'test-game', 'title': 'At dusk', 'details': {'artifact': {'key': key}}})
    body = {'gameId': 'test-game', 'creation': {'schemaVersion': 4, 'target': 'video', 'chapterId': identity}}
    result = request(m, 'POST /editorial-jobs', body)
    assert result['statusCode'] == 200
    job = unpack(result)
    assert unpack(request(m, 'POST /editorial-jobs', body))['jobId'] == job['jobId']
    assert job['chapterSource']['sha256'] == __import__('base64').b64encode(hashlib.sha256(original).digest()).decode()
    assert job['rawSources'] == [] and job['videoGenerationAuthorized'] is False
    assert [person['characterId'] for person in job['selectedCharacters']] == ['fictional-hero']
    pointer = organization_records.pointer('episode-scenes-v1', 'test-game', 'episode', job['episodeRef']['episodeId'])
    episode = organization_records.decode(browse_index.table().get_item(Key=pointer)['Item'])
    assert episode['production']['state'] == 'planning' and episode['sceneIds'] == []
    assert request(m, 'POST /editorial-jobs', {**body, 'gameId': 'another-game'})['statusCode'] == 400
    assert request(m, 'POST /editorial-jobs', {'gameId': 'test-game', 'creation': {**body['creation'], 'markdown': 'Unpinned text'}})['statusCode'] == 400


def test_scene_pipeline_publishes_only_its_owned_scene_and_replay_preserves_edits(editorial):
    import time
    import browse_index
    import organization_records
    from test_episode_destination import source
    m = editorial
    _, job = submitted(m)
    previous = {'entityType':'Scene','schemaVersion':1,'gameId':job['gameId'], 'episodeId':'existing-episode', 'id':'arrival', 'revision':'b'*32, 'name':'Human title', 'selectedOutputKey':'retained-footage', 'generationInputs':{'durationSeconds':7.5}}
    job.update(selectedScene=previous, episodeDestination=True)
    from decimal import Decimal
    stored = json.loads(json.dumps({**job,'pk':'RUNS','sk':job['jobId']}), parse_float=Decimal)
    m.table.put_item(Item=stored)
    pointer = organization_records.pointer('episode-scenes-v1', job['gameId'], 'scene#existing-episode', 'arrival')
    db = browse_index.table()
    db.put_item(Item={**pointer,'revision':previous['revision'],'payload':json.dumps(previous)})
    _, packet, _ = source()
    packet.update(gameId=job['gameId'],jobId=job['jobId'],workflowVersion=PLAN['version'],passed=True,sourceKeys=[job['raw']['key']])
    packet['payload']['episode']['scenes'][0]['referenceKeys']=[job['raw']['key']]
    stage='video-generation-packets'
    task={'pk':'TASKS','sk':job['jobId']+':'+stage,'jobId':job['jobId'],'gameId':job['gameId'],'stage':stage,'status':'RUNNING','lease':'owned-scene-lease','leaseUntil':int(time.time())+600,'actor':'fictional-worker'}
    m.table.put_item(Item=task)
    key=f"games/test-game/assets/editorial-{job['jobId'][:32]}-scene-packet/original/packet.json"
    put(m,key,json.dumps(packet).encode(),'application/json')
    body={'jobId':job['jobId'],'stage':stage,'lease':task['lease'],'outputKey':key}
    assert m.update(task,body,'complete')=={'ok':True}
    scene=organization_records.decode(db.get_item(Key=pointer)['Item'])
    assert scene['name']=='Human title' and scene['episodeId']=='existing-episode'
    assert scene['generationInputs']['durationSeconds']==7.5 and scene['selectedOutputKey']=='retained-footage'
    assert scene['storyboard']['origin']=='ai' and scene['planningState']=='needs-approval'
    changed={**scene,'name':'Later edit','revision':'f'*32}
    db.put_item(Item={**pointer,'revision':changed['revision'],'payload':json.dumps(changed)})
    m.table.put_item(Item=task)
    assert m.update(task,body,'complete')=={'ok':True}
    assert organization_records.decode(db.get_item(Key=pointer)['Item'])['name']=='Later edit'


def test_pinned_chapter_input_alias_is_valid_evidence_without_allowing_foreign_sources(tmp_path,monkeypatch):
    report={'passed':True,'title':'Context','markdown':'Use the pinned story.','evidenceIds':['sourceChapter'],'uncertainties':[],'decisions':[],'selectedKeys':[],'shots':[],'edits':[]}
    monkeypatch.setattr(worker,'agent',lambda *args:copy.deepcopy(report))
    inputs={'catalog':{},'candidates':[],'sourceChapter':{'key':'games/test-game/assets/chapter/original/chapter.json','markdown':'The travelers arrive.'}}
    assert worker.autonomous_stage(tmp_path,'context',inputs,lambda:None)[0]['passed']
    report['evidenceIds']=['games/foreign-game/assets/chapter/original/chapter.json']
    foreign=tmp_path/'foreign'
    foreign.mkdir()
    with pytest.raises(worker.local.Deferred,match='No structurally valid'):
        worker.autonomous_stage(foreign,'context',inputs,lambda:None)


def test_generation_schema_constrains_all_citations_to_pinned_evidence():
    inputs={"catalog":{},"candidates":[],"sourceChapter":{"key":"games/test-game/assets/chapter/original/chapter.json"}}
    schema=worker.stage_schema('video-source-brief',inputs)
    allowed={'catalog','sourceChapter',inputs['sourceChapter']['key']}
    assert set(schema['properties']['evidenceIds']['items']['enum'])==allowed
    for field in ('decisions','edits'):
        assert set(schema['properties'][field]['items']['properties']['evidenceIds']['items']['enum'])==allowed
    assert 'enum' not in worker.SCHEMA['properties']['evidenceIds']['items']
    assert "enum" not in schema["properties"]["title"]
    assert "enum" not in schema["properties"]["uncertainties"]["items"]


def test_storyboard_generation_schema_matches_renderer_palette_and_blocking():
    import jsonschema
    shot={'sceneId':'arrival','shotId':'dock','durationSeconds':8,'description':'Wet wharf','camera':'Wide','color':'#182838','subjects':[{'label':'Guide','x':0.5,'y':0.5}]}
    jsonschema.validate(shot,worker.SHOT)
    for change in ({'color':'cold blues'},{'durationSeconds':0},{'durationSeconds':121},{'subjects':[{'label':'Guide','x':1.1,'y':0.5}]}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**shot,**change},worker.SHOT)
