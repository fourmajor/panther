"""One continuous listening derivative; lossless recording parts remain authoritative."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

import click

from panther_journal import recording as audio
from panther_journal.audio_storage import capture_active, flush_directory, flush_file, lock


def build(folder):
    folder = folder.resolve()
    if any((p / ".git").exists() for p in (folder, *folder.parents)):
        raise click.ClickException("Playback files belong outside Git.")
    if capture_active(folder):
        raise click.ClickException("Finish or recover the recording before preparing playback.")
    if (folder / "recording.json").is_symlink():
        raise click.ClickException("Refusing a symlinked recording manifest.")
    with lock(folder, "playback.lock"):
        record = audio.verified(folder)
        source_hash = audio.digest(folder / "recording.json")
        name = f"playback-v1-{source_hash[:16]}"
        target, manifest = folder / f"{name}.mp3", folder / f"{name}.json"
        if manifest.exists():
            doc = json.loads(manifest.read_text())
            if (manifest.is_symlink() or target.is_symlink() or not target.is_file()
                    or doc.get("sourceManifestSha256") != source_hash
                    or doc.get("audioSha256") != audio.digest(target)
                    or doc.get("size") != target.stat().st_size):
                raise click.ClickException("Saved playback changed or is missing; refusing overwrite.")
            return target, manifest, doc
        first = record.parts[0]
        if first.channels not in {1, 2} or first.sampleRate not in {32000, 44100, 48000}:
            raise click.ClickException("Continuous playback currently supports mono/stereo 32/44.1/48 kHz recordings; originals retained.")
        if any((p.channels, p.sampleRate) != (first.channels, first.sampleRate) for p in record.parts):
            raise click.ClickException("Recording formats differ between parts; refusing implicit mixing/resampling.")
        if target.exists():
            raise click.ClickException("Playback exists without its manifest; retain it for recovery, do not overwrite.")
        temporary = folder / f".playback-{uuid.uuid4().hex}.mp3"
        command = [audio.executable("ffmpeg"), "-v", "error", "-xerror", "-nostdin",
                   "-f", "s32le", "-ar", str(first.sampleRate), "-ac", str(first.channels),
                   "-i", "pipe:0", "-map_metadata", "-1", "-c:a", "libmp3lame", "-b:a",
                   "128k" if first.channels == 1 else "192k", "-write_xing", "1",
                   "-f", "mp3", str(temporary)]
        pcm_hash, total_samples, markers = hashlib.sha256(), 0, []
        try:
            with tempfile.TemporaryFile() as errors:
                with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                      stderr=errors) as encoder:
                    try:
                        for part in record.parts:
                            details = audio.probe(folder / part.file)
                            if (details["channels"] != first.channels or details["sampleRate"] != first.sampleRate):
                                raise click.ClickException("Decoded source format differs from manifest.")
                            markers.append({"file": part.file, "start": total_samples / first.sampleRate})
                            decode = [audio.executable("ffmpeg"), "-v", "error", "-xerror", "-nostdin",
                                      "-f", "flac", "-i", str(folder / part.file), "-map", "0:a:0",
                                      "-c:a", "pcm_s32le", "-f", "s32le", "pipe:1"]
                            count = 0
                            with subprocess.Popen(decode, stdout=subprocess.PIPE, stderr=errors) as decoder:
                                try:
                                    while block := decoder.stdout.read(256 * 1024):
                                        count += len(block)
                                        pcm_hash.update(block)
                                        encoder.stdin.write(block)
                                    if decoder.wait(timeout=300):
                                        raise click.ClickException("Could not decode a source part; originals retained.")
                                finally:
                                    if decoder.poll() is None:
                                        decoder.kill()
                            expected = round(part.duration * part.sampleRate) * first.channels * 4
                            if count != expected:
                                raise click.ClickException("Decoded sample count differs from manifest; playback not published.")
                            total_samples += count // (first.channels * 4)
                        encoder.stdin.close()
                        if encoder.wait(timeout=300):
                            raise click.ClickException("Playback encoding failed; originals retained.")
                    finally:
                        if encoder.poll() is None:
                            encoder.kill()
                        # Do not let buffered-pipe cleanup hide the original validation error.
                        try:
                            encoder.stdin.close()
                        except BrokenPipeError:
                            pass
                        encoder.wait(timeout=30)
            # Verify sources again before publishing a derivative; never fix gaps with silence.
            audio.verified(folder)
            if audio.digest(folder / "recording.json") != source_hash:
                raise click.ClickException("Recording manifest changed during assembly.")
            if temporary.stat().st_size > audio.cloud.MAX_UPLOAD_BYTES:
                raise click.ClickException("Playback exceeds Panther's upload limit; originals retained.")
            check = subprocess.run([audio.executable("ffprobe"), "-v", "error", "-show_streams",
                                    "-show_format", "-of", "json", str(temporary)],
                                   check=True, capture_output=True, text=True, timeout=60)
            encoded = json.loads(check.stdout)
            duration = total_samples / first.sampleRate
            if (len(encoded["streams"]) != 1 or encoded["streams"][0]["codec_name"] != "mp3"
                    or abs(float(encoded["format"]["duration"]) - duration) > 0.1):
                raise click.ClickException("Encoded playback duration/format is invalid; originals retained.")
            prefix = f"games/{record.gameId}/assets/{record.id}/original/"
            doc = {
                "schemaVersion": 1, "entityType": "RecordingPlayback", "version": 1,
                "gameId": record.gameId, "recordingId": record.id, "sessionId": record.sessionId,
                "recordingKey": prefix + "recording.json", "audioKey": prefix + target.name,
                "sourceManifestSha256": source_hash,
                "sourceKeys": [prefix + "recording.json", *[prefix + p.file for p in record.parts]],
                "sourceParts": [p.model_dump() for p in record.parts], "partMarkers": markers,
                "audioSha256": audio.digest(temporary), "size": temporary.stat().st_size,
                "durationSeconds": duration, "sampleRate": first.sampleRate, "channels": first.channels,
                "inputSamples": total_samples, "inputPcmSha256": pcm_hash.hexdigest(),
                "codec": "mp3", "container": "mp3", "lossless": False,
                "purpose": "continuous-listening-copy", "recordingStatus": record.status,
                "captureWarning": "Assembly does not repair missing captured audio. Original parts and capture reports remain authoritative.",
            }
            flush_file(temporary)
            os.link(temporary, target)
            flush_directory(folder)
            audio.write_new(manifest, doc)
            return target, manifest, doc
        except (subprocess.SubprocessError, BrokenPipeError) as exc:
            raise click.ClickException("Playback assembly failed; originals retained. Retry preparation, not recording.") from exc
        finally:
            temporary.unlink(missing_ok=True)


def publish(folder, config, record):
    target, manifest, doc = build(folder)
    if doc["recordingId"] != record.id:
        raise click.ClickException("Playback belongs to a different recording.")
    manifest_key = audio.upload_one(config, manifest, record, "recording-playback-manifest")
    key = audio.upload_one(config, target, record, "recording-playback", source_keys=[manifest_key])
    return {"audioKey": key, "manifestKey": manifest_key}


@click.command("playback-preview")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
def playback(folder):
    """Prepare a local-only preview; published playback comes from the completed-set workflow."""
    target, manifest, _ = build(folder)
    click.echo(json.dumps({"playback": str(target), "manifest": str(manifest)}))
