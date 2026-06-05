from __future__ import annotations

from panther_journal.asr.base import ASRProvider
from panther_journal.contracts import TranscriptLine


class OpenAIASRProvider(ASRProvider):
    def transcribe_channel(self, channel: int, audio_uri: str) -> list[TranscriptLine]:
        raise NotImplementedError("OpenAI ASR integration will be added behind this interface.")
