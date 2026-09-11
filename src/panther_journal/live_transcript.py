"""Read-only consumer of completed capture checkpoints; local provisional text, never evidence.

This process does not open a microphone, recover/finalize capture, upload anything, or trigger
editorial work. Only its own preview directory is writable. Capture always remains independent.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import signal
import shutil
import subprocess
import time
import uuid

import click
from contextlib import nullcontext

from panther_journal import recording as audio, generation_metadata as generation
from panther_journal.audio_storage import lock, write_json
from panther_journal.model_workflow import clean_environment

VERSION = 1
DEFAULT_MODEL = Path.home() / ".cache/whisper.cpp/ggml-small.bin"
NOTICE = "LIVE PREVIEW — provisional, speakers unassigned; not the final transcript."
GAP_NOTICE = "Preview gap: invalid recognizer output for this audio chunk. Original audio retained; not silence."


class PreviewOutputError(click.ClickException):
    """Recoverable recognition-data failure, never a source/integrity/process failure."""


def read_json(path, limit=1024 * 1024):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise click.ClickException("Missing, oversized or symlinked preview input")
    return json.loads(path.read_text())


def capture_running(folder):
    """Inspect the existing lock without creating/modifying a capture file."""
    import fcntl

    path = folder / "capture.lock"
    if path.is_symlink():
        raise click.ClickException("Unsafe capture lock")
    if not path.exists():
        return False
    with path.open("rb") as source:
        try:
            fcntl.flock(source, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def completed_parts(folder, header):
    journal = folder / "checkpoints"
    if journal.is_symlink():
        raise click.ClickException("Unsafe checkpoint directory")
    result, offset = [], 0.0
    for index, path in enumerate(sorted(journal.glob("part-*.json"))):
        value = read_json(path, 16384)
        part = audio.Part.model_validate(value["part"])
        if (
            value.get("schemaVersion") != 1
            or value.get("entityType") != "RecordingCheckpoint"
            or any(
                value.get(k) != header[v]
                for k, v in (
                    ("recordingId", "id"),
                    ("gameId", "gameId"),
                    ("sessionId", "sessionId"),
                )
            )
            or path.name != f"part-{index:04d}.json"
            or part.file != f"part-{index:04d}.flac"
            or abs(part.start - offset) > 0.02
        ):
            raise click.ClickException(
                "Checkpoint identity/order changed; preview stopped, capture untouched"
            )
        result.append(part)
        offset += part.duration
    return result


def check_part(folder, part):
    path = folder / part.file
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size != part.size
        or audio.digest(path) != part.sha256
    ):
        raise click.ClickException(
            "Completed audio changed or is missing; preview stopped, capture untouched"
        )
    return path


def initialize(folder, model, from_start, preview_name=None):
    folder, model = folder.expanduser().resolve(), model.expanduser().resolve()
    if folder in (Path.home(), Path("/")) or any(
        (p / ".git").exists() for p in (folder, *folder.parents)
    ):
        raise click.ClickException("Live previews belong beside private recordings outside Git")
    header = read_json(folder / "capture.json", 16384)
    if header.get("id") != folder.name:
        raise click.ClickException("Recording directory does not match capture identity")
    # Validate header shape without writing a final manifest or inventing capture status.
    for field in ("gameId", "sessionId"):
        audio.cloud.slug(header[field])
    parts = completed_parts(folder, header)
    if not model.is_file() or model.stat().st_size < 1024 * 1024:
        raise click.ClickException(
            "Supply real local Whisper weights with --model; no model is downloaded automatically"
        )
    model_hash = audio.digest(model)
    settings = {
        "workflowVersion": VERSION,
        "recordingId": header["id"],
        "captureSha256": audio.digest(folder / "capture.json"),
        "modelSha256": model_hash,
        "fromStart": from_start,
        "threads": 2,
        "gpu": False,
        "language": "en",
        "beamSize": 1,
        "bestOf": 1,
        "context": "one-completed-chunk",
    }
    if preview_name is not None:
        audio.cloud.slug(preview_name)
        settings["previewName"] = preview_name
    identity = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    root = folder / "live-preview" / f"v{VERSION}-{identity[:24]}"
    if (folder / "live-preview").is_symlink() or root.is_symlink():
        raise click.ClickException("Unsafe preview directory")
    os.umask(0o077)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock(root, "preview.lock"):
        config_path = root / "preview.json"
        if config_path.exists():
            config = read_json(config_path)
            if config.get("settings") != settings:
                raise click.ClickException("Preview settings changed")
        else:
            config = {
                "schemaVersion": 1,
                "entityType": "LiveTranscriptPreview",
                "settings": settings,
                "gameId": header["gameId"],
                "sessionId": header["sessionId"],
                "startIndex": 0 if from_start else max(0, len(parts) - 1),
                "reviewStatus": "provisional",
                "speakerMethod": "unassigned",
                "extra": {
                    "relationshipRole": "intermediate",
                    "contextUse": "exclude",
                    "generation": generation.local("whisper.cpp", method="ai"),
                },
            }
            write_json(config_path, config)
    return folder, model, header, root, config


def run_process(command, attempt, log_name, *, timeout=180):
    """Low priority, bounded work; Ctrl+C kills only this preview subprocess group."""
    with (attempt / log_name).open("xb") as log:
        env = {**clean_environment(), "OMP_NUM_THREADS": "2", "VECLIB_MAXIMUM_THREADS": "2"}
        child = subprocess.Popen(
            [audio.executable("nice"), "-n", "15", *command],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=attempt,
            env=env,
            start_new_session=True,
        )
        try:
            if child.wait(timeout=timeout):
                raise click.ClickException(
                    "Local preview decoder/transcriber failed; inspect its private log. Capture is unaffected"
                )
        except subprocess.TimeoutExpired as exc:
            raise click.ClickException(
                "Preview exceeded its time limit; capture continues. Retry with a smaller local model"
            ) from exc
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()


def transcribe_part(folder, part, model, attempt):
    source = check_part(folder, part)
    wav = attempt / "input.wav"
    run_process(
        [
            audio.executable("ffmpeg"),
            "-hide_banner",
            "-v",
            "error",
            "-xerror",
            "-nostdin",
            "-n",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-protocol_whitelist",
            "file,pipe",
            "-f",
            "flac",
            "-i",
            str(source),
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
            str(wav),
        ],
        attempt,
        "decode.log",
    )
    run_process(
        [
            audio.executable("whisper-cli"),
            "-m",
            str(model),
            "-f",
            str(wav),
            "-l",
            "en",
            "-t",
            "2",
            "-p",
            "1",
            "-ng",
            "-bs",
            "1",
            "-bo",
            "1",
            "-nf",
            "-mc",
            "0",
            "-ojf",
            "-of",
            str(attempt / "recognizer"),
        ],
        attempt,
        "recognizer.log",
    )
    check_part(folder, part)
    try:
        raw = read_json(attempt / "recognizer.json", 8 * 1024 * 1024)
    except json.JSONDecodeError as exc:
        raise PreviewOutputError("Malformed recognizer JSON") from exc
    return preview_lines(raw, part)


def preview_lines(raw, part):
    try:
        return _preview_lines(raw, part)
    except (click.ClickException, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PreviewOutputError("Invalid recognizer text/timestamps") from exc


def _preview_lines(raw, part):
    """Bound small decoder end-time overruns only in the explicitly provisional projection."""
    if not isinstance(raw.get("transcription"), list):
        raise click.ClickException("Invalid recognizer output; no provisional text accepted")
    lines, previous = [], -1
    for segment in raw["transcription"]:
        a, b = (segment["offsets"][k] for k in ("from", "to"))
        if any(
            type(v) not in (int, float) or not math.isfinite(v) for v in (a, b)
        ) or not isinstance(segment["text"], str):
            raise click.ClickException("Invalid recognizer text/timestamps")
        if a < previous:
            raise click.ClickException("Recognizer timestamps are out of order")
        previous = a
        clipped = part.duration * 1000 < b <= (part.duration + 2) * 1000
        projected = (
            {**segment, "offsets": {"from": a, "to": part.duration * 1000}} if clipped else segment
        )
        segment_lines = audio.transcript_lines({"transcription": [projected]}, part, None)
        if clipped:
            for line in segment_lines:
                line["timingNote"] = (
                    "Recognizer end time exceeded the chunk; preview end clipped to source duration."
                )
        lines.extend(segment_lines)
    return lines


def render_line(line):
    # Never execute terminal controls embedded in recognized speech or display it as Markdown commands.
    text = GAP_NOTICE if line.get("kind") == "preview-gap" else line["text"]
    text = " ".join("".join(c for c in text if c.isprintable()).split())
    seconds = int(line["start"])
    prefix = "~" if line.get("timingNote") else ""
    return f"{prefix}[{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}] {text}"


def process_part(folder, model, root, config, part, transcriber=transcribe_part):
    final = root / f"{Path(part.file).stem}.json"
    if final.exists():
        value = read_json(final)
        if (
            value.get("sourcePart") != part.model_dump()
            or value.get("modelSha256") != config["settings"]["modelSha256"]
        ):
            raise click.ClickException("Saved preview input pin changed")
        # Checkpointed sources are immutable even after preview completion.
        check_part(folder, part)
        raw = root / value["attempt"] / "recognizer.json"
        if raw.is_symlink() or audio.digest(raw) != value["recognizerSha256"]:
            raise click.ClickException("Preserved recognizer output changed")
        return value
    check_part(folder, part)
    if shutil.disk_usage(root).free < 1024**3:
        raise click.ClickException(
            "Less than 1 GiB free: preview stopped to conserve recording space. Capture is independent"
        )
    attempt = root / f"attempt-{uuid.uuid4().hex}"
    attempt.mkdir(mode=0o700)
    started = time.monotonic()
    try:
        lines = transcriber(folder, part, model, attempt)
    except PreviewOutputError:
        # Discard the entire provisional projection, not the preserved raw output. The interval
        # comes from the verified source chunk, never the recognizer's invalid timestamps.
        # Persist once so resume advances instead of retrying the same bad recognition forever.
        lines = [{"kind": "preview-gap", "start": part.start,
                  "end": part.start + part.duration, "text": GAP_NOTICE}]
    check_part(folder, part)
    # Detect weights changed during execution, not merely at the beginning of the preview.
    if audio.digest(model) != config["settings"]["modelSha256"]:
        raise click.ClickException("Whisper weights changed; preview stopped")
    raw = attempt / "recognizer.json"
    value = {
        "schemaVersion": 1,
        "entityType": "LiveTranscriptChunk",
        "reviewStatus": "provisional",
        "recordingId": folder.name,
        "sourcePart": part.model_dump(),
        "sourceKeys": [f"games/{config['gameId']}/assets/{folder.name}/original/{part.file}"],
        "modelSha256": config["settings"]["modelSha256"],
        "attempt": attempt.name,
        "recognizerSha256": audio.digest(raw),
        "processingSeconds": round(time.monotonic() - started, 3),
        "segments": lines,
        "extra": config["extra"],
    }
    write_json(final, value)
    return value


def presentation(root, config, values, status):
    """Rebuildable plain-text view; immutable recognizer/chunk results remain separate."""
    lines = [
        NOTICE,
        "Capture and cloud backup run independently. Preview text can be wrong.",
        f"Earlier chunks omitted: {config['startIndex']} (use --from-start for a separate full preview).",
        f"Status: {status['state']}; queued chunks: {status['pendingChunks'] if status['pendingChunks'] is not None else 'unknown'}",
        "",
    ]
    for value in values:
        lines.extend(render_line(line) for line in value["segments"])
        if not value["segments"]:
            lines.append(
                f"[{value['sourcePart']['start']:.0f}s] No speech recognized in this chunk (not proof of silence)."
            )
    temporary = root / f".preview-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text("\n".join(lines) + "\n")
        os.replace(temporary, root / "preview.txt")
    finally:
        temporary.unlink(missing_ok=True)
    write_json(root / "status.json", status, replace=True)


def follow(
    folder,
    model,
    *,
    from_start=False,
    once=False,
    transcriber=transcribe_part,
    emit=click.echo,
    publish=False,
    preview_name=None,
):
    folder, model, header, root, config = initialize(folder, model, from_start, preview_name)
    emit(NOTICE)
    emit(
        f"Preview file: {root / 'preview.txt'}\nCtrl+C stops ONLY this preview; keep the recording terminal open."
    )
    values = []
    from panther_journal.live_publish import Publisher

    with (
        lock(root, "preview.lock"),
        Publisher(folder, header, root, config, emit) if publish else nullcontext(),
    ):
        try:
            parts = completed_parts(folder, header)
            for part in parts[config["startIndex"] :]:
                if not (root / f"{Path(part.file).stem}.json").exists():
                    break
                values.append(process_part(folder, model, root, config, part, transcriber))
            if values:
                emit(
                    f"Resuming {len(values)} saved preview chunk(s); prior text remains in preview.txt."
                )
                for line in values[-1]["segments"]:
                    emit(render_line(line))
            while True:
                if audio.digest(folder / "capture.json") != config["settings"]["captureSha256"]:
                    raise click.ClickException("Capture identity changed")
                parts = completed_parts(folder, header)
                index = config["startIndex"] + len(values)
                if index < len(parts):
                    presentation(
                        root,
                        config,
                        values,
                        {
                            "schemaVersion": 1,
                            "state": "transcribing",
                            "pendingChunks": len(parts) - index,
                            "chunksTranscribed": len(values),
                            "checkedAt": time.time(),
                            "error": None,
                        },
                    )
                    emit(
                        f"Transcribing {parts[index].start:.0f}s–{parts[index].start + parts[index].duration:.0f}s; {len(parts) - index} chunk(s) queued…"
                    )
                    value = process_part(folder, model, root, config, parts[index], transcriber)
                    values.append(value)
                    if any(line.get("timingNote") for line in value["segments"]):
                        emit(
                            "~ Approximate timing: decoder end time clipped to this chunk; original output retained."
                        )
                    for line in value["segments"]:
                        emit(render_line(line))
                    if not value["segments"]:
                        emit("[No speech recognized in this chunk—not proof of silence.]")
                    index += 1
                    if value["processingSeconds"] > parts[index - 1].duration:
                        emit("Preview is slower than capture and may lag; recording is unaffected.")
                running = capture_running(folder)
                pending = max(0, len(parts) - index)
                state = "catching-up" if pending else "waiting-for-chunk" if running else "stopped"
                status = {
                    "schemaVersion": 1,
                    "state": state,
                    "pendingChunks": pending,
                    "chunksTranscribed": len(values),
                    "captureRunning": running,
                    "finalRecordingManifestPresent": (folder / "recording.json").is_file(),
                    "checkedAt": time.time(),
                    "error": None,
                }
                presentation(root, config, values, status)
                if once:
                    emit("One-chunk preview finished; recording was not stopped.")
                    return root
                if not running and not pending:
                    # Capture may have published its final checkpoint during the transcription pass.
                    if len(completed_parts(folder, header)) > index:
                        continue
                    emit(
                        "Capture is no longer active. Preview saved; full transcription/player attribution is still separate."
                    )
                    return root
                if not pending:
                    time.sleep(2)
        except KeyboardInterrupt:
            presentation(
                root,
                config,
                values,
                {
                    "state": "preview-stopped",
                    "pendingChunks": None,
                    "error": None,
                    "checkedAt": time.time(),
                },
            )
            emit("Live preview stopped. Recording was not stopped.")
            return root
        except Exception:
            presentation(
                root,
                config,
                values,
                {
                    "state": "preview-error",
                    "pendingChunks": None,
                    "error": "Preview failed; capture is independent. Inspect the private attempt logs.",
                    "checkedAt": time.time(),
                },
            )
            raise


@click.command("live")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--model",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=DEFAULT_MODEL,
    show_default=True,
    help="Existing local Whisper weights; no automatic model download.",
)
@click.option(
    "--from-start",
    is_flag=True,
    help="Catch up from the beginning instead of the latest completed chunk.",
)
@click.option(
    "--once", is_flag=True, help="Process at most one available completed chunk, then exit."
)
@click.option(
    "--local-only", is_flag=True, help="Do not publish the provisional web feed/heartbeat."
)
@click.option(
    "--preview-name",
    help="Named resumable preview; a new name joins the latest chunk without replacing older previews.",
)
def live(folder, model, from_start, once, local_only, preview_name):
    """Follow provisional local transcript text in a second terminal; Ctrl+C leaves capture running."""
    for name in ("ffmpeg", "whisper-cli", "nice"):
        audio.executable(name)
    try:
        follow(
            folder,
            model,
            from_start=from_start,
            once=once,
            publish=not local_only and not once,
            preview_name=preview_name,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise click.ClickException(
            "Live preview failed; capture is unaffected. Check the private preview logs and inputs."
        ) from exc
