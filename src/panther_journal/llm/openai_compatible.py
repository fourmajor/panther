from __future__ import annotations

from panther_journal.contracts import ClassifiedLine, LoreFact, TranscriptLine
from panther_journal.llm.base import LLMProvider


class OpenAICompatibleLLMProvider(LLMProvider):
    def classify_line(self, line: TranscriptLine) -> ClassifiedLine:
        raise NotImplementedError("OpenAI-compatible classifier integration placeholder.")

    def extract_lore(self, lines: list[ClassifiedLine]) -> list[LoreFact]:
        raise NotImplementedError("OpenAI-compatible lore extraction integration placeholder.")
