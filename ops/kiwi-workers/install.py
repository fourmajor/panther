"""Upgrade the Kiwi playback and model workers. Do not raise their memory limits.

Kiwi is a 14 GiB household server. The shared slice stays at 3G, each worker at
1.5G, with OOMScoreAdjust 900. Old releases, including 32de295 and 2bb9136, stay
on disk. Stop a loaded worker before replacing it, or pass --retire to disable
the units without deleting that state.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import tempfile

RETAINED = ("32de295", "2bb9136")
SLICE = """\
[Slice]
MemoryMax=3G
"""
UNITS = {
    "playback": ("panther-playback", "1min"),
    "model": ("panther-model", "5min"),
}


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def output(args):
    return subprocess.check_output(args, text=True).strip()


def require_kiwi():
    if socket.gethostname().split(".")[0] != "kiwi":
        raise SystemExit("This installer is only for the Kiwi household server.")


def state_root():
    return Path.home() / ".local/state/panther"


def unit_dir():
    return Path.home() / ".config/systemd/user"


def service_text(kind, release):
    state = release.parents[1]
    runner = release / "venv/bin/python"
    script = release / "repo/ops/kiwi-workers/run.py"
    credential = Path.home() / ".local/share/panther/session.cred"
    session = (
        f"Environment=PANTHER_SESSION_CREDENTIAL_FILE={credential}\n"
        if credential.is_file()
        else ""
    )
    return (
        "[Unit]\n"
        f"Description=Panther {kind} worker\n"
        "After=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "Slice=panther.slice\n"
        "MemoryMax=1.5G\n"
        "OOMScoreAdjust=900\n"
        "TimeoutStartSec=infinity\n"
        f"WorkingDirectory={state}\n"
        f"ExecStart={runner} {script} {kind} {release}\n"
        "Environment=PYTHONUNBUFFERED=1\n"
        f"Environment=HOME={Path.home()}\n"
        f"{session}"
    )


def timer_text(kind):
    _name, interval = UNITS[kind]
    return f"""\
[Unit]
Description=Panther {kind} worker tick

[Timer]
OnBootSec=1min
OnUnitActiveSec={interval}
AccuracySec=15s

[Install]
WantedBy=timers.target
"""


def write_exact(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != text:
        raise SystemExit(
            f"Existing unit differs; move {path} aside and inspect it before replacement."
        )
    path.write_text(text, encoding="utf-8")


def loaded(names):
    active = []
    for name in names:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", name],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() in {"active", "activating"}:
            active.append(name)
    return active


def reviewed_sha(repo):
    git = ["git", "-C", str(repo)]
    sha = output([*git, "rev-parse", "HEAD"])
    if (
        output([*git, "branch", "--show-current"]) != "main"
        or output([*git, "status", "--porcelain"])
        or output([*git, "rev-parse", "origin/main"]) != sha
    ):
        raise SystemExit("Install only from clean, merged main matching origin/main; fetch first.")
    return sha


def snapshot(repo, release, sha):
    ready = release / "ready.json"
    if release.exists() and not ready.exists():
        raise SystemExit(f"Incomplete installation retained at {release}; inspect before retrying.")
    if ready.exists():
        return json.loads(ready.read_text(encoding="utf-8"))
    tree = release / "repo"
    tree.mkdir(parents=True, mode=0o700)
    with tempfile.TemporaryFile() as archive:
        run(["git", "-C", str(repo), "archive", sha], stdout=archive)
        archive.seek(0)
        with tarfile.open(fileobj=archive) as packed:
            packed.extractall(tree, filter="data")
    run([sys.executable, "-m", "venv", str(release / "venv")])
    run([str(release / "venv/bin/python"), "-m", "pip", "install", str(tree)])
    return None


def qa_image(snapshot_dir, sha):
    tag = f"panther-model-qa:{sha}"
    run(
        [
            "docker",
            "build",
            "--tag",
            tag,
            "--file",
            "ops/model-worker/Dockerfile",
            ".",
        ],
        cwd=snapshot_dir,
    )
    return output(["docker", "image", "inspect", "--format", "{{.Id}}", tag])


def retire():
    require_kiwi()
    names = [f"{unit}.service" for unit, _interval in UNITS.values()]
    names += [f"{unit}.timer" for unit, _interval in UNITS.values()]
    subprocess.run(["systemctl", "--user", "disable", "--now", *names], check=False)
    print(json.dumps({"retired": names, "deleted": False}, indent=2))


def install(repo, playback_state, model_state, authorized, start):
    require_kiwi()
    if not authorized:
        raise SystemExit(
            "Pass --allow-unsandboxed-blender. Codex stays sandboxed; Blender does not."
        )
    repo = repo.resolve()
    playback_state, model_state = playback_state.resolve(), model_state.resolve()
    for state in (playback_state, model_state):
        if state in {Path.home(), Path("/"), repo} or repo in state.parents:
            raise SystemExit("Choose dedicated private state directories outside the repository.")
    busy = loaded(
        [
            "panther-playback.service",
            "panther-model.service",
            "place.panther.playback-worker.service",
            "place.panther.model-worker.service",
        ]
    )
    if busy:
        raise SystemExit(
            "Stop the loaded Kiwi worker before upgrading. "
            f"Active: {', '.join(busy)}. Releases {', '.join(RETAINED)} stay on disk."
        )
    os.umask(0o077)
    sha = reviewed_sha(repo)
    playback_release = playback_state / "releases" / sha
    model_release = model_state / "releases" / sha
    if snapshot(repo, playback_release, sha) is None:
        (playback_release / "ready.json").write_text(
            json.dumps({"commit": sha}, indent=2), encoding="utf-8"
        )
    if snapshot(repo, model_release, sha) is None:
        image = qa_image(model_release / "repo", sha)
        (model_release / "ready.json").write_text(
            json.dumps({"commit": sha, "qaImage": image}, indent=2), encoding="utf-8"
        )
    units = unit_dir()
    write_exact(units / "panther.slice", SLICE)
    write_exact(units / "panther-playback.service", service_text("playback", playback_release))
    write_exact(units / "panther-playback.timer", timer_text("playback"))
    write_exact(units / "panther-model.service", service_text("model", model_release))
    write_exact(units / "panther-model.timer", timer_text("model"))
    run(["systemctl", "--user", "daemon-reload"])
    if start:
        run(
            [
                "systemctl",
                "--user",
                "enable",
                "--now",
                "panther-playback.timer",
                "panther-model.timer",
            ]
        )
    retained = []
    for root in (playback_state, model_state):
        releases = root / "releases"
        if not releases.is_dir():
            continue
        names = [path.name for path in releases.iterdir()]
        retained.extend(pin for pin in RETAINED if any(name.startswith(pin) for name in names))
    print(
        json.dumps(
            {
                "commit": sha,
                "slice": "panther.slice MemoryMax=3G",
                "workerMemoryMax": "1.5G",
                "oomScoreAdjust": 900,
                "memAvailableFloorKib": 1536 * 1024,
                "lock": str(Path.home() / ".local/state/panther/workers.lock"),
                "retainedReleases": retained,
                "started": start,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--playback-state", type=Path, default=state_root() / "playback-worker")
    parser.add_argument("--model-state", type=Path, default=state_root() / "model-worker")
    parser.add_argument("--allow-unsandboxed-blender", action="store_true")
    parser.add_argument("--start", action="store_true")
    parser.add_argument(
        "--retire", action="store_true", help="Disable the units and keep every release."
    )
    args = parser.parse_args()
    if args.retire:
        retire()
    else:
        if args.repo is None:
            raise SystemExit("--repo is required to upgrade")
        install(
            args.repo,
            args.playback_state,
            args.model_state,
            args.allow_unsandboxed_blender,
            args.start,
        )
