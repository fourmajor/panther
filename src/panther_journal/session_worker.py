"""Completed-set session automation on owned compute, with immutable checkpoints.

The server's verified completed sets are the durable queue. Local state is a
checkpoint, never permission to run on an incomplete capture or spend money.
"""

import hashlib
import base64
import json
import os
from pathlib import Path
import time
import uuid

import click

from panther_journal import cloud, recording as audio, live_transcript as live
from panther_journal.audio_storage import lock, write_json, flush_file, flush_directory
from panther_journal.capture_audit import audit
from panther_journal.model_workflow import download
from panther_journal.workflows import Reporter

STAGES = ["verify-inputs", "preserve-raw-transcript", "match-players", "publish-transcripts", "start-adaptations"]


def checkpoint_write(path, value):
    checksum = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    write_json(path, {"value": value, "sha256": checksum})


def checkpoint_read(path):
    saved = live.read_json(path)
    value = saved["value"]
    if hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest() != saved["sha256"]:
        raise click.ClickException("Finalization checkpoint changed")
    return value


def save_transcript(destination, document):
    """Atomically publish each pair member and reconcile a stop between them."""
    identity = destination.name
    json_file = destination / f"{identity}.json"
    if not json_file.exists():
        write_json(json_file, document)
    elif json_file.is_symlink() or json.loads(json_file.read_text()) != document:
        raise click.ClickException("Saved transcript changed; refusing overwrite")
    people = {p["id"]: p["name"] for p in document["players"]}
    text = "# Transcript — unreviewed\n\nPlayer identity is separate from character voice or table chatter.\n\n"
    text += "".join(f"[{line['start']:.2f}–{line['end']:.2f}] {people.get(line['playerId'], 'Unassigned')}: {line['text']}\n\n" for line in document["segments"])
    md = destination / f"{identity}.md"
    if md.exists():
        if md.is_symlink() or md.read_text() != text:
            raise click.ClickException("Saved transcript export changed")
        return
    temporary = destination / (".export-" + uuid.uuid4().hex)
    try:
        with temporary.open("x") as stream:
            stream.write(text)
        flush_file(temporary)
        os.link(temporary, md)
        flush_directory(destination)
    finally:
        temporary.unlink(missing_ok=True)


def settings(path):
    from panther_journal.speaker_profiles import private_path
    path = private_path(path)
    value = live.read_json(path)
    if value.get("schemaVersion") != 1 or not isinstance(value.get("games"), dict):
        raise click.ClickException("Supply private version-1 session-worker configuration")
    for game, config in value["games"].items():
        cloud.slug(game)
        if set(config) != {"whisperModel", "speakerProfiles", "speakerModel", "speakerRuntime", "recordingsRoot", "completedAfter"}:
            raise click.ClickException("Invalid game worker configuration")
        if type(config["completedAfter"]) not in (float, int) or config["completedAfter"] < 0:
            raise click.ClickException("Set an explicit completion-time activation boundary")
        for name, item in config.items():
            if name == "completedAfter":
                continue
            if not isinstance(item, str) or not Path(item).is_absolute():
                raise click.ClickException("Worker paths must be absolute")
            private_path(Path(item))
    return value


def completed_sets(config):
    cursor = None
    while True:
        page = cloud.api(config, "GET", "/recording-playback-jobs", params={"cursor": cursor} if cursor else {})
        yield from (job for job in page["jobs"] if job.get("setStatus") == "COMPLETE")
        cursor = page.get("cursor")
        if not cursor:
            return


def local_recording(job, config, root):
    """Use exact local evidence if available, otherwise checksum-download cloud pins."""
    from panther_journal.speaker_profiles import private_path
    base = private_path(Path(config["recordingsRoot"]))
    for file in base.rglob("recording.json"):
        if file.parent.name == job["chunkSetId"] and audio.digest(file) == base64.b64decode(job["recording"]["sha256"]).hex():
            private_path(file)
            audio.verified(file.parent)
            return file.parent
    folder = root / job["chunkSetId"]
    folder.mkdir(mode=0o700, exist_ok=True)
    prefix = f"games/{job['gameId']}/assets/{job['chunkSetId']}/original/"
    connection = cloud.configuration()
    if job["workflowVersion"] != 1:
        raise click.ClickException("This local finalizer currently requires FLAC source sets")
    for index, ref in enumerate([job["recording"], *job["chunks"]]):
        name = "recording.json" if index == 0 else f"part-{index - 1:04d}.flac"
        if ref["key"] != prefix + name:
            raise click.ClickException("Invalid completed-set input path")
        download(connection, ref, folder / name)
    record = audio.verified(folder)
    header = {k: getattr(record, k) for k in ("id", "gameId", "sessionId", "startedAt", "device")}
    if not (folder / "capture.json").exists():
        write_json(folder / "capture.json", header)
    elif live.read_json(folder / "capture.json") != header:
        raise click.ClickException("Downloaded capture header changed")
    return folder


def transcript(folder, job, options, target, report):
    """Reuse verified live ASR; recognize only absent or gapped chunks. Never use context."""
    from panther_journal import speaker_profiles as speakers
    record = audio.verified(folder)
    if record.id != job["chunkSetId"] or record.gameId != job["gameId"]:
        raise click.ClickException("Recording identity differs from verified completion")
    model = Path(options["whisperModel"])
    model_hash = audio.digest(model)
    profiles = speakers.load_profiles(Path(options["speakerProfiles"]), record.gameId, Path(options["speakerModel"]))
    profiles_hash = audio.digest(Path(options["speakerProfiles"]))
    game = cloud.api(cloud.configuration(), "GET", "/game", params={"gameId": record.gameId})
    ids = {p["id"] for p in game["players"]}
    if not {p["playerId"] for p in profiles["profiles"]} <= ids:
        raise click.ClickException("Enrolled speakers are not in this game")
    raw, attributed, evidence = [], [], []
    target.mkdir(mode=0o700, exist_ok=True)
    with speakers.SpeakerWorker(target, Path(options["speakerModel"]), Path(options["speakerRuntime"])) as analyzer:
        for index, part in enumerate(record.parts):
            if audio.digest(Path(options["speakerProfiles"])) != profiles_hash:
                raise click.ClickException("Speaker enrollment changed during processing")
            checkpoint = target / f"part-{index:04d}.json"
            if checkpoint.exists():
                value = checkpoint_read(checkpoint)
                if value["part"] != part.model_dump() or value["modelSha256"] != model_hash or value["profilesSha256"] != profiles_hash:
                    raise click.ClickException("Finalization checkpoint input changed")
            else:
                working = target / f"part-{index:04d}-working.json"
                prior = checkpoint_read(working) if working.exists() else None
                attempt = target / (prior["attempt"] if prior else f"part-{index:04d}-evidence-{uuid.uuid4().hex}")
                if attempt.parent != target or attempt.is_symlink():
                    raise click.ClickException("Invalid evidence directory")
                attempt.mkdir(mode=0o700, exist_ok=True)
                lines = prior["raw"] if prior else None
                pins = prior["evidence"] if prior else None
                for preview in ([] if lines is not None else sorted((folder / "live-preview").glob("*/preview.json"))):
                    config = live.read_json(preview)
                    if config["settings"].get("modelSha256") != model_hash or not (preview.parent / f"part-{index:04d}.json").is_file():
                        continue
                    saved = live.process_part(folder, model, preview.parent, config, part)
                    if not any(s.get("kind") == "preview-gap" for s in saved["segments"]):
                        lines = saved["segments"]
                        pins = {"preview": str(preview.parent), "checkpointSha256": audio.digest(preview.parent / f"part-{index:04d}.json"), "recognizerSha256": saved["recognizerSha256"]}
                        break
                if lines is None:
                    lines = live.transcribe_part(folder, part, model, attempt, use_gpu=True)
                    pins = {"recognizerSha256": audio.digest(attempt / "recognizer.json")}
                clean = [{**line, "playerId": None, "attribution": "unassigned"} for line in lines]
                for line in clean:
                    line.pop("speakerLabel", None)
                    line.pop("sourcePart", None)
                    line["sourceParts"] = [part.file]
                if not prior:
                    checkpoint_write(working, {"attempt": attempt.name, "raw": clean, "evidence": pins})
                wav = attempt / "speaker-input.wav"
                if not wav.exists():
                    live.run_process([audio.executable("ffmpeg"), "-v", "error", "-nostdin", "-n", "-i", str(folder / part.file), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], attempt, "speaker-decode.log")
                speaker_attempt = attempt / ("speaker-" + uuid.uuid4().hex)
                speaker_attempt.mkdir(mode=0o700)
                result_file = speaker_attempt / "speaker-result.json"
                result = analyzer.analyze(wav, speaker_attempt)
                assigned = speakers.label_lines(clean, result, profiles["profiles"], part.start)
                value = {"part": part.model_dump(), "modelSha256": model_hash, "profilesSha256": profiles_hash, "raw": clean, "attributed": assigned, "evidence": pins, "speakerResultPath": str(result_file.relative_to(target)), "speakerResultSha256": audio.digest(result_file)}
                checkpoint_write(checkpoint, value)
            # Do not silently trust modified local speaker evidence after a restart.
            evidence_file = target / value["speakerResultPath"]
            if evidence_file.is_symlink() or not evidence_file.resolve().is_relative_to(target.resolve()) or audio.digest(evidence_file) != value["speakerResultSha256"]:
                raise click.ClickException("Speaker evidence changed")
            raw.extend(value["raw"])
            attributed.extend(value["attributed"])
            evidence.append({"chunk": part.file, "checkpointSha256": audio.digest(checkpoint)})
            write_json(target / "progress.json", {"stage": "recognition-and-attribution", "completed": index + 1, "total": len(record.parts), "percent": round(100 * (index + 1) / len(record.parts), 1), "updatedAt": time.time()}, replace=True)
    if audio.digest(model) != model_hash or speakers.model_pin(Path(options["speakerModel"])) != profiles["modelFiles"]:
        raise click.ClickException("Recognition model weights changed during processing")
    base = {"schemaVersion": 1, "entityType": "PlayerTranscript", "artifactType": "raw-transcript", "gameId": record.gameId,
            "sessionId": record.sessionId, "recordingId": record.id, "sourceParts": [p.model_dump() for p in record.parts],
            "captureIntegrity": audit(folder), "engine": "whisper.cpp", "modelSha256": model_hash, "players": game["players"],
            "reviewStatus": "unreviewed", "speakerMethod": "unassigned", "finalizationEvidence": evidence}
    raw_id = "transcript-" + hashlib.sha256((job["jobId"] + model_hash + "raw-v1").encode()).hexdigest()[:32]
    assigned_id = "transcript-" + hashlib.sha256((job["jobId"] + profiles_hash + model_hash + "attributed-v1").encode()).hexdigest()[:32]
    paths = []
    for identity, segments, extra in [(raw_id, raw, {}), (assigned_id, attributed, {"speakerMethod": "enrolled-voice-chunk-matching", "reviewStatus": "provisional", "sourceTranscriptId": raw_id})]:
        destination = folder / identity
        destination.mkdir(mode=0o700, exist_ok=True)
        document = {**base, "id": identity, "segments": segments, **extra}
        save_transcript(destination, document)
        paths.append(destination)
    report.stage("preserve-raw-transcript", "done")
    report.stage("match-players", "done")
    return record, paths


def process(job, options, root):
    identity = hashlib.sha256((job["jobId"] + "session-finalization-v1").encode()).hexdigest()
    target = root / identity
    target.mkdir(mode=0o700, exist_ok=True)
    state_file = target / "state.json"
    if state_file.exists() and live.read_json(state_file).get("status") == "done":
        return
    report = Reporter(target, identity, job["gameId"], "Session finalization · " + job["sessionId"], STAGES, kind="session-finalization")
    report.enter()
    try:
        folder = local_recording(job, options, target)
        report.stage("verify-inputs", "done")
        report.stage("preserve-raw-transcript", "running")
        report.stage("match-players", "running")
        record, paths = transcript(folder, job, options, target / "recognition", report)
        report.stage("publish-transcripts", "running")
        config = cloud.configuration()
        raw_key = None
        for directory in paths:
            keys = []
            for suffix in ("json", "md"):
                keys.append(audio.upload_one(config, directory / f"{directory.name}.{suffix}", record, "raw-transcript",
                    source_keys=[raw_key] if raw_key else [job["recording"]["key"]]))
            raw_key = keys[0]
        report.stage("publish-transcripts", "done")
        report.stage("start-adaptations", "running")
        editorial = cloud.api(config, "POST", "/editorial-jobs", json={"gameId": job["gameId"], "rawKey": raw_key})
        write_json(state_file, {"status": "done", "completedSetJobId": job["jobId"], "rawKey": raw_key, "editorialJobId": editorial["jobId"]}, replace=True)
        report.stage("start-adaptations", "done")
        report.close("done")
    except Exception:
        write_json(target / "failure.json", {"status": "failed", "failedAt": time.time(), "message": "Session finalization stopped; inspect private worker logs and checkpoints. Originals are retained."}, replace=True)
        report.close("failed")
        raise


@click.group("automation")
def automation():
    """Finalize verified recordings and automatically start story/screen adaptations."""


@automation.command("worker")
@click.option("--config", "config_file", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--work-dir", required=True, type=click.Path(path_type=Path))
@click.option("--once", is_flag=True)
def worker(config_file, work_dir, once):
    from panther_journal.speaker_profiles import private_path
    os.umask(0o077)
    root = private_path(work_dir)
    if root in {Path.home(), Path("/")}:
        raise click.ClickException("Use a dedicated private worker directory")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    options = settings(config_file)
    with lock(root, "worker.lock"):
        while True:
            for job in completed_sets(cloud.configuration()):
                if job["gameId"] in options["games"] and job["createdAt"] >= options["games"][job["gameId"]]["completedAfter"]:
                    try:
                        process(job, options["games"][job["gameId"]], root)
                    except Exception as exc:
                        # Do not expose credential-bearing URLs/provider exceptions.
                        click.echo("Session finalization failed; private checkpoints retained (" + type(exc).__name__ + ").", err=True)
            if once:
                return
            time.sleep(60)
