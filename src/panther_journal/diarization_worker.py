"""Invoked in the separate local audio runtime; no cloud inference or saved token."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

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

    import numpy as np
    import torch
    from pyannote.audio import Pipeline

    torch.set_num_threads(4)
    record = json.loads((args.folder / "recording.json").read_text())
    waves = []
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
    waveform = torch.from_numpy(np.concatenate(waves)).unsqueeze(0)
    del waves
    pipeline = Pipeline.from_pretrained(args.model.resolve())
    options = {"num_speakers": args.speakers} if args.speakers else {}
    result = pipeline({"waveform": waveform, "sample_rate": 16000}, **options)
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


if __name__ == "__main__":
    main()
