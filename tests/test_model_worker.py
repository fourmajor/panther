import base64
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import click
import pytest
from click.testing import CliRunner

from panther_journal import model_workflow as worker
from panther_journal.cli import main


def test_upload_new_model_edition_uses_exact_pinned_semantic_predecessor(tmp_path, monkeypatch):
    file = tmp_path / "model.glb"
    file.write_bytes(b"synthetic model")
    prior = "games/example-game/assets/prior/original/model.glb"
    job = {
        "jobId": "0" * 64,
        "gameId": "example-game",
        "characterId": "hero",
        "appearanceId": "ordinary",
        "appearanceSelection": {"modelKey": prior, "sourceKey": None, "provenanceKey": None},
        "views": {
            view: {"key": f"games/example-game/assets/refs/original/{view}.png"}
            for view in worker.VIEWS
        },
    }
    monkeypatch.setattr(
        worker.cloud, "api", Mock(side_effect=click.ClickException("Object not found"))
    )
    upload = Mock()
    monkeypatch.setattr(worker.cloud.upload, "callback", upload)
    worker.upload_file({}, file, job, 1)
    assert upload.call_args.kwargs["new_version_of"] == prior
    assert upload.call_args.kwargs["kind"] == "model-3d"
    metadata = json.loads((tmp_path / "model.glb.metadata.json").read_text())
    assert metadata["characterIds"] == ["hero"] and metadata["extra"]["appearanceId"] == "ordinary"
    assert metadata["sourceKeys"] == [job["views"][view]["key"] for view in worker.VIEWS]


def test_provenance_revision_preserves_its_registered_kind(tmp_path, monkeypatch):
    file = tmp_path / "provenance.json"
    file.write_text("{}")
    prior = "games/example-game/assets/prior/original/provenance.json"
    job = {
        "jobId": "0" * 64,
        "gameId": "example-game",
        "characterId": "hero",
        "appearanceId": "ordinary",
        "appearanceSelection": {"provenanceKey": prior},
        "views": {view: {"key": f"{view}.png"} for view in worker.VIEWS},
    }
    monkeypatch.setattr(
        worker.cloud, "api", Mock(side_effect=click.ClickException("Object not found"))
    )
    upload = Mock()
    monkeypatch.setattr(worker.cloud.upload, "callback", upload)
    worker.upload_file({}, file, job, 2)
    assert upload.call_args.kwargs["kind"] == "model-provenance"
    assert upload.call_args.kwargs["new_version_of"] == prior


def test_qa_image_includes_runtime_plan_and_discovers_tests_before_jobs():
    repo = Path(__file__).resolve().parents[1]
    dockerfile = (repo / "ops/model-worker/Dockerfile").read_text()
    ignore = (repo / ".dockerignore").read_text()
    assert "COPY src/panther_journal/editorial-plan.json" in dockerfile
    assert "!src/panther_journal/editorial-plan.json" in ignore
    assert "playwright test browser-tests/viewer.spec.cjs --list" in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers" in dockerfile
    assert 'chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH"' in dockerfile


def test_browser_qa_runs_as_the_private_job_owner():
    source = (
        Path(__file__).resolve().parents[1] / "src/panther_journal/model_workflow.py"
    ).read_text()
    assert '"--user",\n                    f"{os.getuid()}:{os.getgid()}",' in source


def test_subscription_environment_never_inherits_provider_or_aws_keys(monkeypatch):
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/test/codex")
    for name in (
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_PROFILE",
        "HTTP_PROXY",
        "ANTHROPIC_API_KEY",
        "CODEX_HOME",
    ):
        monkeypatch.setenv(name, "secret")
    assert not any("secret" == value for value in worker.clean_environment().values())
    base = worker.codex_base()
    assert 'forced_login_method="chatgpt"' in base
    assert 'model_provider="openai"' in base
    assert not any("bypass" in value for value in base)


def test_native_tools_use_linux_paths_and_default_docker_context(monkeypatch):
    monkeypatch.setattr(worker.sys, "platform", "linux")
    monkeypatch.setattr(worker.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert worker.native_blender() == Path("/usr/bin/blender")
    assert worker.docker_base() == ["docker"]


def test_native_tools_keep_macos_application_and_desktop_context(monkeypatch):
    monkeypatch.setattr(worker.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "is_file", lambda path: True)
    assert worker.native_blender() == Path("/Applications/Blender.app/Contents/MacOS/Blender")
    assert worker.docker_base() == ["docker", "--context", "desktop-linux"]


def test_worker_rejects_repository_as_game_output(tmp_path):
    result = CliRunner().invoke(
        main, ["model", "worker", "--repo", str(tmp_path), "--work-dir", str(tmp_path), "--once"]
    )
    assert result.exit_code != 0
    assert "outside the application repository" in result.output


def test_references_submit_through_panther_api(tmp_path, monkeypatch):
    manifest = tmp_path / "set.json"
    manifest.write_text(json.dumps({"kind": "character-turnaround"}))
    api = Mock(return_value={"jobId": "test"})
    monkeypatch.setattr(worker.cloud, "configuration", lambda: {})
    monkeypatch.setattr(worker.cloud, "api", api)
    result = CliRunner().invoke(main, ["model", "references", str(manifest)])
    assert result.exit_code == 0
    assert api.call_args.args[1:3] == ("POST", "/model-reference-sets")


def test_download_checks_exact_checksum_and_never_overwrites(tmp_path, monkeypatch):
    data = b"synthetic reference"
    reference = {
        "key": "test",
        "size": len(data),
        "sha256": base64.b64encode(hashlib.sha256(data).digest()).decode(),
    }
    reply = Mock()
    reply.__enter__ = Mock(return_value=reply)
    reply.__exit__ = Mock(return_value=False)
    reply.iter_content.return_value = [data]
    monkeypatch.setattr(worker.requests, "get", Mock(return_value=reply))
    monkeypatch.setattr(
        worker.cloud, "api", Mock(return_value={"url": "https://test.s3.amazonaws.com/ref"})
    )
    dest = tmp_path / "reference.png"
    worker.download({}, reference, dest)
    assert dest.read_bytes() == data
    worker.download({}, reference, dest)
    dest.write_bytes(b"changed")
    with pytest.raises(click.ClickException, match="refusing to overwrite"):
        worker.download({}, reference, dest)


def test_codex_nonzero_defers_instead_of_falling_back(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        worker, "codex_base", lambda: ["codex", "-c", 'forced_login_method="chatgpt"']
    )
    monkeypatch.setattr(
        worker, "run_process", lambda command, **kwargs: called.append(command) or 1
    )
    with pytest.raises(worker.Deferred):
        worker.agent(tmp_path, [], "test", lambda: None, "build")
    assert len(called) == 1
    assert "--ignore-user-config" in called[0]
    assert "sandbox_workspace_write.network_access=false" in called[0]
    assert "workspace-write" in called[0]
    with pytest.raises(worker.Deferred):
        worker.agent(tmp_path, [], "test", lambda: None, "review")
    assert "read-only" in called[1]


def test_native_blender_requires_explicit_authorization(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    result = CliRunner().invoke(
        main,
        ["model", "worker", "--repo", str(repo), "--work-dir", str(tmp_path / "jobs"), "--once"],
    )
    assert result.exit_code != 0
    assert "explicit --allow-unsandboxed-blender" in result.output
    assert not (tmp_path / "jobs").exists()


def test_invalid_or_external_glb_is_rejected(tmp_path):
    import struct

    file = tmp_path / "model.glb"
    for doc in (
        {"asset": {"version": "2.0"}, "images": [{"uri": "https://external/image.png"}]},
        {"asset": {"version": "2.0"}, "buffers": [{"uri": "data:external"}]},
    ):
        raw = json.dumps(doc).encode()
        file.write_bytes(
            struct.pack("<4sIII4s", b"glTF", 2, 20 + len(raw), len(raw), b"JSON") + raw
        )
        with pytest.raises(click.ClickException, match="embed"):
            worker.validate_glb(file)


def test_in_progress_publication_is_reconciled_without_rerunning_inference(tmp_path, monkeypatch):
    job = {"jobId": "test", "status": "PUBLISHING", "result": {"passed": True}}
    api = Mock(return_value={"status": "PUBLISHED"})
    monkeypatch.setattr(worker.cloud, "api", api)
    result = worker.process_job(
        tmp_path, tmp_path, Path("blender"), {}, {"job": job, "lease": "lease"}
    )
    assert result["status"] == "PUBLISHED"
    assert api.call_args.args[2] == "/model-jobs/complete"


def synthetic_job_runtime(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    job = {
        "jobId": "1" * 64,
        "gameId": "example-game",
        "characterId": "hero",
        "status": "RUNNING",
        "appearanceId": "ordinary",
        "workflowVersion": 2,
        "appearanceSelection": {"portraitKey": "synthetic", "modelKey": None},
        "views": {view: {"key": f"{view}.png"} for view in worker.VIEWS},
    }
    api = Mock(return_value={"status": "PUBLISHED"})
    monkeypatch.setattr(worker.cloud, "api", api)
    monkeypatch.setattr(worker, "download", lambda config, ref, path: path.write_bytes(b"ref"))
    monkeypatch.setattr(worker, "validate_glb", lambda path: None)
    upload = Mock(side_effect=lambda config, path, job, attempt: f"synthetic/{path.name}")
    monkeypatch.setattr(worker, "upload_file", upload)
    stages = []

    def agent(folder, images, prompt, heartbeat, stage):
        stages.append(stage)
        if stage == "build":
            (folder / "build.py").write_text("# synthetic test script")
        return {"passed": True, "assessment": "Synthetic test only", "issues": []}

    def process(command, *, folder, **kwargs):
        if str(repo / "ops/model-worker/validate.py") in command:
            (folder / "renders").mkdir(exist_ok=True)
            for view in worker.VIEWS:
                (folder / "renders" / f"{view}.png").write_bytes(b"synthetic render")
            (folder / "validation.json").write_text("{}")
        elif str(folder / "build.py") in command:
            (folder / "model.blend").write_bytes(b"synthetic source")
            (folder / "model.glb").write_bytes(b"synthetic model")
        return 0

    monkeypatch.setattr(worker, "agent", agent)
    monkeypatch.setattr(worker, "run_process", process)
    return repo, job, api, upload, stages, process


def test_native_interruption_resumes_script_without_repeating_inference(tmp_path, monkeypatch):
    repo, job, api, upload, stages, process = synthetic_job_runtime(tmp_path, monkeypatch)
    interrupted = [False]

    def stop_once(command, **kwargs):
        if str(kwargs["folder"] / "build.py") in command and not interrupted[0]:
            interrupted[0] = True
            raise worker.Deferred("synthetic native interruption")
        return process(command, **kwargs)

    monkeypatch.setattr(worker, "run_process", stop_once)
    claim = {"job": job, "lease": "synthetic-lease"}
    with pytest.raises(worker.Deferred):
        worker.process_job(repo, tmp_path, Path("blender"), {}, claim)
    checkpoint = json.loads((tmp_path / job["jobId"] / "checkpoint.json").read_text())
    assert checkpoint["phase"] == "blender" and len(checkpoint["scriptSha256"]) == 64
    assert not upload.called
    worker.process_job(repo, tmp_path, Path("blender"), {}, claim)
    assert stages == ["build", "review"]
    assert api.call_args.args[2] == "/model-jobs/complete"


def test_final_rejected_candidate_completes_without_uploading_artwork(tmp_path, monkeypatch):
    repo, job, api, upload, stages, process = synthetic_job_runtime(tmp_path, monkeypatch)
    original_agent = worker.agent

    def reject_review(folder, images, prompt, heartbeat, stage):
        result = original_agent(folder, images, prompt, heartbeat, stage)
        if stage == "review":
            return {
                "passed": False,
                "assessment": "Synthetic quality rejection",
                "issues": ["poor likeness"],
            }
        return result

    monkeypatch.setattr(worker, "agent", reject_review)
    claim = {"job": job, "lease": "lease"}
    with pytest.raises(worker.Deferred, match="bounded refinement"):
        worker.process_job(repo, tmp_path, Path("blender"), {}, claim)
    worker.process_job(repo, tmp_path, Path("blender"), {}, claim)
    assert not upload.called
    result = api.call_args.kwargs["json"]["result"]
    assert result == {
        "passed": False,
        "webKey": None,
        "sourceKey": None,
        "provenanceKey": None,
        "evidenceKey": None,
    }
    candidate = tmp_path / job["jobId"] / "candidate-2"
    assert json.loads((candidate / "evidence.json").read_text())["visualReview"]["passed"] is False
    assert (candidate / "model.blend").is_file() and (candidate / "model.glb").is_file()
    # Recovery submits the same rejected result without new inference or uploads.
    before = list(stages)
    worker.process_job(repo, tmp_path, Path("blender"), {}, claim)
    assert stages == before and not upload.called


def test_changed_saved_script_stops_before_native_execution(tmp_path, monkeypatch):
    repo, job, api, upload, stages, process = synthetic_job_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(worker, "run_process", Mock(side_effect=worker.Deferred("interrupt")))
    claim = {"job": job, "lease": "synthetic-lease"}
    with pytest.raises(worker.Deferred):
        worker.process_job(repo, tmp_path, Path("blender"), {}, claim)
    (tmp_path / job["jobId"] / "candidate-1" / "build.py").write_text("# changed")
    native = Mock(side_effect=process)
    monkeypatch.setattr(worker, "run_process", native)
    with pytest.raises(click.ClickException, match="script changed"):
        worker.process_job(repo, tmp_path, Path("blender"), {}, claim)
    assert stages == ["build"] and not native.called and not upload.called


def test_recovery_rejects_changed_pinned_inputs(tmp_path, monkeypatch):
    repo, job, api, upload, stages, process = synthetic_job_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(worker, "run_process", Mock(side_effect=worker.Deferred("interrupt")))
    claim = {"job": job, "lease": "lease"}
    with pytest.raises(worker.Deferred):
        worker.process_job(repo, tmp_path, Path("blender"), {}, claim)
    job["appearanceSelection"]["portraitKey"] = "different-selection"
    with pytest.raises(click.ClickException, match="Recovery inputs changed"):
        worker.process_job(repo, tmp_path, Path("blender"), {}, claim)
    assert stages == ["build"] and not upload.called


def test_old_evidence_checkpoint_is_preserved_and_revalidated(tmp_path, monkeypatch):
    repo, job, api, upload, stages, process = synthetic_job_runtime(tmp_path, monkeypatch)
    claim = {"job": job, "lease": "lease"}
    worker.process_job(repo, tmp_path, Path("blender"), {}, claim)
    path = tmp_path / job["jobId"] / "checkpoint.json"
    checkpoint = json.loads(path.read_text())
    checkpoint["validatedHashes"] = {
        key: value
        for key, value in checkpoint["validatedHashes"].items()
        if key in {"model.glb", "model.blend"}
    }
    path.write_text(json.dumps(checkpoint))
    stages.clear()
    worker.process_job(repo, tmp_path, Path("blender"), {}, claim)
    folder = tmp_path / job["jobId"] / "candidate-1"
    assert stages == ["review"]
    assert (
        folder / "checkpoint-evidence-v1" / "renders/back.png"
    ).read_bytes() == b"synthetic render"
    assert (
        json.loads((folder / "checkpoint-evidence-v1" / "checkpoint.json").read_text())
        == checkpoint
    )
    assert len(json.loads(path.read_text())["validatedHashes"]) == 11


def test_bounded_refinement_preserves_inputs_and_first_candidate(tmp_path, monkeypatch):
    repo, job, api, upload, stages, process = synthetic_job_runtime(tmp_path, monkeypatch)
    original = worker.agent

    def review(folder, images, prompt, heartbeat, stage):
        result = original(folder, images, prompt, heartbeat, stage)
        if stage == "review" and folder.name == "candidate-1":
            return {"passed": False, "assessment": "Synthetic failure", "issues": ["anatomy"]}
        return result

    monkeypatch.setattr(worker, "agent", review)
    claim = {"job": job, "lease": "lease"}
    with pytest.raises(worker.Deferred, match="bounded refinement"):
        worker.process_job(repo, tmp_path, Path("blender"), {}, claim)
    assert not upload.called
    second = tmp_path / job["jobId"] / "candidate-2"
    assert json.loads((second / "inputs.json").read_text()) == job
    assert json.loads((second / "previous-critique.json").read_text())["issues"] == ["anatomy"]
    worker.process_job(repo, tmp_path, Path("blender"), {}, claim)
    assert stages == ["build", "review", "build", "review"]
    assert (tmp_path / job["jobId"] / "candidate-1" / "model.blend").is_file()


@pytest.mark.parametrize("filename", ["model.glb", "validation.json", "renders/back.png"])
def test_changed_review_evidence_blocks_publication(tmp_path, monkeypatch, filename):
    repo, job, api, upload, stages, process = synthetic_job_runtime(tmp_path, monkeypatch)
    original = worker.agent

    def changed_evidence(folder, images, prompt, heartbeat, stage):
        result = original(folder, images, prompt, heartbeat, stage)
        if stage == "review":
            (folder / filename).write_bytes(b"changed after inspection")
        return result

    monkeypatch.setattr(worker, "agent", changed_evidence)
    with pytest.raises(click.ClickException, match="inspection evidence changed"):
        worker.process_job(repo, tmp_path, Path("blender"), {}, {"job": job, "lease": "lease"})
    assert not upload.called
