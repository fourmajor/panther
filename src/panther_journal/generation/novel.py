from __future__ import annotations

from panther_journal.contracts import ClassifiedLine, LoreFact, LineType


def generate_novel_recap(lines: list[ClassifiedLine], facts: list[LoreFact]) -> str:
    parts = ["# Novel-Style Session Recap", ""]
    parts.append(
        "The party's search drew them beneath Briarwall's old mill, where every discovery "
        "came from the table record rather than invention."
    )
    parts.append("")

    for line in lines:
        if line.label == LineType.CHARACTER_DIALOGUE:
            parts.append(f"{line.speaker_name}'s words carried the moment: {line.text}")
        elif line.label in {LineType.GAME_CANON, LineType.UNCERTAIN}:
            parts.append(f"{line.text}")

    if facts:
        parts.extend(["", "## Grounded Memory"])
        for fact in facts:
            source = ", ".join(fact.source_line_ids)
            parts.append(f"- {fact.name}: {' '.join(fact.facts)} Source lines: {source}.")

    return "\n\n".join(parts) + "\n"
