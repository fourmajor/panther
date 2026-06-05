from __future__ import annotations

from panther_journal.contracts import ClassifiedLine, LineType, PantherConfig


def filter_game_lines(lines: list[ClassifiedLine], config: PantherConfig) -> list[ClassifiedLine]:
    include = {LineType(label) for label in config.filtering["include_labels"]}
    exclude = {LineType(label) for label in config.filtering.get("exclude_labels", [])}
    keep_uncertain = bool(config.filtering.get("keep_uncertain", True))

    filtered: list[ClassifiedLine] = []
    for line in lines:
        if line.label == LineType.UNCERTAIN and keep_uncertain:
            filtered.append(line)
        elif line.label in include and line.label not in exclude:
            filtered.append(line)
    return filtered
