from __future__ import annotations

from abc import ABC, abstractmethod

from panther_journal.contracts import PantherConfig, TranscriptLine


class AudioIngestor(ABC):
    @abstractmethod
    def ingest(self, config: PantherConfig) -> list[TranscriptLine]:
        """Return timestamped transcript lines from a configured audio source."""
