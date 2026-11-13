"""Smoke set: pipeline hand-offs, budget guards, and recovery that reuses finished stages."""

import base64
import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import boto3
import click
import pytest
import yaml
from moto import mock_aws

from panther_journal import narration, video
from panther_journal.editorial_contract import PLAN

ROOT = Path(__file__).parents[1]


def test_stage_handoff_follows_each_branch_in_order():
    source = (ROOT / "infra/lib/editorial-processing.ts").read_text()
    assert "sequence(plan.novel)" in source
    assert "sequence(plan.video)" in source
    assert "sequence(plan.correction" in source
    seen = []
    for branch in ("correction", "novel", "video"):
        stages = PLAN[branch]
        assert stages and stages == list(dict.fromkeys(stages))
        seen.extend(stages)
    assert len(seen) == len(set(seen))


def test_fal_cap_and_session_budget_refuse_overspend(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "ROOT", tmp_path / "private-video")

    class Billing:
        def billing(self):
            return {"account": "fal-example"}

    with video.database(initialize=True) as db:
        assert video.LIMIT_CENTS == 5000
        assert video.totals(db)["limitUsd"] == "50.00"
        video.check_budget(db, {"manifest": {}}, 5000)
        with pytest.raises(click.ClickException, match="configured budget"):
            video.check_budget(db, {"manifest": {}}, 5001)
    status = narration.create_budget(
        "session-one", "test-game", "10.00", "4.00", "Owner approved this session", Billing()
    )
    assert status["capCents"] == 1000
    assert status["otherHeldCents"] == 400
    plan = {
        "manifest": {"projectId": "session-one", "gameId": "test-game"},
        "billingAccount": "fal-example",
    }
    with video.database() as db:
        video.check_budget(db, plan, 400)
        with pytest.raises(click.ClickException, match="narration remains protected"):
            video.check_budget(db, plan, 401)
    with pytest.raises(click.ClickException, match="already exists"):
        narration.create_budget(
            "session-one", "test-game", "10.00", "5.00", "A different allowance", Billing()
        )
    shots = [
        {
            "id": f"shot-{index}",
            "model": "h3-max-image",
            "durationSeconds": 5,
            "resolution": "768P",
            "maxAttempts": 1,
        }
        for index in range(16)
    ]
    video.assert_planned_cut(shots, session=True)
    estimate = video.reviewed_estimate(shots)
    assert estimate["estimatedCents"] == 640
    assert estimate["estimatedCents"] <= 900
    with pytest.raises(ValueError, match="8–16"):
        video.assert_planned_cut(shots[:7], session=True)
    video.assert_planned_cut([{**shot, "durationSeconds": 10} for shot in shots[:8]], session=True)
    with pytest.raises(ValueError, match="2–12"):
        video.assert_planned_cut([{**shots[0], "durationSeconds": 13}])
    under = [{**shot, "durationSeconds": 4} for shot in shots[:14]]
    with pytest.raises(ValueError, match="60–90"):
        video.assert_planned_cut(under, session=True)
    video.assert_planned_cut([shots[0]])
    guard = narration.create_budget(
        "session-cut", "test-game", "20.00", "9.00", "Session video guard", Billing()
    )
    assert guard["otherHeldCents"] == 900
    guarded = {
        "manifest": {"projectId": "session-cut", "gameId": "test-game"},
        "billingAccount": "fal-example",
    }
    with video.database() as db:
        video.check_budget(db, guarded, estimate["estimatedCents"])
        with pytest.raises(click.ClickException, match="narration remains protected"):
            video.check_budget(db, guarded, 901)


def test_deploy_choice_hotswaps_code_and_fully_deploys_infrastructure():
    def choose(files, base=""):
        env = os.environ.copy()
        env.pop("PANTHER_DEPLOY_BASE", None)
        if base:
            env["PANTHER_DEPLOY_BASE"] = base
        done = subprocess.run(
            ["bash", str(ROOT / "ops/deploy.sh"), "--decide"],
            input="".join(f"{name}\n" for name in files),
            text=True,
            capture_output=True,
            check=True,
            env=env,
        )
        return done.stdout.strip()

    script = (ROOT / "ops/deploy.sh").read_text()
    assert "--hotswap-fallback" in script
    assert choose(["infra/lambda/media-api/editorial_jobs.py", "web/media-explorer/app.js"]) == (
        "hotswap 0"
    )
    assert choose(["infra/lib/editorial-processing.ts"]) == "full 0"
    assert choose(["infra/bin/panther.ts"]) == "full 0"
    assert choose(["infra/lib/panther-domain-stack.ts"]) == "full 1"
    assert choose(["src/panther_journal/video.py"], base="0" * 40) == "full 1"


def test_main_deploy_does_not_wait_on_tests_or_accept_pull_requests():
    workflow = yaml.load(
        (ROOT / ".github/workflows/deploy.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert set(workflow["on"]) == {"push"}
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert "pull_request" not in workflow
    smoke = workflow["jobs"]["smoke"]
    deploy = workflow["jobs"]["deploy"]
    assert smoke["continue-on-error"] == "true"
    assert smoke["if"] == "github.repository == 'fourmajor/panther'"
    assert "needs" not in deploy
    assert deploy["if"] == smoke["if"]
    assert deploy["permissions"]["id-token"] == "write"
    role = next(
        step["with"]["role-to-assume"]
        for step in deploy["steps"]
        if step.get("with", {}).get("role-to-assume")
    )
    assert role == "arn:aws:iam::223663280572:role/PantherGitHubDeploy"
    assert not (ROOT / ".github/workflows/ci.yml").exists()


@pytest.fixture
def broker(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("ASSET_BUCKET_NAME", "test-panther-assets")
    monkeypatch.setenv("JOB_TABLE", "test-jobs")
    monkeypatch.setenv("ASSET_BROWSE_TABLE", "test-job-browse")
    monkeypatch.setenv("CATALOG_TABLE", "test-job-catalog")
    monkeypatch.setenv("MODEL_PUBLISHERS", "example-operator,example-editor")
    monkeypatch.setenv("MODEL_WORKERS", "example-operator")
    monkeypatch.setenv(
        "STATE_MACHINE_ARN", "arn:aws:states:us-west-2:123456789012:stateMachine:test"
    )
    monkeypatch.syspath_prepend(str(ROOT / "infra/lambda/media-api"))
    with mock_aws():
        dynamo = boto3.client("dynamodb")
        for name in ("test-jobs", "test-job-browse", "test-job-catalog"):
            dynamo.create_table(
                TableName=name,
                BillingMode="PAY_PER_REQUEST",
                KeySchema=[
                    {"AttributeName": "pk", "KeyType": "HASH"},
                    {"AttributeName": "sk", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "pk", "AttributeType": "S"},
                    {"AttributeName": "sk", "AttributeType": "S"},
                ],
            )
        boto3.client("s3").create_bucket(
            Bucket="test-panther-assets",
            CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
        )
        for module in ("index", "model_jobs"):
            monkeypatch.delitem(sys.modules, module, raising=False)
        imported = importlib.import_module("model_jobs")
        imported.media.s3 = imported.media.raw_s3
        yield imported


@pytest.fixture
def editorial(broker, monkeypatch):
    monkeypatch.setenv("EDITORIAL_TABLE", "test-jobs")
    monkeypatch.setenv("CATALOG_READERS", "example-operator,example-editor,example-reader")
    monkeypatch.setenv("EDITORIAL_PLAN", json.dumps(PLAN))
    monkeypatch.delitem(sys.modules, "editorial_jobs", raising=False)
    return importlib.import_module("editorial_jobs")


def request(module, route, body=None, username="example-operator"):
    return module.handler(
        {
            "routeKey": route,
            "body": json.dumps(body or {}),
            "requestContext": {
                "authorizer": {"jwt": {"claims": {"sub": "test-owner", "cognito:username": username}}}
            },
        },
        None,
    )


def unpack(result):
    assert result["statusCode"] == 200, result
    return json.loads(result["body"])


def put(module, key, data=b"image", content_type="image/png"):
    metadata = {"characterIds": ["test-person"], "extra": {"appearanceId": "original"}}
    result = module.media.s3.put_object(
        Bucket=module.media.BUCKET_NAME,
        Key=key,
        Body=data,
        ContentType=content_type,
        ChecksumAlgorithm="SHA256",
        ChecksumSHA256=base64.b64encode(hashlib.sha256(data).digest()).decode(),
        Metadata={"panther": base64.b64encode(json.dumps(metadata).encode()).decode()},
    )
    if "/assets/" in key:
        import browse_index

        browse_index.table().put_item(
            Item={
                "pk": browse_index.partition("test-game", "all"),
                "sk": key,
                "observed": 1,
                "payload": json.dumps(
                    {"key": key, "size": len(data), "contentType": content_type, "metadata": metadata}
                ),
            }
        )
    return result


def raw():
    return {
        "entityType": "PlayerTranscript",
        "artifactType": "raw-transcript",
        "gameId": "test-game",
        "sessionId": "test-session",
        "recordingId": "recording-" + "a" * 32,
        "sourceParts": [{"file": "part-0000.flac"}],
        "segments": [{"start": 1, "end": 2, "playerId": "person", "text": "Ask Captain Kade."}],
    }


def submitted(module):
    key = "games/test-game/assets/test-recording/original/raw.json"
    put(module, key, json.dumps(raw()).encode(), "application/json")
    body = {"gameId": "test-game", "rawKey": key}
    return body, unpack(request(module, "POST /editorial-jobs", body))


def done_stage(module, job, stage, payload):
    envelope = {
        "schemaVersion": 1,
        "entityType": "EditorialArtifact",
        "jobId": job["jobId"],
        "gameId": job["gameId"],
        "stage": stage,
        "workflowVersion": job["workflowVersion"],
        "passed": True,
        "publicationStatus": "accepted",
        "structuralValidation": "passed",
        "videoGenerationAuthorized": False,
        "payload": payload,
    }
    body = json.dumps(envelope).encode()
    key = f"games/test-game/assets/editorial-{job['jobId'][:32]}-{stage}/original/{stage}.json"
    put(module, key, body, "application/json")
    ref, _head = module.asset(key, "test-game")
    module.table.put_item(
        Item={
            "pk": "TASKS",
            "sk": f"{job['jobId']}:{stage}",
            "jobId": job["jobId"],
            "gameId": job["gameId"],
            "stage": stage,
            "status": "DONE",
            "output": ref,
            "leaseUntil": 0,
            "attempts": 1,
        }
    )
    return ref


def test_recovery_reuses_valid_stages_and_reruns_only_the_failed_one(editorial):
    parent = submitted(editorial)[1]
    payloads = {
        "context": {"selection": {"title": "Context"}, "evidence": {"catalog": {}}},
        "correction": {"markdown": "Names fixed", "edits": [], "passed": True},
        "corrected-transcript": {"transcript": {"segments": []}, "review": {"markdown": "Kept"}},
        "novel-brief": {"markdown": "A brief that no longer matches its pin.", "passed": True},
        "novel-proof": {"markdown": "The river chapter.", "passed": True, "title": "River"},
    }
    kept = {stage: done_stage(editorial, parent, stage, payload) for stage, payload in payloads.items()}
    editorial.table.update_item(
        Key={"pk": "TASKS", "sk": f"{parent['jobId']}:novel-brief"},
        UpdateExpression="SET #output = :output",
        ExpressionAttributeNames={"#output": "output"},
        ExpressionAttributeValues={":output": {**kept["novel-brief"], "sha256": "stale-checksum"}},
    )
    editorial.table.put_item(
        Item={
            "pk": "TASKS",
            "sk": f"{parent['jobId']}:novel-chapter",
            "jobId": parent["jobId"],
            "stage": "novel-chapter",
            "status": "FAILED",
        }
    )
    editorial.internal({"operation": "fail", "jobId": parent["jobId"]})
    recovered = unpack(
        request(editorial, "POST /editorial-jobs", {"recovery": {"jobId": parent["jobId"], "target": "both"}})
    )
    assert recovered["recovery"]["mode"] == "reuse-valid-stages"
    assert set(recovered["recovery"]["reusedStages"]) == {
        "context",
        "correction",
        "corrected-transcript",
        "novel-proof",
    }
    for stage in recovered["recovery"]["reusedStages"]:
        editorial.internal(
            {
                "operation": "dispatch",
                "jobId": recovered["jobId"],
                "stage": stage,
                "taskToken": f"token-{stage}",
            }
        )
        stored = editorial.read("TASKS", f"{recovered['jobId']}:{stage}")
        assert stored["status"] == "DONE"
        assert stored["reusedFrom"] == parent["jobId"]
        assert stored["output"]["sha256"] == recovered["recovery"]["reusedOutputs"][stage]["sha256"]
    assert unpack(request(editorial, "POST /editorial-jobs/claim", {"workflowVersion": PLAN["version"]}))[
        "task"
    ] is None
    editorial.internal(
        {
            "operation": "dispatch",
            "jobId": recovered["jobId"],
            "stage": "novel-chapter",
            "taskToken": "token-novel-chapter",
        }
    )
    claimed = unpack(
        request(editorial, "POST /editorial-jobs/claim", {"workflowVersion": PLAN["version"]})
    )
    assert claimed["task"]["stage"] == "novel-chapter"
    assert claimed["artifacts"]["novel-proof"]["key"] == kept["novel-proof"]["key"]


def test_recovery_reuses_completed_novel_chapter_and_video_stages(editorial):
    parent = submitted(editorial)[1]
    payloads = {
        "context": {"selection": {"title": "Context"}, "evidence": {"catalog": {}}},
        "correction": {"markdown": "Names fixed", "edits": [], "passed": True},
        "corrected-transcript": {"transcript": {"segments": []}, "review": {"markdown": "Kept"}},
        "novel-brief": {"markdown": "A brief.", "passed": True},
        "novel-proof": {"markdown": "The river chapter.", "passed": True, "title": "River"},
        "novel-chapter": {"markdown": "The finished chapter.", "passed": True, "title": "River"},
        "video-source-brief": {"markdown": "Usable dialogue from the enrolled players.", "passed": True},
        "video-audio-script": {"markdown": "Treatment.", "passed": True},
    }
    kept = {stage: done_stage(editorial, parent, stage, payload) for stage, payload in payloads.items()}
    editorial.table.put_item(
        Item={
            "pk": "TASKS",
            "sk": f"{parent['jobId']}:video-preflight",
            "jobId": parent["jobId"],
            "stage": "video-preflight",
            "status": "FAILED",
        }
    )
    editorial.internal({"operation": "fail", "jobId": parent["jobId"]})
    recovered = unpack(
        request(editorial, "POST /editorial-jobs", {"recovery": {"jobId": parent["jobId"], "target": "both"}})
    )
    assert {"novel-chapter", "video-source-brief", "video-audio-script"} <= set(
        recovered["recovery"]["reusedStages"]
    )
    for stage in ("novel-chapter", "video-source-brief", "video-audio-script"):
        editorial.internal(
            {
                "operation": "dispatch",
                "jobId": recovered["jobId"],
                "stage": stage,
                "taskToken": f"token-{stage}",
            }
        )
        stored = editorial.read("TASKS", f"{recovered['jobId']}:{stage}")
        assert stored["status"] == "DONE"
        assert stored["reusedFrom"] == parent["jobId"]
        assert stored["output"]["sha256"] == kept[stage]["sha256"]
    editorial.internal(
        {
            "operation": "dispatch",
            "jobId": recovered["jobId"],
            "stage": "video-preflight",
            "taskToken": "token-video-preflight",
        }
    )
    claimed = unpack(
        request(editorial, "POST /editorial-jobs/claim", {"workflowVersion": PLAN["version"]})
    )
    assert claimed["task"]["stage"] == "video-preflight"
    assert claimed["artifacts"]["novel-chapter"]["key"] == kept["novel-chapter"]["key"]


def test_novel_ready_recovery_replans_video_and_keeps_the_novel(editorial):
    parent = submitted(editorial)[1]
    payloads = {
        "context": {"selection": {"title": "Context"}, "evidence": {"catalog": {}}},
        "correction": {"markdown": "Names fixed", "edits": [], "passed": True},
        "corrected-transcript": {"transcript": {"segments": []}, "review": {"markdown": "Kept"}},
        "novel-chapter": {"markdown": "The finished chapter.", "passed": True, "title": "River"},
        "video-source-brief": {"markdown": "The old cut.", "passed": True},
    }
    kept = {
        stage: done_stage(editorial, parent, stage, payload) for stage, payload in payloads.items()
    }
    editorial.table.update_item(
        Key={"pk": "RUNS", "sk": parent["jobId"]},
        UpdateExpression="SET #target = :target",
        ExpressionAttributeNames={"#target": "target"},
        ExpressionAttributeValues={":target": "novel"},
    )
    editorial.internal({"operation": "finish", "jobId": parent["jobId"]})
    assert editorial.read("RUNS", parent["jobId"])["status"] == "NOVEL_READY"
    recovered = unpack(
        request(
            editorial,
            "POST /editorial-jobs",
            {"recovery": {"jobId": parent["jobId"], "target": "video"}},
        )
    )
    assert recovered["videoGenerationAuthorized"] is False
    assert recovered["target"] == "video"
    refused = request(
        editorial,
        "POST /editorial-jobs",
        {"recovery": {"jobId": parent["jobId"], "target": "both"}},
    )
    assert refused["statusCode"] == 400
    reused = set(recovered["recovery"]["reusedStages"])
    assert {"context", "correction", "corrected-transcript", "novel-chapter"} <= reused
    assert "video-source-brief" not in reused
    assert "video-preflight" not in reused
    editorial.internal(
        {
            "operation": "dispatch",
            "jobId": recovered["jobId"],
            "stage": "novel-chapter",
            "taskToken": "token-novel-chapter",
        }
    )
    stored = editorial.read("TASKS", f"{recovered['jobId']}:novel-chapter")
    assert stored["status"] == "DONE"
    assert stored["reusedFrom"] == parent["jobId"]
    assert stored["output"]["sha256"] == kept["novel-chapter"]["sha256"]
    editorial.internal(
        {
            "operation": "dispatch",
            "jobId": recovered["jobId"],
            "stage": "video-source-brief",
            "taskToken": "token-video-source-brief",
        }
    )
    replanned = editorial.read("TASKS", f"{recovered['jobId']}:video-source-brief")
    assert replanned["status"] == "QUEUED"
    assert "reusedFrom" not in replanned


def test_video_recovery_reuses_stages_inherited_from_a_prior_recovery(editorial):
    original = submitted(editorial)[1]
    payloads = {
        "context": {"selection": {"title": "Context"}, "evidence": {"catalog": {}}},
        "correction": {"markdown": "Names fixed", "edits": [], "passed": True},
        "corrected-transcript": {"transcript": {"segments": []}, "review": {"markdown": "Kept"}},
        "novel-proof": {"markdown": "The river chapter.", "passed": True, "title": "River"},
    }
    kept = {
        stage: done_stage(editorial, original, stage, payload) for stage, payload in payloads.items()
    }
    editorial.table.put_item(
        Item={
            "pk": "TASKS",
            "sk": f"{original['jobId']}:novel-chapter",
            "jobId": original["jobId"],
            "stage": "novel-chapter",
            "status": "FAILED",
        }
    )
    editorial.internal({"operation": "fail", "jobId": original["jobId"]})
    novel = unpack(
        request(
            editorial,
            "POST /editorial-jobs",
            {"recovery": {"jobId": original["jobId"], "target": "novel"}},
        )
    )
    for stage in novel["recovery"]["reusedStages"]:
        editorial.internal(
            {
                "operation": "dispatch",
                "jobId": novel["jobId"],
                "stage": stage,
                "taskToken": f"token-{stage}",
            }
        )
        stored = editorial.read("TASKS", f"{novel['jobId']}:{stage}")
        assert stored["status"] == "DONE"
        assert stored["reusedFrom"] == original["jobId"]
    chapter = done_stage(
        editorial,
        novel,
        "novel-chapter",
        {"markdown": "The finished chapter.", "passed": True, "title": "River"},
    )
    editorial.internal({"operation": "finish", "jobId": novel["jobId"]})
    assert editorial.read("RUNS", novel["jobId"])["status"] == "NOVEL_READY"
    recovered = unpack(
        request(
            editorial,
            "POST /editorial-jobs",
            {"recovery": {"jobId": novel["jobId"], "target": "video"}},
        )
    )
    assert recovered["videoGenerationAuthorized"] is False
    reused = set(recovered["recovery"]["reusedStages"])
    assert {"context", "correction", "corrected-transcript", "novel-proof", "novel-chapter"} <= reused
    assert recovered["recovery"]["reusedOutputs"]["context"]["sha256"] == kept["context"]["sha256"]
    assert recovered["recovery"]["reusedOutputs"]["novel-chapter"]["sha256"] == chapter["sha256"]
    assert "video-source-brief" not in reused


def test_video_stages_keep_only_an_excerpt_of_earlier_sessions():
    from panther_journal import editorial

    prior = {"content": "x" * 50_000}
    inputs = {"context": {"catalog": {}, "prior.txt": prior}, "priorStages": {}}
    selected, notes = editorial.select_stage_inputs("video-audio-script", inputs)
    assert len(selected["context"]["prior.txt"]["content"]) == editorial.PRIOR_SESSION_VIDEO_BYTES
    assert notes and notes[0]["action"] == "excerpted"
    kept, _ = editorial.select_stage_inputs("novel-brief", inputs)
    assert len(kept["context"]["prior.txt"]["content"]) == 50_000


def test_claude_stage_thinking_is_bounded_below_the_output_cap():
    from panther_journal import inference

    env = inference.claude_budget_environment({}, "medium")
    assert int(env["MAX_THINKING_TOKENS"]) < int(env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"])
