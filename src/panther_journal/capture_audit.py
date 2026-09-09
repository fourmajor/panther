"""Compare captured sample counts with the device-timestamp segment journal; never repair audio."""

import csv
import json
import re
from pathlib import Path

import click


def audit(folder):
    record = json.loads((folder / "recording.json").read_text())
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
