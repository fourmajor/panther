"""One Kiwi worker tick. Skip it when memory is tight or the other worker holds the lock."""

import fcntl
import json
import os
from pathlib import Path
import sys

# Same 1.5 GiB ceiling as the systemd MemoryMax. A tighter box waits for the next tick.
FLOOR_KIB = 1536 * 1024
LOCK = Path.home() / ".local/state/panther/workers.lock"


def mem_available_kib(text):
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1])
    raise SystemExit("MemAvailable is missing from /proc/meminfo")


def main(argv):
    if len(argv) != 3 or argv[1] not in {"playback", "model"}:
        raise SystemExit("Usage: run.py playback|model RELEASE")
    kind, release = argv[1], Path(argv[2]).resolve()
    available = mem_available_kib(Path("/proc/meminfo").read_text(encoding="utf-8"))
    if available < FLOOR_KIB:
        print(
            "MemAvailable is below 1.5 GiB; leaving this tick for the household.", file=sys.stderr
        )
        return 0
    LOCK.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        print("The other Kiwi worker holds the shared lock.", file=sys.stderr)
        return 0
    flags = fcntl.fcntl(descriptor, fcntl.F_GETFD)
    fcntl.fcntl(descriptor, fcntl.F_SETFD, flags & ~fcntl.FD_CLOEXEC)
    state = release.parents[1]
    panther = release / "venv/bin/panther"
    if kind == "playback":
        command = [
            str(panther),
            "recording",
            "playback",
            "worker",
            "--work-dir",
            str(state / "jobs"),
            "--once",
        ]
    else:
        image = (release / "ready.json").read_text(encoding="utf-8")
        command = [
            str(panther),
            "model",
            "worker",
            "--repo",
            str(release / "repo"),
            "--work-dir",
            str(state / "jobs"),
            "--qa-image",
            json.loads(image)["qaImage"],
            "--once",
            "--allow-unsandboxed-blender",
        ]
    os.execv(command[0], command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
