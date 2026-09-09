"""Compare captured sample counts with the device-timestamp segment journal; never repair audio."""

import csv
import json
import re
from pathlib import Path

import click


def audit(folder):
    record = json.loads((folder / "recording.json").read_text())
    health_file = folder / "capture-health.json"
    if health_file.exists():
        try:
            health = json.loads(health_file.read_text())
            captured = sum(p["duration"] for p in record["parts"])
            elapsed = health["deviceElapsedSeconds"]
            # ADC host-clock estimates can drift relative to nominal sample rate. Local
            # callback discontinuities are checked separately; never resample to hide either.
            clock_tolerance = max(2 / health["sampleRate"], captured * 100e-6)
            consistent = (
                health["cleanStop"] is True
                and health["errorCode"] == 0
                and health["acceptedFrames"] == health["capturedFrames"]
                and abs(captured - health["capturedFrames"] / health["sampleRate"])
                < 1 / health["sampleRate"]
                and health["maxTimestampGapSeconds"] <= max(0.0001, 2 / health["sampleRate"])
                and abs(elapsed - captured) <= clock_tolerance
            )
            return {
                "status": "consistent" if consistent else "warning",
                "captureHealth": health,
                "capturedSeconds": captured,
                "deviceElapsedSeconds": elapsed,
                "discrepancySeconds": elapsed - captured,
                "clockToleranceSeconds": clock_tolerance,
                "interpretation": "Native callback continuity and decoded sample counts; not proof of speech intelligibility or hardware correctness.",
            }
        except (ValueError, KeyError, TypeError, ZeroDivisionError):
            return {
                "status": "warning",
                "reason": "Missing or invalid native capture health fields",
            }
    settings = folder / "capture-settings.json"
    if (
        settings.exists()
        and json.loads(settings.read_text()).get("backend") == "portaudio-coreaudio"
    ):
        return {
            "status": "warning",
            "reason": "Native capture ended without its final health report; inspect/recover retained audio",
        }
    journal = folder / "segments.csv"
    if not journal.exists():
        return {"status": "unknown", "reason": "No device-timestamp journal available"}
    rows = list(csv.reader(journal.read_text().splitlines()))
    parts = record["parts"]
    if not rows or not parts or len(rows) != len(parts) or any(len(row) < 3 for row in rows):
        return {"status": "warning", "reason": "Capture journal and recovered parts differ"}
    captured = sum(p["duration"] for p in parts)
    elapsed = float(rows[-1][2]) - float(rows[0][1])
    missing = elapsed - captured
    return {
        "status": "warning" if abs(missing) > max(0.05, elapsed * 0.001) else "consistent",
        "deviceElapsedSeconds": elapsed,
        "capturedSeconds": captured,
        "discrepancySeconds": missing,
        "interpretation": "A mismatch indicates missing samples or clock disagreement; never fill it with invented dialogue. Consistent duration alone cannot establish audio quality.",
    }


def packet_gaps(text):
    packets = [
        (int(a), int(b))
        for a, b in re.findall(r"demuxer\+tsfixup ->.*?pkt_pts:(\d+).*?duration:(\d+)", text)
    ]
    gaps = [b[0] - a[0] - a[1] for a, b in zip(packets, packets[1:]) if b[0] - a[0] - a[1] > 100]
    return {"packets": len(packets), "gapCount": len(gaps), "missingSeconds": sum(gaps) / 1e6}


@click.command("audit")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
def audit_command(folder):
    """Check sample duration against device timestamps without opening the microphone."""
    click.echo(json.dumps(audit(folder), indent=2))
