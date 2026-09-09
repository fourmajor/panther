"""Build the bundled native recorder; no device is opened during compilation."""

import hashlib
from importlib.resources import files
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

import click

from panther_journal.audio_storage import lock


def binary():
    if sys.platform != "darwin":
        raise click.ClickException("Native microphone capture requires macOS.")
    source = Path(str(files("panther_journal").joinpath("native/capture.c")))
    compiler, pkg = shutil.which("clang"), shutil.which("pkg-config")
    if not compiler or not pkg:
        raise click.ClickException(
            "Install Xcode command-line tools and Homebrew pkg-config/portaudio."
        )
    try:
        flags = shlex.split(
            subprocess.check_output(
                [pkg, "--cflags", "--libs", "portaudio-2.0"], text=True, stderr=subprocess.PIPE
            )
        )
        version = subprocess.check_output([pkg, "--modversion", "portaudio-2.0"], text=True)
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            "Install the native capture dependency: brew install portaudio"
        ) from exc
    identity = hashlib.sha256(
        source.read_bytes() + repr(flags).encode() + version.encode()
    ).hexdigest()
    root = Path.home() / "Library/Application Support/Panther/audio-capture"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock(root, "build.lock"):
        target = root / f"capture-{identity}"
        if target.is_symlink():
            raise click.ClickException("Refusing symlinked recorder executable.")
        if not target.exists():
            with tempfile.TemporaryDirectory(prefix="build-", dir=root) as folder:
                output = Path(folder) / "capture"
                subprocess.run(
                    [
                        compiler,
                        "-std=c11",
                        "-O2",
                        "-Wall",
                        "-Wextra",
                        "-Werror",
                        str(source),
                        "-o",
                        str(output),
                        *flags,
                    ],
                    check=True,
                )
                os.link(output, target)
    return str(target)
