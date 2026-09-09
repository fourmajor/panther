import importlib.util
from pathlib import Path
import plistlib

import pytest

spec = importlib.util.spec_from_file_location(
    "worker_install", Path(__file__).parents[1] / "ops/model-worker/install.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_service_pins_release_and_image_without_inheriting_secrets(tmp_path):
    release, state = tmp_path / "releases/reviewed-sha", tmp_path / "private"
    definition = installer.service_definition(release, state, "sha256:verified", tmp_path)
    assert plistlib.loads(plistlib.dumps(definition)) == definition
    args = definition["ProgramArguments"]
    assert args[0] == str(release / "venv/bin/panther")
    assert str(release / "repo") in args
    assert "sha256:verified" in args
    assert "--allow-unsandboxed-blender" in args
    assert definition["StartInterval"] == 300
    assert "KeepAlive" not in definition
    assert set(definition["EnvironmentVariables"]) == {"PATH", "HOME", "PYTHONUNBUFFERED"}


def test_installer_requires_explicit_native_permission(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    with pytest.raises(SystemExit, match="explicit"):
        installer.install(tmp_path / "repo", tmp_path / "state", False, False)
    assert not (tmp_path / "state").exists()


def test_preparation_cannot_autostart_at_next_login(tmp_path):
    state, home = tmp_path / "private", tmp_path / "home"
    assert installer.service_path(state, home, False) == state / f"{installer.LABEL}.plist"
    assert installer.service_path(state, home, True) == (
        home / "Library/LaunchAgents" / f"{installer.LABEL}.plist"
    )


def test_installer_refuses_unreviewed_branch_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    monkeypatch.setattr(installer, "output", lambda args: "codex/unmerged")
    with pytest.raises(SystemExit, match="clean, merged main"):
        installer.install(tmp_path / "repo", tmp_path / "state", True, False)
    assert not (tmp_path / "state").exists()
