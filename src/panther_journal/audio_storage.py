"""Durable local checkpoints and advisory locks for the recording lifecycle."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import uuid

import click


def flush_file(file):
    with Path(file).open("rb") as stream:
        os.fsync(stream.fileno())
        if sys.platform == "darwin":
            import fcntl

            fcntl.fcntl(stream.fileno(), fcntl.F_FULLFSYNC)


def flush_directory(folder):
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json(file, value, *, replace=False):
    """Atomic publish after fsync. Only operational status files may be replaced."""
    file = Path(file)
    temporary = file.with_name(f".{file.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        flush_file(temporary)
        if replace:
            os.replace(temporary, file)
        else:
            os.link(temporary, file)  # Atomic, refuses an existing destination.
        flush_directory(file.parent)
    finally:
        temporary.unlink(missing_ok=True)  # Only this invocation's private scratch file.


@contextmanager
def lock(folder, name):
    import fcntl

    with (Path(folder) / name).open("a") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise click.ClickException(
                f"{name}: another process is still using this recording."
            ) from exc
        yield stream.fileno()


def capture_active(folder):
    try:
        with lock(folder, "capture.lock"):
            return False
    except click.ClickException:
        return True
