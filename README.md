# Panther

Panther is a private platform for capturing tabletop roleplaying sessions, organizing game assets,
and turning play into compelling media.

Its foundation is a reliable, speaker-attributed record of each session. From that source material,
Panther can produce novel-worthy narrative retellings, TV-episode-style reimaginings, and playful
videos loosely inspired by the game.

Panther keeps the canonical record separate from creative adaptations: transcripts should be
accurate and reviewable, while derivative works may reinterpret events as long as their source and
creative nature remain clear.

## What Panther Supports

- Session recordings and speaker-attributed transcripts
- Portraits, maps, documents, music, video, and other game assets
- Grounded narrative retellings based closely on what happened
- Creative episodic reimaginings of game sessions
- Trailers, jokes, music videos, and other playful derivative media
- Private group collaboration and deliberate publication of selected material

The asset model is intentionally open-ended so that new kinds of source material and media can be
added without redesigning the storage hierarchy.

## Canonical and Creative Material

Panther distinguishes between four broad kinds of material:

- **Canonical sources:** recordings, reviewed transcripts, corrections, maps, documents, and other
  original game material
- **Grounded adaptations:** polished retellings that stay close to the session record
- **Creative reimaginings:** deliberately dramatized works, including TV-episode-style adaptations
- **Playful derivatives:** trailers, jokes, music videos, and media only loosely related to the game

Every derived asset should retain enough provenance to identify its source material and distinguish
recorded fact from creative interpretation.

## Current Status

The initial AWS foundation is operational. It provides private and published asset storage,
short-lived administrative access, and a near-zero-idle-cost baseline managed with AWS CDK. A
password-protected, read-only media explorer is available for browsing and previewing private game
assets at [panther.place](https://panther.place).

`src/panther_journal` is an early prototype of the transcription and narrative-generation pipeline.
It does not define the full scope of Panther. Reliable session capture, production transcription,
speaker attribution, richer group collaboration, and the media-production workflows remain to be
built.

## Scope

Panther initially serves one gaming group and one game. It is not currently intended to be a
general-purpose multi-tenant service. Data still carries a stable game identifier so another game
can be added later without reorganizing storage.

Application source and infrastructure code live in this repository. Game content and application
data live in the dedicated AWS account and must never be committed to GitHub.

## Design Principles

- Private by default; publication is always deliberate
- Accurate, reviewable transcripts before downstream generation
- Clear separation between canonical records and creative works
- Open-ended support for new asset and media types
- Near-zero infrastructure cost while Panther is inactive
- AWS infrastructure defined and deployed through CDK
- Local development and verification without always-on CI infrastructure

## Project Documentation

- [AWS platform architecture](docs/aws-platform-architecture-draft.md)
- [AWS foundation runbook](docs/aws-foundation-runbook.md)
- [Audio capture strategy](docs/adr/0001-audio-capture-strategy.md)
- [Transcription prototype architecture](architecture.md)

## Transcription Prototype

The current Python package contains mock providers and sample data for exercising the early pipeline.
It is useful for development, but it is not yet a production recording or transcription system.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

panther ingest-sample
panther classify-sample
panther generate-transcript
panther extract-lore
panther generate-novel
panther generate-screenplay
```

Sample artifacts are written to `runs/sample-session/` by default and must not contain real game
data intended for shared or durable storage.
