"""Identity embeddings that use the same extractor as confirmed enrollment.

Cluster centroids are a different statistic. Comparing them with a full-waveform
enrollment prototype can miss every speaker. Exclusive diarization is the timeline
meant for transcript alignment; the overlapping annotation is kept for audit.
"""

REFERENCE_EMBEDDING_METHOD = "community-1-exclusive-speech-waveform-v1"
EXCLUSIVE_TURN_SOURCE = "exclusive-speaker-diarization"
REFERENCE_MAX_SECONDS = 30.0
REFERENCE_MIN_SECONDS = 1.0


def annotation_turns(annotation):
    return [
        {"start": float(turn.start), "end": float(turn.end), "speaker": speaker}
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]


def exclusive_speech(
    samples,
    turns,
    speaker,
    sample_rate=16000,
    max_seconds=REFERENCE_MAX_SECONDS,
    minimum_seconds=REFERENCE_MIN_SECONDS,
):
    """Longest exclusive turns for one speaker, capped, in enrollment-sized audio."""
    selected = [
        turn
        for turn in turns
        if turn.get("speaker") == speaker and float(turn["end"]) > float(turn["start"])
    ]
    selected.sort(key=lambda turn: float(turn["end"]) - float(turn["start"]), reverse=True)
    pieces = []
    remaining = int(round(max_seconds * sample_rate))
    total = 0
    length = len(samples)
    for turn in selected:
        if remaining <= 0:
            break
        start = max(0, min(length, int(round(float(turn["start"]) * sample_rate))))
        end = max(start, min(length, int(round(float(turn["end"]) * sample_rate))))
        take = min(end - start, remaining)
        if take <= 0:
            continue
        pieces.append(samples[start : start + take])
        remaining -= take
        total += take
    if total < int(round(minimum_seconds * sample_rate)) or not pieces:
        return None
    return _concatenate(pieces)


def _concatenate(pieces):
    first = pieces[0]
    if hasattr(first, "dtype"):
        import numpy as np

        return np.concatenate(pieces)
    merged = []
    for piece in pieces:
        merged.extend(piece)
    return merged


def reference_embeddings(embed, samples, turns, sample_rate=16000):
    """One enrollment-style vector per diarized speaker. Centroids are not inputs."""
    embeddings, unavailable = {}, {}
    speakers = list(dict.fromkeys(turn["speaker"] for turn in turns))
    for speaker in speakers:
        speech = exclusive_speech(samples, turns, speaker, sample_rate=sample_rate)
        if speech is None:
            embeddings[speaker] = None
            unavailable[speaker] = {
                "reason": "insufficient-exclusive-speech",
                "minimumSeconds": REFERENCE_MIN_SECONDS,
            }
            continue
        try:
            embeddings[speaker] = embed(speech)
        except Exception as exc:
            embeddings[speaker] = None
            unavailable[speaker] = {
                "reason": "reference-extraction-failed",
                "errorType": type(exc).__name__,
            }
    return embeddings, unavailable
