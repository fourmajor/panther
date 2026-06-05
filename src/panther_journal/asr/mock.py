from __future__ import annotations

from panther_journal.asr.base import ASRProvider
from panther_journal.contracts import TranscriptLine


class MockASRProvider(ASRProvider):
    def transcribe_channel(self, channel: int, audio_uri: str) -> list[TranscriptLine]:
        raise NotImplementedError("Mock ASR is represented by fixture transcript events.")
