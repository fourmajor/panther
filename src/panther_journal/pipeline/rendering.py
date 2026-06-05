from __future__ import annotations

from panther_journal.contracts import ClassifiedLine


def render_transcript_markdown(lines: list[ClassifiedLine]) -> str:
    parts = ["# Filtered Game Transcript", ""]
    for line in lines:
        start = _format_ts(line.timestamp_start)
        end = _format_ts(line.timestamp_end)
        parts.append(f"- [{start}-{end}] **{line.speaker_name}** ({line.label}): {line.text}")
    return "\n".join(parts) + "\n"


def _format_ts(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"
