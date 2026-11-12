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
    from .speaker_profile_worker import runtime_embeddings
    from .speaker_reference import (
        EXCLUSIVE_TURN_SOURCE,
        REFERENCE_EMBEDDING_METHOD,
        annotation_turns,
        reference_embeddings,
    )
except ImportError:  # Script invocation in the separate audio runtime, not the CLI environment.
    from diarization_progress import Progress
    from speaker_profile_worker import runtime_embeddings
    from speaker_reference import (
        EXCLUSIVE_TURN_SOURCE,
        REFERENCE_EMBEDDING_METHOD,
        annotation_turns,
        reference_embeddings,
    )

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["PYANNOTE_METRICS_ENABLED"] = "0"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--speakers", type=int)
    parser.add_argument("--device", choices=['cpu', 'mps'], default='cpu')
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


class _Rows:
    """Give runtime_embeddings a .tolist() row without requiring a NumPy matrix."""

    def __init__(self, rows):
        self._rows = rows

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, index):
        return self._rows[index]


class _Row:
    def __init__(self, values):
        self._values = values

    def tolist(self):
        return list(self._values)


def _finite_embeddings(embeddings):
    clean, rejected = {}, {}
    for label, value in embeddings.items():
        if value is None:
            clean[label] = None
            continue
        row = value if isinstance(value, list) else value.tolist()
        if row and isinstance(row[0], list):
            if len(row) != 1:
                clean[label] = None
                rejected[label] = {"reason": "malformed-reference-embedding"}
                continue
            row = row[0]
        try:
            checked, missing = runtime_embeddings([label], _Rows([_Row(row)]))
        except (TypeError, ValueError):
            clean[label] = None
            rejected[label] = {"reason": "malformed-reference-embedding"}
            continue
        clean[label] = checked[label]
        if label in missing:
            rejected[label] = missing[label]
    return clean, rejected


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
    if args.device == 'mps':
        if not torch.backends.mps.is_available():
            raise RuntimeError('Requested MPS device is unavailable')
        pipeline.to(torch.device('mps'))
        pipeline.segmentation_batch_size = 8
        pipeline.embedding_batch_size = 8
    options = {"num_speakers": args.speakers} if args.speakers else {}
    progress.update('segmentation', force=True)
    result = pipeline({"waveform": waveform, "sample_rate": 16000}, hook=progress, **options)
    progress.update('writing-result', force=True)
    # Overlapping diarization makes almost every table line fail the 10% overlap
    # cap, so the transcript loses both the label and the player. Exclusive turns
    # are the timeline pyannote builds for transcription.
    overlapping = annotation_turns(result.speaker_diarization)
    exclusive_annotation = getattr(result, "exclusive_speaker_diarization", None)
    exclusive = annotation_turns(exclusive_annotation) if exclusive_annotation is not None else None
    if exclusive is not None:
        turns, turn_source = exclusive, EXCLUSIVE_TURN_SOURCE
    else:
        turns, turn_source = overlapping, "speaker-diarization"
    embeddings, unavailable = {}, {}
    if turns:
        samples = waveform.detach().cpu().reshape(-1).numpy()

        def embed(speech):
            # Same call as confirmed enrollment: the full waveform, no cluster centroid.
            audio = torch.from_numpy(np.ascontiguousarray(speech, dtype=np.float32)).reshape(
                1, 1, -1
            )
            return pipeline._embedding(audio)[0].tolist()

        embeddings, unavailable = reference_embeddings(embed, samples, turns)
        embeddings, rejected = _finite_embeddings(embeddings)
        unavailable = {**unavailable, **rejected}
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
        "turnSource": turn_source,
        "overlappingTurns": overlapping if exclusive is not None else [],
        "embeddingMethod": REFERENCE_EMBEDDING_METHOD,
        "embeddings": embeddings,
        "inferenceDevice": args.device,
    }
    if unavailable:
        document["unavailableEmbeddings"] = unavailable
    # Centroids stay diagnostic. They are not the identity prototype: enrollment
    # stores pipeline._embedding of the confirmed waveform, and those two
    # statistics do not cosine-match even for the same voice.
    if getattr(result, "speaker_embeddings", None) is not None:
        labels = list(result.speaker_diarization.labels())
        if len(labels) != len(result.speaker_embeddings):
            raise ValueError("Session speaker embedding labels differ")
        centroids, centroid_gaps = runtime_embeddings(labels, result.speaker_embeddings)
        document["clusterCentroids"] = centroids
        if centroid_gaps:
            document["unavailableClusterCentroids"] = centroid_gaps
    with args.output.open("x") as stream:
        json.dump(document, stream, indent=2, allow_nan=False)
    progress.update('complete', state='complete', force=True)


if __name__ == "__main__":
    main()
