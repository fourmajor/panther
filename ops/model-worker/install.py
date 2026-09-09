"""Install a reviewed main snapshot as a user-scoped macOS worker. No AWS credentials."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tarfile
import tempfile

LABEL = "place.panther.model-worker"


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def output(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def service_definition(release, state, image, home):
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(release / "venv/bin/panther"),
            "model",
            "worker",
            "--repo",
            str(release / "repo"),
            "--work-dir",
            str(state / "jobs"),
            "--qa-image",
            image,
            "--once",
            "--allow-unsandboxed-blender",
        ],
        "WorkingDirectory": str(state),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(home),
            "PYTHONUNBUFFERED": "1",
        },
        "RunAtLoad": True,
        "StartInterval": 300,
        "ProcessType": "Background",
        "Umask": 0o077,
        "StandardOutPath": str(state / "worker.log"),
        "StandardErrorPath": str(state / "worker-error.log"),
    }


def service_path(state, home, start):
    # LaunchAgents are automatically loaded at login, even without an explicit bootstrap.
    return (home / "Library/LaunchAgents" if start else state) / f"{LABEL}.plist"


def install(repo, state, authorized, start):
    if sys.platform != "darwin" or not authorized:
        raise SystemExit("macOS and explicit --allow-unsandboxed-blender authorization required.")
    repo, state = repo.resolve(), state.resolve()
    if state == Path.home() or state == Path("/") or state == repo or repo in state.parents:
        raise SystemExit("Choose a dedicated private state directory outside the repository.")
    git = ["git", "-C", str(repo)]
    sha = output([*git, "rev-parse", "HEAD"])
    if (
        output([*git, "branch", "--show-current"]) != "main"
        or output([*git, "status", "--porcelain"])
        or output([*git, "rev-parse", "origin/main"]) != sha
    ):
        raise SystemExit("Install only from clean, merged main matching origin/main; fetch first.")
    os.umask(0o077)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    release = state / "releases" / sha
    ready = release / "ready.json"
    if release.exists() and not ready.exists():
        raise SystemExit(f"Incomplete installation retained at {release}; inspect before retrying.")
    if not ready.exists():
        snapshot = release / "repo"
        snapshot.mkdir(parents=True)
        with tempfile.TemporaryFile() as archive:
            run([*git, "archive", sha], stdout=archive)
            archive.seek(0)
            with tarfile.open(fileobj=archive) as tree:
                tree.extractall(snapshot, filter="data")
        run([sys.executable, "-m", "venv", str(release / "venv")])
        run([str(release / "venv/bin/python"), "-m", "pip", "install", str(snapshot)])
        tag = f"panther-model-qa:{sha}"
        run(
            [
                "docker",
                "--context",
                "desktop-linux",
                "build",
                "--tag",
                tag,
                "--file",
                "ops/model-worker/Dockerfile",
                ".",
            ],
            cwd=snapshot,
        )
        image = output(
            ["docker", "--context", "desktop-linux", "image", "inspect", "--format", "{{.Id}}", tag]
        )
        ready.write_text(json.dumps({"commit": sha, "qaImage": image}, indent=2))
    image = json.loads(ready.read_text())["qaImage"]
    plist = service_path(state, Path.home(), start)
    plist.parent.mkdir(parents=True, exist_ok=True)
    service = f"gui/{os.getuid()}/{LABEL}"
    # Do not interrupt active work or silently replace another loaded release.
    loaded = subprocess.run(["launchctl", "print", service], capture_output=True)
    if loaded.returncode == 0:
        raise SystemExit("Worker is already loaded. Stop it explicitly before changing releases.")
    definition = service_definition(release, state, image, Path.home())
    if plist.exists() and plistlib.loads(plist.read_bytes()) != definition:
        raise SystemExit(
            f"Existing service differs; preserve and inspect {plist} before replacement."
        )
    plist.write_bytes(plistlib.dumps(definition))
    if start:
        run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)])
    print(
        json.dumps(
            {
                "commit": sha,
                "qaImage": image,
                "plist": str(plist),
                "state": str(state),
                "started": start,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path.home() / "Library/Application Support/Panther/model-worker",
    )
    parser.add_argument("--allow-unsandboxed-blender", action="store_true")
    parser.add_argument(
        "--start",
        action="store_true",
        help="Activate after installation; otherwise leave unloaded.",
    )
    args = parser.parse_args()
    install(args.repo, args.state_dir, args.allow_unsandboxed_blender, args.start)
