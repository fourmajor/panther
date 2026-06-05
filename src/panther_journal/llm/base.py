from __future__ import annotations

from abc import ABC, abstractmethod

from panther_journal.contracts import ClassifiedLine, LoreFact, TranscriptLine


class LLMProvider(ABC):
    @abstractmethod
    def classify_line(self, line: TranscriptLine) -> ClassifiedLine:
        """Classify one transcript line."""

    @abstractmethod
    def extract_lore(self, lines: list[ClassifiedLine]) -> list[LoreFact]:
        """Extract campaign memory from filtered lines."""
