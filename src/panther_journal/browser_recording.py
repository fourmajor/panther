"""Version-1 browser PCM capture; separate from the native FLAC Recording contract."""

import json
from typing import Literal

import click
from pydantic import Field, model_validator

from panther_journal import recording as audio


class BrowserPart(audio.Part):
    file: str = Field(pattern=r"^part-[0-9]{4}\.wav$")
    duration: float = Field(gt=0, le=15.01)
    sampleRate: Literal[32000] = 32000
    channels: Literal[1] = 1
    bitsPerSample: Literal[16] = 16


class BrowserRecording(audio.Recording):
    entityType: Literal["BrowserRecording"] = "BrowserRecording"
    sessionName: str = Field(min_length=1, max_length=120)
    sourceFormat: Literal["wav"] = "wav"
    parts: list[BrowserPart] = Field(min_length=1, max_length=1000)
    captureWarnings: list[str] = Field(max_length=100)

    @model_validator(mode="after")
    def timeline(self):
        offset = 0.0
        for i, part in enumerate(self.parts):
            if part.file != f"part-{i:04d}.wav" or abs(part.start - offset) > 0.02:
                raise ValueError("Browser recording parts must be ordered and contiguous")
            offset += part.duration
        return self


def verified(folder):
    doc = json.loads((folder / "recording.json").read_text())
    if doc.get("entityType") != "BrowserRecording":
        return audio.verified(folder)
    record = BrowserRecording.model_validate(doc)
    for part in record.parts:
        file = folder / part.file
        if (
            file.is_symlink()
            or not file.is_file()
            or file.stat().st_size != part.size
            or audio.digest(file) != part.sha256
        ):
            raise click.ClickException("Browser source changed or is missing; refusing overwrite.")
    return record
