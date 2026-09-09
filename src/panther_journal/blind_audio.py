"""Allowlisted mounts for a blind, offline Whisper run. No chat, prompt or holdout inputs."""

import os
import re
import subprocess

import click


def image_id(docker):
    result = subprocess.run(
        [
            docker,
            "--context",
            "desktop-linux",
            "image",
            "inspect",
            "panther-audio:local",
            "--format",
            "{{.Id}}",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    image = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise click.ClickException(
            "Build the blind transcriber with ops/audio/build-transcriber.sh."
        )
    return image


def command(docker, image, audio_file, model, output):
    # Mount individual input files, never their parent directories or the recording folder.
    mounts = [
        (audio_file.resolve(), "/input.wav", True),
        (model.resolve(), "/model.bin", True),
        (output.resolve(), "/output", False),
    ]
    if any("," in str(source) for source, _, _ in mounts):
        raise click.ClickException("Docker blind inputs cannot use paths containing commas.")
    result = [
        docker,
        "--context",
        "desktop-linux",
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--cpus=4",
        "--memory=6g",
        "--pids-limit=128",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
    ]
    for source, destination, readonly in mounts:
        result += [
            "--mount",
            f"type=bind,src={source},dst={destination}" + (",readonly" if readonly else ""),
        ]
    return result + [
        image,
        "-m",
        "/model.bin",
        "-f",
        "/input.wav",
        "-l",
        "en",
        "-t",
        "4",
        "-ojf",
        "-of",
        "/output/transcription",
    ]


def manifest(image, audio_sha256, model_sha256):
    # Explicit allowlist for evaluation evidence, not a list supplied by the test-script author.
    return {
        "mode": "blind-offline-container",
        "imageId": image,
        "audioSha256": audio_sha256,
        "modelSha256": model_sha256,
        "inputs": ["audio", "model"],
        "textPrompt": None,
        "network": False,
        "chatHistory": False,
        "referenceScript": False,
    }
