from __future__ import annotations

from abc import ABC, abstractmethod

from panther_journal.contracts import TranscriptLine


class ASRProvider(ABC):
    @abstractmethod
    def transcribe_channel(self, channel: int, audio_uri: str) -> list[TranscriptLine]:
        """Transcribe one known-speaker audio channel."""
