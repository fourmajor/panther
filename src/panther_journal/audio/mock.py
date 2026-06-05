from __future__ import annotations

import json
from pathlib import Path

from panther_journal.audio.base import AudioIngestor
from panther_journal.contracts import PantherConfig, TranscriptLine


class MockAudioIngestor(AudioIngestor):
    def ingest(self, config: PantherConfig) -> list[TranscriptLine]:
        fixture_path = Path(config.audio["sample_fixture"])
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        speakers = config.speakers_by_channel
        lines: list[TranscriptLine] = []

        for index, event in enumerate(payload["events"], start=1):
            speaker = speakers[int(event["channel"])]
            lines.append(
                TranscriptLine(
                    id=f"line-{index:04d}",
                    session_id=config.campaign.session_id,
                    speaker_id=speaker.id,
                    speaker_name=speaker.display_name,
                    channel=speaker.channel,
                    timestamp_start=float(event["timestamp_start"]),
                    timestamp_end=float(event["timestamp_end"]),
                    text=event["text"],
                    asr_confidence=float(event.get("asr_confidence", 1.0)),
                )
            )
        return lines
