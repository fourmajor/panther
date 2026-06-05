from __future__ import annotations

from panther_journal.asr.base import ASRProvider
from panther_journal.contracts import TranscriptLine


class WhisperASRProvider(ASRProvider):
    def transcribe_channel(self, channel: int, audio_uri: str) -> list[TranscriptLine]:
        raise NotImplementedError("Whisper/WhisperX local ASR integration placeholder.")
