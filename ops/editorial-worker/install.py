"""Install a pinned, reviewed Panther editorial worker; never copy AWS/Codex credentials."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile

LABEL = "place.panther.editorial-worker"
# launchd does not inherit a login shell. This is the PATH the LaunchAgent actually gets.
LAUNCHD_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def claude_executable(search_path=None):
    """Absolute Claude Code CLI visible to launchd. A shell-only install is not enough."""
    search_path = LAUNCHD_PATH if search_path is None else search_path
    found = shutil.which("claude", path=search_path)
    if not found or not os.path.isabs(found):
        shell_found = shutil.which("claude")
        located = ""
        if shell_found and os.path.isabs(shell_found):
            located = f" The shell finds {shell_found}, which is outside the LaunchAgent PATH."
        raise SystemExit(
            "claude is not on the LaunchAgent PATH "
            f"({search_path}).{located} Install the Claude Code CLI on that PATH and sign in "
            "with the Claude subscription. An API key is not the editorial backend."
        )
    path = Path(found)
    if str(path.parent) not in search_path.split(":") or not path.is_file() or not os.access(path, os.X_OK):
        raise SystemExit(f"{found} is not an executable Claude Code CLI on the LaunchAgent PATH")
    return found


def attach_claude(definition, claude):
    """Record the absolute CLI. Never place a provider key in the LaunchAgent."""
    if not os.path.isabs(claude):
        raise SystemExit("Claude Code must be recorded as an absolute path")
    variables = definition["EnvironmentVariables"]
    if any(
        key.startswith("ANTHROPIC_") or key == "CLAUDE_CODE_OAUTH_TOKEN" or key.endswith("API_KEY")
        for key in variables
    ):
        raise SystemExit("The LaunchAgent must not carry an API key. Claude Code uses the subscription login.")
    variables["PATH"] = LAUNCHD_PATH
    variables["PANTHER_CLAUDE"] = claude
    return definition


def service_definition(release, state, home):
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(release / "venv/bin/panther"),
            "editorial",
            "worker",
            "--work-dir",
            str(state / "jobs"),
        ],
        "WorkingDirectory": str(state),
        "EnvironmentVariables": {
            "PATH": LAUNCHD_PATH,
            "HOME": str(home),
            "PYTHONUNBUFFERED": "1",
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "Umask": 0o077,
        "StandardOutPath": str(state / "worker.log"),
        "StandardErrorPath": str(state / "worker-error.log"),
    }


def install(repo, state, start, claude=None):
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
    definition = service_definition(release, state, Path.home())
    if claude:
        attach_claude(definition, claude)
    with plist.open("xb") as stream:
        plistlib.dump(definition, stream)
    if start:
        subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)], check=True)
    print(json.dumps({"commit": sha, "state": str(state), "plist": str(plist), "started": start}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path.home() / "Library/Application Support/Panther/editorial-worker",
    )
    parser.add_argument("--start", action="store_true")
    args = parser.parse_args()
    install(args.repo, args.state_dir, args.start, claude_executable())
