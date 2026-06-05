from __future__ import annotations

from panther_journal.contracts import ClassifiedLine, LoreFact, LineType


def generate_screenplay_recap(lines: list[ClassifiedLine], facts: list[LoreFact]) -> str:
    parts = ["# Screenplay-Style Session Recap", "", "INT. OLD MILL - NIGHT", ""]

    for line in lines:
        if line.label == LineType.CHARACTER_DIALOGUE:
            parts.append(f"{line.speaker_name.upper()}\n{line.text}")
        elif line.label == LineType.RULES_CHAT:
            parts.append(f"RULES BEAT: {line.text}")
        else:
            parts.append(f"Action: {line.text}")
        parts.append("")

    if facts:
        parts.append("CONTINUITY NOTES")
        for fact in facts:
            parts.append(f"- {fact.name}: {' '.join(fact.facts)}")

    return "\n".join(parts).rstrip() + "\n"
