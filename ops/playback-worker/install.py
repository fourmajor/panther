"""Install a pinned, reviewed Panther playback worker; never copy AWS/Codex credentials."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tarfile
import tempfile

LABEL = "place.panther.playback-worker"


def service_definition(release, state, home):
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(release / "venv/bin/panther"),
            "recording",
            "playback",
            "worker",
            "--work-dir",
            str(state / "jobs"),
            "--once",
        ],
        "WorkingDirectory": str(state),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(home),
            "PYTHONUNBUFFERED": "1",
        },
        "RunAtLoad": True,
        "StartInterval": 60,
        "ProcessType": "Background",
        "Umask": 0o077,
        "StandardOutPath": str(state / "worker.log"),
        "StandardErrorPath": str(state / "worker-error.log"),
    }


def install(repo, state, start):
    if sys.platform != "darwin":
        raise SystemExit("This installer is for macOS")
    repo, state = repo.resolve(), state.resolve()
    if state in {Path.home(), Path("/")} or any(
        (p / ".git").exists() for p in (state, *state.parents)
    ):
        raise SystemExit("Use a dedicated private directory outside Git")
    git = ["git", "-C", str(repo)]

    def output(*args):
        return subprocess.check_output([*git, *args], text=True).strip()

    sha = output("rev-parse", "HEAD")
    if (
        output("branch", "--show-current") != "main"
        or output("status", "--porcelain")
        or output("rev-parse", "origin/main") != sha
    ):
        raise SystemExit("Install only clean merged main matching fetched origin/main")
    service = f"gui/{os.getuid()}/{LABEL}"
    if subprocess.run(["launchctl", "print", service], capture_output=True).returncode == 0:
        raise SystemExit("Worker is already loaded; stop it explicitly before upgrading")
    os.umask(0o077)
    release = state / "releases" / sha
    if release.exists():
        raise SystemExit(
            "Release already exists; inspect retained installation instead of overwriting"
        )
    snapshot = release / "repo"
    snapshot.mkdir(parents=True, mode=0o700)
    with tempfile.TemporaryFile() as archive:
        subprocess.run([*git, "archive", sha], stdout=archive, check=True)
        archive.seek(0)
        with tarfile.open(fileobj=archive) as tree:
            tree.extractall(snapshot, filter="data")
    subprocess.run([sys.executable, "-m", "venv", str(release / "venv")], check=True)
    subprocess.run(
        [str(release / "venv/bin/python"), "-m", "pip", "install", str(snapshot)], check=True
    )
    plist = (Path.home() / "Library/LaunchAgents" if start else state) / f"{LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    if plist.exists():
        raise SystemExit("Existing service retained; inspect before replacement")
    with plist.open("xb") as stream:
        plistlib.dump(service_definition(release, state, Path.home()), stream)
    if start:
        subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)], check=True)
    print(json.dumps({"commit": sha, "state": str(state), "plist": str(plist), "started": start}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path.home() / "Library/Application Support/Panther/playback-worker",
    )
    parser.add_argument("--start", action="store_true")
    args = parser.parse_args()
    install(args.repo, args.state_dir, args.start)

