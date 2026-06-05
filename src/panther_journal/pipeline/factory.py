from __future__ import annotations

from panther_journal.audio.base import AudioIngestor
from panther_journal.audio.mock import MockAudioIngestor
from panther_journal.llm.base import LLMProvider
from panther_journal.llm.local import LocalLLMProvider
from panther_journal.llm.mock import MockLLMProvider
from panther_journal.llm.openai_compatible import OpenAICompatibleLLMProvider


def audio_ingestor(name: str) -> AudioIngestor:
    if name == "mock":
        return MockAudioIngestor()
    raise ValueError(f"Unsupported audio provider: {name}")


def llm_provider(name: str) -> LLMProvider:
    if name == "mock":
        return MockLLMProvider()
    if name == "openai":
        return OpenAICompatibleLLMProvider()
    if name == "local":
        return LocalLLMProvider()
    raise ValueError(f"Unsupported LLM provider: {name}")
