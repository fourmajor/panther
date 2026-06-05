from __future__ import annotations

from panther_journal.contracts import ClassifiedLine, LoreFact, TranscriptLine
from panther_journal.llm.base import LLMProvider


class LocalLLMProvider(LLMProvider):
    def classify_line(self, line: TranscriptLine) -> ClassifiedLine:
        raise NotImplementedError("Local model classifier integration placeholder.")

    def extract_lore(self, lines: list[ClassifiedLine]) -> list[LoreFact]:
        raise NotImplementedError("Local model lore extraction integration placeholder.")
