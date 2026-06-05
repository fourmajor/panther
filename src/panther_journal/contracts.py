from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class LineType(StrEnum):
    GAME_CANON = "GAME_CANON"
    RULES_CHAT = "RULES_CHAT"
    CHARACTER_DIALOGUE = "CHARACTER_DIALOGUE"
    TABLE_LOGISTICS = "TABLE_LOGISTICS"
    FOOD_DRINK = "FOOD_DRINK"
    FAMILY_PERSONAL = "FAMILY_PERSONAL"
    JOKE_OOC = "JOKE_OOC"
    UNCERTAIN = "UNCERTAIN"


class Confidence(StrEnum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    UNCERTAIN = "uncertain"


class Speaker(BaseModel):
    id: str
    display_name: str
    role: str
    channel: int
    character_name: str | None = None


class CampaignConfig(BaseModel):
    name: str
    session_id: str
    session_title: str


class PantherConfig(BaseModel):
    campaign: CampaignConfig
    speakers: list[Speaker]
    audio: dict[str, Any]
    models: dict[str, Any]
    filtering: dict[str, Any]
    output: dict[str, Any] = Field(default_factory=dict)

    @property
    def speakers_by_channel(self) -> dict[int, Speaker]:
        return {speaker.channel: speaker for speaker in self.speakers}


class TranscriptLine(BaseModel):
    id: str
    session_id: str
    speaker_id: str
    speaker_name: str
    channel: int
    timestamp_start: float
    timestamp_end: float
    text: str
    asr_confidence: float = 1.0


class ClassifiedLine(TranscriptLine):
    label: LineType
    classifier_confidence: float
    rationale: str


class LoreFact(BaseModel):
    type: str
    name: str
    session_id: str
    timestamp_start: float
    timestamp_end: float
    facts: list[str]
    status: str
    confidence: Confidence
    source_line_ids: list[str]


class ArtifactBundle(BaseModel):
    session_id: str
    artifact_type: str
    path: Path
