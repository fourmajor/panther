"""Local lossless capture and versioned, player-attributed transcripts. No paid API calls."""

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Literal

import click
from pydantic import BaseModel, ConfigDict, Field, model_validator

from panther_journal import cloud, generation_metadata as generation
from panther_journal.audio_storage import flush_directory, lock, write_json


class Part(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    file: str = Field(pattern=r"^part-[0-9]{4}\.flac$")
    start: float = Field(ge=0)
    duration: float = Field(gt=0)
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sampleRate: int = Field(gt=0)
    channels: int = Field(ge=1, le=32)
    bitsPerSample: int = Field(ge=4, le=32)


class Recording(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    schemaVersion: Literal[1] = 1
    entityType: Literal["Recording"] = "Recording"
    id: str = Field(pattern=r"^recording-[0-9a-f]{32}$")
    gameId: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=96)
    sessionId: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=96)
    startedAt: str
    device: str
    status: Literal["complete", "interrupted"]
    sourceFormat: Literal["flac"] = "flac"
    parts: list[Part] = Field(min_length=1)

    @model_validator(mode="after")
    def timeline(self):
        offset = 0.0
        for i, part in enumerate(self.parts):
            if part.file != f"part-{i:04d}.flac" or abs(part.start - offset) > 0.02:
                raise ValueError("Recording parts must be ordered and contiguous")
            offset += part.duration
        return self


def executable(name):
    path = shutil.which(name)
    if not path:
        raise click.ClickException(f"Required local tool is missing: {name}")
    return path


def digest(file):
    with file.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_new(file, value):
    write_json(file, value)


def private_folder(root, game, session):
    root = root.expanduser().resolve()
    # Reject application checkouts, not merely this package's installed location.
    if (
        root == Path.home()
        or root == Path("/")
        or any((p / ".git").exists() for p in (root, *root.parents))
    ):
        raise click.ClickException("Use a dedicated private output directory outside Git.")
    cloud.slug(game)
    cloud.slug(session)
    os.umask(0o077)
    folder = root / f"recording-{uuid.uuid4().hex}"
    folder.mkdir(parents=True, mode=0o700)
    flush_directory(folder.parent)
    return folder


def probe(file):
    result = subprocess.run(
        [
            executable("ffprobe"),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-show_frames",
            "-show_entries",
            "frame=nb_samples",
            "-of",
            "json",
            str(file),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    data = json.loads(result.stdout)
    streams = [s for s in data["streams"] if s["codec_type"] == "audio"]
    if len(streams) != 1:
        raise click.ClickException("Expected one audio stream; preserve its original channels.")
    stream = streams[0]
    # The FLAC encoder's STREAMINFO totals may be absent or span the entire session
    # when FFmpeg's segment muxer reuses it. Count actual decoded samples per file.
    samples = sum(int(frame.get("nb_samples", 0)) for frame in data.get("frames", []))
    if samples <= 0:
        raise ValueError("No decodable audio samples.")
    return {
        "duration": samples / int(stream["sample_rate"]),
        "sampleRate": int(stream["sample_rate"]),
        "channels": stream["channels"],
        "bitsPerSample": int(
            stream.get("bits_per_raw_sample") or stream.get("bits_per_sample") or 0
        ),
    }


def finish_capture(folder, header, status):
    from panther_journal.recording_sync import checkpoint

    parts = checkpoint(folder, header, final=True, allow_incomplete=status == "interrupted")
    if not parts:
        raise click.ClickException(
            "No valid audio samples captured. Files retained; inspect capture.log."
        )
    record = Recording(**header, status=status, parts=parts)
    write_new(folder / "recording.json", record.model_dump())
    return record


def verified(folder):
    folder = folder.resolve()
    record = Recording.model_validate_json((folder / "recording.json").read_text())
    for part in record.parts:
        file = folder / part.file
        if (
            file.is_symlink()
            or not file.is_file()
            or file.stat().st_size != part.size
            or digest(file) != part.sha256
        ):
            raise click.ClickException(
                "Recording changed or is missing; refusing to process/upload."
            )
    return record


def capture_command(device, folder, seconds, chunk_seconds=30):
    from panther_journal.native_capture import binary

    return [binary(), device, str(folder), str(seconds or 0), str(chunk_seconds)]


def header(folder, game, session, device):
    return {
        "id": folder.name,
        "gameId": game,
        "sessionId": session,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "device": device,
    }


@click.group()
def recording():
    """Capture lossless audio, preserve it, and make player-attributed transcript versions."""


@recording.command("devices")
def devices():
    """List Mac recording devices without capturing audio."""
    if sys.platform != "darwin":
        raise click.ClickException(
            "Device capture currently supports macOS; import supports other platforms."
        )
    from panther_journal.native_capture import binary

    result = subprocess.run([binary(), "--list"], capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise click.ClickException("Could not list microphones; check macOS permissions.")
    click.echo(result.stdout, nl=False)


DEFAULT_ROOT = Path.home() / "Library/Application Support/Panther/recordings"


@recording.command("start")
@click.option("--game", required=True)
@click.option("--session", required=True)
@click.option(
    "--device", required=True, help="Exact device name from recording devices; no silent fallback."
)
@click.option("--seconds", type=click.IntRange(1, 43200), help="Otherwise record until Ctrl+C.")
@click.option("--output-root", type=click.Path(path_type=Path), default=DEFAULT_ROOT)
@click.option("--chunk-seconds", type=click.IntRange(10, 600), default=30, show_default=True)
@click.option(
    "--sync/--no-sync",
    "sync_enabled",
    default=False,
    help="Sync completed chunks through Panther in the background.",
)
def start(game, session, device, seconds, output_root, chunk_seconds, sync_enabled):
    """Stream to durable short FLAC parts, optionally syncing completed parts in the background."""
    from panther_journal.recording_sync import checkpoint

    if sys.platform != "darwin" or not device or ":" in device or device.startswith("--"):
        raise click.ClickException("Choose an exact macOS audio device name.")
    executable("ffmpeg")
    executable("ffprobe")
    executable("flac")
    from panther_journal.native_capture import binary

    binary()  # Fail dependency/build checks before announcing microphone capture.
    folder = private_folder(output_root, game, session)
    metadata = header(folder, game, session, device)
    (folder / "capture-pcm").mkdir(mode=0o700)
    flush_directory(folder)
    write_new(folder / "capture.json", metadata)
    write_new(
        folder / "capture-settings.json",
        {
            "chunkSeconds": chunk_seconds,
            "syncRequested": sync_enabled,
            "backend": "portaudio-coreaudio",
        },
    )
    click.echo(
        f"Starting microphone: {device}\nPrivate recording: {folder}\nCtrl+C stops and finalizes. Background sync: {'on' if sync_enabled else 'off'}."
    )
    with lock(folder, "capture.lock") as lock_fd, (folder / "capture.log").open("x") as log:
        child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "panther_journal.capture_worker",
                json.dumps(capture_command(device, folder, seconds, chunk_seconds)),
                str(lock_fd),
            ],
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=log,
            start_new_session=True,
            pass_fds=(lock_fd,),
        )
        uploader = None
        if sync_enabled:
            try:
                with (folder / "sync.log").open("x") as sync_log:
                    uploader = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "panther_journal.cli",
                            "recording",
                            "sync",
                            str(folder),
                            "--watch",
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=sync_log,
                        stderr=sync_log,
                        start_new_session=True,
                    )
            except OSError:
                click.echo(
                    "Background sync could not start; local capture continues. Use recording sync later.",
                    err=True,
                )
        interrupted = False

        def request_stop(signum, frame):
            raise KeyboardInterrupt

        previous_handlers = {
            s: signal.signal(s, request_stop) for s in (signal.SIGTERM, signal.SIGHUP)
        }
        checkpoint_count = 0
        sync_seen = None
        try:
            while child.poll() is None:
                parts = checkpoint(folder, metadata)
                if len(parts) != checkpoint_count:
                    checkpoint_count = len(parts)
                    click.echo(f"Saved locally: {checkpoint_count} completed chunk(s).")
                status_file = folder / "sync-status.json"
                if sync_enabled and status_file.exists():
                    try:
                        sync_status = json.loads(status_file.read_text())
                        if not isinstance(sync_status, dict):
                            raise ValueError("Invalid sync status")
                    except (OSError, ValueError):
                        # Backup progress is advisory; it must never stop microphone capture.
                        sync_status = {"error": "Unreadable sync status"}
                    progress = (sync_status.get("partsSynced", 0), sync_status.get("error"))
                    if progress != sync_seen:
                        sync_seen = progress
                        click.echo(
                            "Cloud sync pending; local capture continues."
                            if progress[1]
                            else f"Backed up: {progress[0]} chunk(s)."
                        )
                time.sleep(1)
        except KeyboardInterrupt:
            interrupted = True
            if child.poll() is None:
                try:
                    child.stdin.write(b"q\n")
                    child.stdin.flush()
                except BrokenPipeError:
                    pass
        finally:
            child.stdin.close()  # EOF also closes capture if this controller crashes.
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            for s, previous in previous_handlers.items():
                signal.signal(s, previous)
        result = finish_capture(
            folder, metadata, "interrupted" if interrupted or child.returncode else "complete"
        )
    click.echo(f"Saved and verified {len(result.parts)} FLAC part(s): {folder}")
    if uploader:
        click.echo(
            f"Background sync is independent. Resume/check with: panther recording sync '{folder}'"
        )
    if child.returncode:
        raise click.ClickException(
            "Capture was interrupted; intact audio retained. Inspect capture.log."
        )


@recording.command("recover")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
def recover(folder):
    """Recover a stopped recording; retain any damaged final chunk separately, never delete it."""
    with lock(folder, "capture.lock"):
        if (folder / "recording.json").exists():
            verified(folder)
        else:
            finish_capture(folder, json.loads((folder / "capture.json").read_text()), "interrupted")
    click.echo(
        "Recording manifest verified. Inspect capture.log for interruptions or dropped input."
    )


@recording.command("import")
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--game", required=True)
@click.option("--session", required=True)
@click.option("--output-root", type=click.Path(path_type=Path), default=DEFAULT_ROOT)
def import_audio(source, game, session, output_root):
    """Import FLAC or losslessly encode integer PCM WAV; leave the supplied original untouched."""
    if source.suffix.lower() not in {".wav", ".flac"}:
        raise click.ClickException(
            "Import WAV or FLAC; do not make a lossy source look like a lossless original."
        )
    folder = private_folder(output_root, game, session)
    destination = folder / "part-0000.flac"
    if source.suffix.lower() == ".flac":
        shutil.copyfile(source, destination)
    else:
        subprocess.run(
            [
                executable("flac"),
                "--verify",
                "--keep-foreign-metadata-if-present",
                "-o",
                str(destination),
                str(source),
            ],
            check=True,
        )
    metadata = header(folder, game, session, "import")
    write_new(folder / "capture.json", metadata)
    write_new(
        folder / "import-provenance.json",
        {
            "originalFilename": source.name,
            "originalSha256": digest(source),
            "originalRetained": True,
        },
    )
    finish_capture(folder, metadata, "complete")
    click.echo(str(folder))


def upload_one(config, file, record, kind, *, source_keys=None):
    key = f"games/{record.gameId}/assets/{record.id}/original/{file.name}"
    sha = base64.b64encode(bytes.fromhex(digest(file))).decode()
    try:
        existing = cloud.api(config, "GET", "/object-url", params={"key": key})
    except click.ClickException as exc:
        if "Object not found" not in str(exc):
            raise
    else:
        if (
            existing.get("size") != file.stat().st_size
            or existing.get("metadata", {}).get("extra", {}).get("sha256") != sha
        ):
            raise click.ClickException("Remote file differs; refusing overwrite.")
        return key
    metadata = {
        "title": file.name,
        "sessionId": record.sessionId,
        "category": "canonical-source" if kind == "recording" else "unclassified",
        "extra": {"recordingId": record.id, "chunkSetId": record.id, "sha256": sha},
    }
    creation = generation.unknown()
    if kind in {"recording-playback", "recording-playback-manifest"}:
        creation = generation.local("FFmpeg")
    elif kind in {"raw-transcript", "transcript"}:
        # The original transcript retains the model checksum. Do not infer its model version.
        creation = generation.local("whisper.cpp", method="ai")
    elif kind == "recording":
        # Imports may have been captured elsewhere; a local upload does not establish origin.
        capture = json.loads((file.parent / "capture.json").read_text()) if (file.parent / "capture.json").is_file() else {}
        if capture.get("device") and capture["device"] != "import":
            creation = generation.local("Panther recorder", method="capture")
    metadata["extra"]["generation"] = creation
    # Existing CLI enforces authentication, streamed SHA-256, exact size, and If-None-Match.
    metadata_path = file.parent / f".upload-{uuid.uuid4().hex}.json"
    if kind in {"transcript", "raw-transcript", "corrected-transcript"}:
        metadata["sourceKeys"] = [
            f"games/{record.gameId}/assets/{record.id}/original/recording.json"
        ]
    if source_keys is not None:
        metadata["sourceKeys"] = source_keys
    write_new(metadata_path, metadata)
    cloud.upload.callback(
        file=file,
        game=record.gameId,
        asset=record.id,
        kind=kind,
        metadata=metadata_path,
        as_json=True,
    )
    return key


@recording.command("upload")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--transcript", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--editorial/--no-editorial",
    default=True,
    help="Commit a raw transcript to the editorial workflow after upload.",
)
def upload_recording(folder, transcript, editorial=True):
    """Upload verified source parts and structured manifest through Panther; keep local copies."""
    record = verified(folder)
    config = cloud.configuration()
    cloud.api(config, "GET", "/game", params={"gameId": record.gameId})
    transcript_files = []
    if transcript:
        if transcript.is_symlink() or transcript.resolve().parent != folder.resolve():
            raise click.ClickException(
                "Transcript must be this recording's local version directory."
            )
        json_file = transcript / f"{transcript.name}.json"
        document = json.loads(json_file.read_text())
        if document.get("recordingId") != record.id or document.get("sourceParts") != [
            p.model_dump() for p in record.parts
        ]:
            raise click.ClickException("Transcript does not reference this exact source recording.")
        for file in (json_file, transcript / f"{transcript.name}.md"):
            if file.is_symlink() or not file.is_file():
                raise click.ClickException("Missing or symlinked transcript output.")
            transcript_files.append(file)
    keys = [upload_one(config, folder / p.file, record, "recording") for p in record.parts]
    manifest_key = upload_one(config, folder / "recording.json", record, "recording-manifest")
    if (folder / "capture-health.json").exists():
        upload_one(config, folder / "capture-health.json", record, "capture-health")
    from panther_journal.playback_worker import complete_set

    playback = complete_set(folder, config, record)
    transcript_keys = [
        upload_one(config, file, record, "raw-transcript") for file in transcript_files
    ]
    editorial_job = None
    if (
        transcript
        and editorial
        and document.get("artifactType", "raw-transcript") == "raw-transcript"
    ):
        editorial_job = cloud.api(
            config,
            "POST",
            "/editorial-jobs",
            json={"gameId": record.gameId, "rawKey": transcript_keys[0]},
        )
    click.echo(
        json.dumps(
            {
                "recordingId": record.id,
                "playback": playback,
                "sourceKeys": keys,
                "manifestKey": manifest_key,
                "transcriptKeys": transcript_keys,
                "editorialJob": editorial_job,
            },
            indent=2,
        )
    )


def transcript_lines(raw, part, player_id):
    lines = []
    for segment in raw["transcription"]:
        start = float(segment["offsets"]["from"]) / 1000
        end = float(segment["offsets"]["to"]) / 1000
        if not 0 <= start <= end <= part.duration + 1 or start > part.duration:
            raise click.ClickException("Transcriber returned invalid timestamps.")
        text = segment["text"].strip()
        if text:
            lines.append(
                {
                    "start": part.start + start,
                    "end": part.start + min(end, part.duration),
                    "playerId": player_id,
                    "attribution": "user-declared-single-player" if player_id else "unassigned",
                    "text": text,
                    "speechContext": "unclassified",
                    "sourcePart": part.file,
                }
            )
    return lines


@recording.command("transcribe")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--model", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "--sole-player",
    help="Only when the entire recording contains this one known person; not speaker recognition.",
)
@click.option(
    "--roster",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Optional saved Panther game-show JSON for offline processing.",
)
@click.option(
    "--blind",
    is_flag=True,
    help="Run offline in Docker with only audio/model inputs; no reference script or chat.",
)
@click.option(
    "--publish/--local-only",
    default=True,
    help="Publish completed raw transcript and trigger editorial stages; local-only preserves offline/holdout testing.",
)
def transcribe(folder, model, sole_player, roster, blind, publish):
    """Run local Whisper and retain a new JSON/Markdown transcript version, including table chatter."""
    record = verified(folder)
    from panther_journal.capture_audit import audit

    integrity = audit(folder)
    game = (
        json.loads(roster.read_text())
        if roster
        else cloud.api(cloud.configuration(), "GET", "/game", params={"gameId": record.gameId})
    )
    if game["game"]["id"] != record.gameId:
        raise click.ClickException("Roster belongs to a different game.")
    people = {p["id"]: p["name"] for p in game["players"]}
    if sole_player and sole_player not in people:
        raise click.ClickException("Sole player must be in this game's roster.")
    run_id = f"transcript-{uuid.uuid4().hex}"
    target = folder / run_id
    target.mkdir(mode=0o700)
    write_new(target / "roster-snapshot.json", game)
    inputs, outputs = target / "asr-input", target / "asr-output"
    inputs.mkdir(mode=0o700)
    outputs.mkdir(mode=0o700)
    # A joined derivative prevents storage chunk boundaries from splitting recognition context.
    # Hard links stage only the verified FLAC parts, not arbitrary files from this folder.
    for part in record.parts:
        os.link(folder / part.file, inputs / part.file)
    with (inputs / "parts.txt").open("x") as listing:
        for part in record.parts:
            listing.write(f"file '{part.file}'\nduration {part.duration:.9f}\n")
    joined = inputs / "audio.wav"
    isolation = None
    with (target / "engine.log").open("x") as log:
        subprocess.run(
            [
                executable("ffmpeg"),
                "-v",
                "error",
                "-n",
                "-f",
                "concat",
                "-safe",
                "1",
                "-i",
                str(inputs / "parts.txt"),
                "-map",
                "0:a:0",
                "-map_metadata",
                "-1",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(joined),
            ],
            stdout=log,
            stderr=log,
            check=True,
            timeout=1800,
        )
        if blind:
            from panther_journal import blind_audio

            docker = executable("docker")
            image = blind_audio.image_id(docker)
            command = blind_audio.command(docker, image, joined, model, outputs)
            isolation = blind_audio.manifest(image, digest(joined), digest(model))
            write_new(target / "blind-inputs.json", isolation)
        else:
            command = [
                executable("whisper-cli"),
                "-m",
                str(model.resolve()),
                "-f",
                str(joined.resolve()),
                "-l",
                "en",
                "-t",
                "4",
                "-ojf",
                "-of",
                str((outputs / "transcription").resolve()),
            ]
        subprocess.run(command, stdout=log, stderr=log, check=True, timeout=43200)
    combined = record.parts[0].model_copy(
        update={"duration": sum(p.duration for p in record.parts)}
    )
    lines = transcript_lines(
        json.loads((outputs / "transcription.json").read_text()), combined, sole_player
    )
    for line in lines:
        line.pop("sourcePart")
        line["sourceParts"] = [
            p.file
            for p in record.parts
            if p.start < line["end"] and p.start + p.duration > line["start"]
        ]
    document = {
        "schemaVersion": 1,
        "entityType": "PlayerTranscript",
        "artifactType": "raw-transcript",
        "captureIntegrity": integrity,
        "id": run_id,
        "gameId": record.gameId,
        "sessionId": record.sessionId,
        "recordingId": record.id,
        "sourceParts": [p.model_dump() for p in record.parts],
        "engine": "whisper.cpp",
        "modelSha256": digest(model),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "reviewStatus": "unreviewed",
        "speakerMethod": "declared-single-player" if sole_player else "unassigned",
        "players": game["players"],
        "segments": lines,
        "isolation": isolation,
    }
    save_transcript(target, document)
    click.echo(str(target))
    if publish:
        upload_recording.callback(folder=folder, transcript=target, editorial=True)
    if not sole_player:
        click.echo(
            "Speakers remain unassigned. Run recording diarize, then attribute with a confirmed speaker map.",
            err=True,
        )


def save_transcript(target, document):
    people = {p["id"]: p["name"] for p in document["players"]}
    write_new(target / f"{target.name}.json", document)
    with (target / f"{target.name}.md").open("x") as out:
        out.write(
            "# Transcript — unreviewed\n\nPlayer identity is separate from character voice or table chatter.\n\n"
        )
        for line in document["segments"]:
            out.write(
                f"[{line['start']:.2f}–{line['end']:.2f}] {people.get(line['playerId'], 'Unassigned')}: {line['text']}\n\n"
            )


DEFAULT_RUNTIME = Path.home() / "Library/Application Support/Panther/audio-runtime/bin/python"
DEFAULT_SPEAKER_MODEL = Path.home() / "Library/Application Support/Panther/audio-models/community-1"


@recording.command("diarize")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--runtime",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=DEFAULT_RUNTIME,
)
@click.option(
    "--model",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=DEFAULT_SPEAKER_MODEL,
)
@click.option(
    "--speakers",
    type=click.IntRange(1, 20),
    help="Actual speakers present, not the whole campaign roster.",
)
def diarize(folder, runtime, model, speakers):
    """Detect anonymous speakers locally across the whole recording; no identity guessing."""
    verified(folder)
    os.umask(0o077)
    target = folder / f"speakers-{uuid.uuid4().hex}"
    target.mkdir(mode=0o700)
    output = target / "diarization.json"
    command = [
        str(runtime.absolute()),
        str(Path(__file__).with_name("diarization_worker.py")),
        "--folder",
        str(folder.resolve()),
        "--model",
        str(model.resolve()),
        "--output",
        str(output.resolve()),
    ]
    if speakers:
        command += ["--speakers", str(speakers)]
    click.echo(f"Speaker run: {target}")
    click.echo(f"Progress: {target / 'progress.json'} (stage counts, not an overall estimate)")
    # No credentials inherited. Downloads are a separate, interactive setup operation.
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
    env.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", PYANNOTE_METRICS_ENABLED="0")
    with (target / "engine.log").open("x") as log:
        try:
            subprocess.run(command, env=env, stdout=log, stderr=log, check=True)
        except subprocess.CalledProcessError as exc:
            raise click.ClickException(
                f"Local speaker processing failed; inspect {target / 'engine.log'}"
            ) from exc
    click.echo(str(output))
    click.echo(
        "Speaker labels are anonymous and specific to this run. Confirm names from introductions before attribution."
    )


@recording.command('speaker-status')
@click.argument('run', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option('--json', 'as_json', is_flag=True, help='Return the saved progress snapshot.')
def speaker_status(run, as_json):
    """Read future diarization runs' real stage counters without contacting AWS or the worker."""
    path = run / 'progress.json'
    if not path.exists():
        raise click.ClickException('No progress snapshot: this run may predate progress reporting or not have started. Overall progress is unknown.')
    if path.is_symlink() or path.stat().st_size > 16384:
        raise click.ClickException('Invalid progress snapshot')
    try:
        value = json.loads(path.read_text())
        if value.get('schemaVersion') != 1 or value.get('entityType') != 'SpeakerDetectionProgress':
            raise ValueError('Invalid schema')
        if as_json:
            click.echo(json.dumps(value, indent=2, allow_nan=False))
            return
        counts = (f"{value['completed']}/{value['total']} ({value['stagePercent']}% of this stage)"
                  if value['stagePercent'] is not None else 'no batch counter for this stage')
        click.echo(f"{value['state']}: {value['stage']} — {counts}")
        click.echo(f"Overall: {'100%' if value['state'] == 'complete' else 'unknown'}; last update: {value['updatedAt']}")
        click.echo('This is a saved observation, not proof the process is still running or a resumable checkpoint.')
    except (ValueError, TypeError, KeyError) as exc:
        raise click.ClickException('Invalid progress snapshot') from exc


class SpeakerTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    speaker: str = Field(pattern=r"^SPEAKER_[0-9]+$")

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Speaker turn ends before it starts")
        return self


def attributed_lines(lines, turns, mapping):
    """Conservative whole-segment attribution: overlapping/mixed turns remain unassigned."""
    result = []
    for source in lines:
        line = dict(source)
        start, end = line["start"], line["end"]
        if not 0 <= start <= end or not all(math.isfinite(t) for t in (start, end)):
            raise click.ClickException("Invalid transcript interval.")
        intervals = [
            (max(start, t.start), min(end, t.end), t.speaker)
            for t in turns
            if t.start < end and t.end > start
        ]
        labels = {t[2] for t in intervals}
        label = next(iter(labels)) if len(labels) == 1 else None
        # Union coverage avoids counting duplicate same-speaker turns twice.
        coverage, previous = 0.0, start
        for a, b, _ in sorted(intervals):
            coverage += max(0, b - max(a, previous))
            previous = max(previous, b)
        player = (
            mapping.get(label)
            if label and end > start and coverage / (end - start) >= 0.8
            else None
        )
        line.update(
            playerId=player,
            speakerLabel=label,
            attribution="diarization-with-confirmed-map" if player else "unassigned",
        )
        result.append(line)
    return result


@recording.command("attribute")
@click.argument("transcript", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--diarization",
    "diarization_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--mapping",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Private JSON mapping anonymous labels to confirmed player IDs.",
)
@click.option('--word-level', is_flag=True, help='Split using the original saved ASR token timing evidence.')
@click.option('--minimum-coverage', default=0.65, type=click.FloatRange(min=0.500001, max=1))
@click.option('--winner-margin', default=0.25, type=click.FloatRange(min=0, max=1))
def attribute(transcript, diarization_file, mapping, word_level, minimum_coverage, winner_margin):
    """Create a new transcript version using a human-confirmed speaker-to-player map."""
    folder = transcript.resolve().parent
    record = verified(folder)
    source = transcript / f"{transcript.name}.json"
    document = json.loads(source.read_text())
    speakers = json.loads(diarization_file.read_text())
    for data in (document, speakers):
        if data.get("recordingId") != record.id or data.get("sourceParts") != [
            p.model_dump() for p in record.parts
        ]:
            raise click.ClickException(
                "Transcript and speaker run must reference this exact recording."
            )
    turns = [SpeakerTurn.model_validate(t) for t in speakers["turns"]]
    duration = sum(p.duration for p in record.parts)
    if any(t.end > duration + 1 for t in turns):
        raise click.ClickException("Speaker times exceed the recording.")
    names = json.loads(mapping.read_text())
    labels = {t.speaker for t in turns}
    players = {p["id"] for p in document["players"]}
    if (
        not isinstance(names, dict)
        or not names
        or not set(names) <= labels
        or any(not isinstance(p, str) or p not in players for p in names.values())
    ):
        raise click.ClickException(
            "Map detected speaker labels to this roster's player IDs, not character IDs."
        )
    target = folder / f"transcript-{uuid.uuid4().hex}"
    target.mkdir(mode=0o700)
    progress = None
    if word_level:
        from panther_journal import word_attribution

        timing_path = transcript / 'asr-output/transcription.json'
        progress = word_attribution.Progress(target / 'progress.json', len(document['segments']))
        click.echo(f'Progress: {target / "progress.json"}')
        try:
            timing = json.loads(timing_path.read_text())
            document['segments'], report = word_attribution.attribute(
                document['segments'], timing, turns, names, minimum_coverage, winner_margin, progress)
            document['speakerAttributionPolicy'] = {
                'version': 1, 'method': 'word-exclusive-coverage',
                'minimumCoverage': minimum_coverage, 'winnerMargin': winner_margin,
                'maximumOverlapCoverage': 0.1, 'timingEvidenceSha256': digest(timing_path),
                'timingWarning': 'Whisper token times are estimates, not forced alignment. '
                                 'Player labels inherit the supplied map; coverage is not accuracy.',
            }
            write_new(target / 'attribution-report.json', report)
        except Exception as exc:
            progress.write(progress.completed, status='failed', error=str(exc))
            raise click.ClickException(str(exc)) from exc
    else:
        document["segments"] = attributed_lines(document["segments"], turns, names)
    document.update(
        sourceTranscriptId=document["id"],
        sourceTranscriptSha256=digest(source),
        id=target.name,
        speakerMethod="word-timing-diarization-confirmed-map" if word_level else "local-diarization-confirmed-map",
        createdAt=datetime.now(timezone.utc).isoformat(),
        reviewStatus="unreviewed",
        diarizationSha256=digest(diarization_file),
        speakerMap=names,
    )
    try:
        save_transcript(target, document)
        write_new(target / "diarization.json", speakers)
    except Exception as exc:
        if progress:
            progress.write(progress.total, status='failed', error=str(exc))
        raise
    if progress:
        progress.write(progress.total, status='completed')
    click.echo(str(target))
    click.echo(
        "Mixed or overlapping speech remains unassigned. All text and earlier versions are retained."
    )
