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


def test_subscription_environment_never_inherits_provider_or_aws_keys(monkeypatch):
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
