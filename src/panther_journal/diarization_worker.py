"""Invoked in the separate local audio runtime; no cloud inference or saved token."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import signal

try:
    from .diarization_progress import Progress
except ImportError:  # Script invocation in the separate audio runtime, not the CLI environment.
    from diarization_progress import Progress

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["PYANNOTE_METRICS_ENABLED"] = "0"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--speakers", type=int)
    args = parser.parse_args()
    if not args.model.is_dir() or args.output.exists():
        raise SystemExit("Use an existing local model directory and a new output file.")
    os.umask(0o077)
    progress = Progress(args.output.parent / 'progress.json')

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        run(args, progress)
    except BaseException as exc:
        try:
            progress.update(progress.last_stage or 'starting',
                            state='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', force=True)
        except OSError:
            pass
        raise


def run(args, progress):
    progress.update('loading-runtime', force=True)

    import numpy as np
    import torch
    from pyannote.audio import Pipeline

    torch.set_num_threads(4)
    record = json.loads((args.folder / "recording.json").read_text())
    waves = []
    progress.update('decoding', completed=0, total=len(record['parts']), force=True)
    for i, part in enumerate(record["parts"]):
        if part["file"] != f"part-{i:04d}.flac":
            raise SystemExit("Invalid part filename.")
        source = args.folder / part["file"]
        with source.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if source.is_symlink() or checksum != part["sha256"]:
            raise SystemExit("Source integrity check failed.")
        # A temporary in-memory mono/16 kHz derivative, never a replacement for the source.
        decoded = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "f32le",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=600,
        )
        waves.append(np.frombuffer(decoded.stdout, dtype="<f4"))
        progress.update('decoding', completed=i + 1, total=len(record['parts']),
                        force=i + 1 == len(record['parts']))
    waveform = torch.from_numpy(np.concatenate(waves)).unsqueeze(0)
    del waves
    progress.completed_stages.append('decoding')
    progress.update('loading-model', force=True)
    pipeline = Pipeline.from_pretrained(args.model.resolve())
    options = {"num_speakers": args.speakers} if args.speakers else {}
    progress.update('segmentation', force=True)
    result = pipeline({"waveform": waveform, "sample_rate": 16000}, hook=progress, **options)
    progress.update('writing-result', force=True)
    turns = [
        {"start": float(turn.start), "end": float(turn.end), "speaker": speaker}
        for turn, _, speaker in result.speaker_diarization.itertracks(yield_label=True)
    ]
    model_hashes = {}
    for file in sorted(args.model.rglob("*")):
        if file.is_file() and file.suffix in {".bin", ".npz", ".yaml"}:
            with file.open("rb") as stream:
                model_hashes[str(file.relative_to(args.model))] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
    document = {
        "schemaVersion": 1,
        "entityType": "SpeakerDiarization",
        "recordingId": record["id"],
        "sourceParts": record["parts"],
        "engine": "pyannote-community-1",
        "modelFiles": model_hashes,
        "requestedSpeakers": args.speakers,
        "turns": turns,
    }
    with args.output.open("x") as stream:
        json.dump(document, stream, indent=2, allow_nan=False)
    progress.update('complete', state='complete', force=True)


if __name__ == "__main__":
    main()
