"""Completed-chunk checkpoints and retryable Panther uploads, independent of capture."""

import csv
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

import click

from panther_journal import cloud
from panther_journal import recording as audio
from panther_journal.audio_storage import (
    capture_active,
    flush_directory,
    flush_file,
    lock,
    write_json,
)


def checkpoints(folder):
    result = []
    for file in sorted((folder / "checkpoints").glob("part-*.json")):
        data = json.loads(file.read_text())
        part = audio.Part.model_validate(data["part"])
        if part.file != f"part-{len(result):04d}.flac" or file.stem != Path(part.file).stem:
            raise click.ClickException("Invalid checkpoint ordering.")
        if data["recordingId"] != folder.name:
            raise click.ClickException("Checkpoint belongs to a different recording.")
        result.append(part)
    return result


def checkpoint(folder, metadata, *, final=False, allow_incomplete=False):
    """CSV rows are emitted only after FFmpeg closes a part. Never upload its active output."""
    journal = folder / "checkpoints"
    journal.mkdir(mode=0o700, exist_ok=True)
    flush_directory(folder)
    parts = checkpoints(folder)
    pcm = (folder / "capture-pcm").is_dir()
    capture_folder = folder / "capture-pcm" if pcm else folder
    suffix = "wav" if pcm else "flac"
    if final:
        files = sorted(capture_folder.glob(f"part-*.{suffix}"))
    else:
        listing = folder / "segments.csv"
        raw = listing.read_text() if listing.exists() else ""
        complete_lines = raw[: raw.rfind("\n") + 1]
        rows = list(csv.reader(complete_lines.splitlines()))
        files = []
        for row in rows:
            if len(row) != 3:
                raise click.ClickException("Invalid capture journal.")
            expected = f"part-{len(files):04d}.{suffix}"
            if row[0] != expected:
                raise click.ClickException("Unexpected filename in capture journal.")
            files.append(capture_folder / expected)
    for i, source in enumerate(files):
        file = folder / f"part-{i:04d}.flac"
        if source.name != f"part-{i:04d}.{suffix}" or source.is_symlink() or file.is_symlink():
            raise click.ClickException("Unexpected recording part; files retained.")
        if i < len(parts):
            if final and (
                file.stat().st_size != parts[i].size or audio.digest(file) != parts[i].sha256
            ):
                raise click.ClickException("A checkpointed recording part changed.")
            continue
        try:
            if pcm:
                flush_file(source)
                temporary = folder / f".encoding-{uuid.uuid4().hex}.flac"
                try:
                    subprocess.run(
                        [
                            audio.executable("flac"),
                            "--verify",
                            "--silent",
                            "--keep-foreign-metadata-if-present",
                            "-o",
                            str(temporary),
                            str(source),
                        ],
                        check=True,
                        capture_output=True,
                        timeout=300,
                    )
                    flush_file(temporary)
                    if file.exists():
                        if audio.digest(file) != audio.digest(temporary):
                            raise click.ClickException(
                                "Uncheckpointed FLAC differs from captured PCM; refusing overwrite."
                            )
                    else:
                        os.link(temporary, file)
                    flush_directory(folder)
                finally:
                    temporary.unlink(missing_ok=True)
            subprocess.run(
                [audio.executable("flac"), "--test", "--silent", str(file)],
                check=True,
                capture_output=True,
                timeout=300,
            )
            details = audio.probe(file)
            flush_file(file)
            part = audio.Part(
                file=file.name,
                start=sum(p.duration for p in parts),
                size=file.stat().st_size,
                sha256=audio.digest(file),
                **details,
            )
        except (subprocess.CalledProcessError, ValueError) as exc:
            if not (final and allow_incomplete and i == len(files) - 1 and parts):
                raise click.ClickException(
                    f"Cannot validate {source.name}; source files retained."
                ) from exc
            report = folder / "incomplete-tail.json"
            if not report.exists():
                audio.write_new(
                    report,
                    {
                        "file": str(source.relative_to(folder)),
                        "excludedFromManifest": True,
                        "reason": "Incomplete or invalid final part; original retained",
                    },
                )
            click.echo(f"Retained but excluded incomplete tail: {source.name}", err=True)
            break
        audio.write_new(
            journal / f"{file.stem}.json",
            {
                "schemaVersion": 1,
                "entityType": "RecordingCheckpoint",
                "recordingId": metadata["id"],
                "gameId": metadata["gameId"],
                "sessionId": metadata["sessionId"],
                "part": part.model_dump(),
            },
        )
        parts.append(part)
    if final and len(files) < len(parts):
        raise click.ClickException("A checkpointed part is missing.")
    return parts


def sync_once(folder):
    metadata = json.loads((folder / "capture.json").read_text())
    if (
        not (folder / "recording.json").exists()
        and not capture_active(folder)
        and (list(folder.glob("part-*.flac")) or list((folder / "capture-pcm").glob("part-*.wav")))
    ):
        with lock(folder, "capture.lock"):
            if not (folder / "recording.json").exists():
                audio.finish_capture(folder, metadata, "interrupted")
    complete = (folder / "recording.json").exists()
    if complete:
        record = audio.verified(folder)
    else:
        parts = checkpoints(folder)
        if not parts:
            return {"partsSynced": 0, "complete": False}
        record = audio.Recording(**metadata, status="interrupted", parts=parts)
    config = cloud.configuration()
    cloud.api(config, "GET", "/game", params={"gameId": record.gameId})
    receipts = folder / "sync-receipts"
    receipts.mkdir(mode=0o700, exist_ok=True)

    def send(file, kind):
        if file.is_symlink():
            raise click.ClickException("Refusing symlinked sync input.")
        expected = {"sha256": audio.digest(file), "size": file.stat().st_size}
        receipt = receipts / f"{file.name}.json"
        if receipt.exists():
            if json.loads(receipt.read_text()) != expected:
                raise click.ClickException("Previously synced file changed; refusing overwrite.")
            return
        audio.upload_one(config, file, record, kind)
        audio.write_new(receipt, expected)

    send(folder / "capture.json", "recording-manifest")
    for part in record.parts:
        file = folder / part.file
        if file.stat().st_size != part.size or audio.digest(file) != part.sha256:
            raise click.ClickException("Checkpointed audio changed; refusing sync.")
        send(file, "recording")
        journal = folder / "checkpoints" / f"{file.stem}.json"
        if journal.exists():
            send(journal, "recording-checkpoint")
    if complete:
        send(folder / "recording.json", "recording-manifest")
    return {"partsSynced": len(record.parts), "complete": complete}


@click.command("sync")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--watch", is_flag=True, help="Retry periodically while capture is active; otherwise sync once."
)
@click.option("--interval", type=click.IntRange(5, 300), default=30, show_default=True)
def sync(folder, watch, interval):
    """Upload completed parts through Panther. Never upload an active chunk or delete local files."""
    folder = folder.resolve()
    with lock(folder, "sync.lock"):
        while True:
            try:
                status = sync_once(folder)
                stopped = not capture_active(folder)
                # Capture may finish while the last network request is in flight. Publish
                # its final manifest before exiting instead of leaving the last chunk behind.
                if watch and not status["complete"] and stopped:
                    status = sync_once(folder)
                status["error"] = None
            except Exception as exc:
                stopped = not capture_active(folder)
                # Do not persist authenticated request URLs or credential-bearing tracebacks.
                status = {"complete": False, "error": type(exc).__name__}
                click.echo(
                    f"Sync pending ({type(exc).__name__}); recording is unaffected.", err=True
                )
            status["checkedAt"] = time.time()
            write_json(folder / "sync-status.json", status, replace=True)
            if not watch or stopped:
                if status["error"]:
                    raise click.ClickException(
                        "Sync unfinished. Check Panther login/network and run recording sync again."
                    )
                click.echo(json.dumps(status))
                return
            time.sleep(interval)
