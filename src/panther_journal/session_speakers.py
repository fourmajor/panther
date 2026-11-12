"""Session-wide, enrolled-voice reconciliation without rewriting speech."""

import copy
import json
from pathlib import Path

import click

from panther_journal import recording as audio, speaker_profiles as speakers
from panther_journal.audio_storage import write_json
from panther_journal.speaker_reference import EXCLUSIVE_TURN_SOURCE, REFERENCE_EMBEDDING_METHOD
from panther_journal.word_attribution import decision

# A working enrolled table lands well above this. Zero or near-zero means the
# mapping did not run, not that every voice was genuinely unknown.
MINIMUM_ASSIGNED_SEGMENT_PERCENT = 25


def reconcile(document, diarization, profiles):
    if (
        document["recordingId"] != diarization["recordingId"]
        or document["sourceParts"] != diarization["sourceParts"]
    ):
        raise click.ClickException("Session speaker evidence belongs to different audio")
    if (
        profiles["gameId"] != document["gameId"]
        or profiles["modelFiles"] != diarization["modelFiles"]
    ):
        raise click.ClickException("Session speaker profiles/model differ")
    roster = {p["id"] for p in document["players"]}
    if not {p["playerId"] for p in profiles["profiles"]} <= roster:
        raise click.ClickException("Enrolled players are not in transcript roster")
    turns = [audio.SpeakerTurn.model_validate(t) for t in diarization["turns"]]
    if any(t.end > sum(p["duration"] for p in document["sourceParts"]) + 1 for t in turns):
        raise click.ClickException("Session speaker turns exceed audio")
    mapping, _unavailable, reports = speakers.map_speakers(diarization, profiles["profiles"])
    if {t.speaker for t in turns} - mapping.keys():
        raise click.ClickException("Detected speakers lack session embedding evidence")
    result = copy.deepcopy(document)
    for line in result["segments"]:
        line["previousAttribution"] = {
            key: copy.deepcopy(line[key])
            for key in ("playerId", "speakerLabel", "attribution", "attributionWarnings")
            if key in line
        }
        line.pop("attributionWarnings", None)
        if line.get("timingMethod") == "verified-chunk-boundaries" or line["end"] <= line["start"]:
            line.update(playerId=None, speakerLabel=None, attribution="unassigned")
            continue
        label, player, evidence = decision(line["start"], line["end"], turns, mapping, 0.65, 0.25)
        line.update(
            playerId=player,
            speakerLabel=label,
            attribution="provisional-enrolled-session-voice" if player else "unassigned",
            sessionAttributionEvidence=evidence,
        )
    result["speakerMethod"] = "enrolled-voice-session-reconciliation-v1"
    assigned = [line for line in result["segments"] if line.get("playerId")]
    result["speakerAttributionSummary"] = {
        "segments": len(result["segments"]),
        "assignedSegments": len(assigned),
        "unassignedSegments": len(result["segments"]) - len(assigned),
        "assignedSegmentPercent": 100 * len(assigned) / len(result["segments"])
        if result["segments"]
        else 0,
        "speakerMatches": reports,
        "embeddingMethod": diarization.get("embeddingMethod"),
        "turnSource": diarization.get("turnSource"),
        "minimumAssignedSegmentPercent": MINIMUM_ASSIGNED_SEGMENT_PERCENT,
        "coverageIsNotAccuracy": True,
    }
    result["speakerAttributionPolicy"] = {
        "version": 1,
        "identityMinimumCosine": 0.75,
        "identityWinnerMargin": 0.15,
        "minimumExclusiveCoverage": 0.65,
        "turnWinnerMargin": 0.25,
        "maximumOverlapCoverage": 0.1,
        "coverageIsNotAccuracy": True,
        "note": "Session-wide enrolled voice matching; uncertain identities and overlapping speech remain unknown.",
    }
    return result


def assert_assignment_rate(result, minimum=MINIMUM_ASSIGNED_SEGMENT_PERCENT):
    """Refuse a transcript that diarized speech and then assigned it to nobody."""
    summary = result.get("speakerAttributionSummary") or {}
    segments = summary.get("segments") or 0
    assigned = summary.get("assignedSegments") or 0
    if not segments or assigned * 100 >= minimum * segments:
        return result
    labeled = sum(1 for line in result["segments"] if line.get("speakerLabel"))
    described = []
    for item in summary.get("speakerMatches") or []:
        if item.get("unavailable"):
            shown = "unavailable"
        elif isinstance(item.get("bestCosine"), (int, float)):
            shown = f"{item['bestCosine']:.3f}"
        else:
            shown = "none"
        described.append(
            f"{item.get('speaker')} cosine {shown} ({item.get('playerId') or 'unmatched'})"
        )
    detail = "; ".join(described) if described else "no speaker embedding was matched"
    percent = 100 * assigned / segments
    raise click.ClickException(
        f"Speaker assignment gave players {assigned} of {segments} segments ({percent:.1f}%), "
        f"and {labeled} segments have a diarized label. "
        f"Below the {minimum:g}% floor, so this transcript is not handed to adaptation. {detail}."
    )


def require_reusable_diarization(saved):
    if (
        saved.get("embeddingMethod") != REFERENCE_EMBEDDING_METHOD
        or saved.get("turnSource") != EXCLUSIVE_TURN_SOURCE
    ):
        raise click.ClickException(
            "Saved session diarization has no exclusive reference embeddings. "
            "Leave that file in place and rerun in a new private work directory."
        )
    return saved


def analyze(folder, model, runtime, root, device="mps"):
    record = audio.verified(folder)
    pins = {
        "recordingId": record.id,
        "sourceParts": [p.model_dump() for p in record.parts],
        "modelFiles": speakers.model_pin(model),
        "device": device,
    }
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    pin_file = root / "inputs.json"
    if pin_file.exists():
        if json.loads(pin_file.read_text()) != pins:
            raise click.ClickException("Session analysis inputs changed")
    else:
        write_json(pin_file, pins)
    output = root / "diarization.json"
    if output.exists():
        return require_reusable_diarization(json.loads(output.read_text()))
    from panther_journal.live_transcript import run_process

    run_process(
        [
            str(runtime.absolute()),
            str(Path(__file__).with_name("diarization_worker.py")),
            "--folder",
            str(folder.resolve()),
            "--model",
            str(model.resolve()),
            "--output",
            str(output.resolve()),
            "--device",
            device,
        ],
        root,
        "engine.log",
        timeout=24 * 3600,
    )
    return json.loads(output.read_text())


@click.command("reconcile-speakers")
@click.argument("transcript", type=click.Path(exists=True, path_type=Path, dir_okay=False))
@click.option(
    "--recording",
    "folder",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--profiles", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option("--work-dir", required=True, type=click.Path(path_type=Path))
@click.option(
    "--runtime", default=audio.DEFAULT_RUNTIME, type=click.Path(exists=True, path_type=Path)
)
@click.option(
    "--model", default=audio.DEFAULT_SPEAKER_MODEL, type=click.Path(exists=True, path_type=Path)
)
@click.option("--device", type=click.Choice(["cpu", "mps"]), default="mps")
def command(transcript, folder, profiles, work_dir, runtime, model, device):
    """Save a new transcript candidate with session-wide enrolled identities; no uploads or ASR."""
    from panther_journal.audio_storage import lock
    from panther_journal.session_worker import save_transcript

    record = audio.verified(folder)
    root = speakers.private_path(work_dir)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    document = json.loads(transcript.read_text())
    document = document.get("payload", {}).get("transcript", document)
    if document["recordingId"] != record.id or document["sourceParts"] != [
        p.model_dump() for p in record.parts
    ]:
        raise click.ClickException("Transcript differs from verified recording")
    enrolled = speakers.load_profiles(profiles, record.gameId, model)
    source_hash, profile_hash = audio.digest(transcript), audio.digest(profiles)
    with lock(root, "reconciliation.lock"):
        diarization = analyze(folder, model, runtime, root / "analysis", device)
        result = reconcile(document, diarization, enrolled)
        if audio.digest(transcript) != source_hash or audio.digest(profiles) != profile_hash:
            raise click.ClickException("Transcript or enrollment changed during reconciliation")
        if speakers.model_pin(model) != enrolled["modelFiles"]:
            raise click.ClickException("Speaker model changed during reconciliation")
        import hashlib

        identity = (
            "transcript-"
            + hashlib.sha256(
                (
                    audio.digest(transcript)
                    + audio.digest(profiles)
                    + audio.digest(root / "analysis/diarization.json")
                    + "session-reconciliation-v1"
                ).encode()
            ).hexdigest()[:32]
        )
        result.update(
            id=identity,
            sourceTranscriptId=document["id"],
            sourceTranscriptSha256=audio.digest(transcript),
            diarizationSha256=audio.digest(root / "analysis/diarization.json"),
            recognitionProfilesSha256=audio.digest(profiles),
            reviewStatus="provisional",
        )
        destination = root / identity
        destination.mkdir(mode=0o700, exist_ok=True)
        save_transcript(destination, result)
        receipt = {
            "transcript": str(destination / (identity + ".json")),
            "segments": len(result["segments"]),
            "assigned": sum(bool(s.get("playerId")) for s in result["segments"]),
        }
        if (root / "result.json").exists():
            if json.loads((root / "result.json").read_text()) != receipt:
                raise click.ClickException("Session reconciliation result changed")
        else:
            write_json(root / "result.json", receipt)
        assert_assignment_rate(result)
        click.echo(str(destination))
        return destination
