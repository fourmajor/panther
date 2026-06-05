# Panther

```text
                         .-''''-.
                    _.-'  .-..-.  `-._
                 .-'     /  ||  \     `-.
        _..--''''       /   ||   \       ``''--.._
     .-'               /_.-^^^^-._\               `-.
   .'              _.-'  _..---.._  `-._              `.
  /            _.-'   .-'  _____  `-.   `-._            \
 /        _.-'      .'   .'     `.   `.      `-._        \
|      .-'        .'    /  .- -.  \    `.        `-.      |
|    .'          /     |  /  _  \  |     \          `.    |
|   /           |      | |  ( )  | |      |           \   |
|  |            |      |  \  -  /  |      |            |  |
|  |             \      \  `---'  /      /             |  |
|   \             `._    `-.___.-'    _.'             /   |
 \   `._              `--._____.--'              _.'   /
  `.    `-._                                      _.-'    .'
    `-._    `--..__                      __..--'    _.-'
        `--.._       ``----......----''       _..--'
              ``--..__                __..--''
                      ``------------''
          /\_/\        P A N T H E R        /\_/\
     ____/ o o \____  session audio to lore  / o o \____
          \_^_/                            \_^_/
```

Panther is a TTRPG session journal automation system for turning multi-person tabletop audio into speaker-attributed transcripts, grounded recaps, and structured campaign memory.

The architecture assumes one known audio channel per speaker. Diarization is a fallback, not the main attribution strategy.

## What It Produces

- Cleaned, speaker-attributed raw game transcript
- Novel-style session recap
- Screenplay-style session recap
- Structured campaign memory for continuity
- JSON artifacts for every intermediate stage
- SQLite storage for sessions, speakers, transcript lines, filtered lines, entities, events, and lore facts

## Quick Start

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

Artifacts are written to `runs/sample-session/` by default.

## CLI

```bash
panther ingest-sample --config config/example.yaml --out runs/sample-session
panther classify-sample --run-dir runs/sample-session
panther generate-transcript --run-dir runs/sample-session
panther extract-lore --run-dir runs/sample-session
panther generate-novel --run-dir runs/sample-session
panther generate-screenplay --run-dir runs/sample-session
```

## Architecture

Pipeline:

```text
audio input
-> per-channel VAD
-> ASR
-> timestamped speaker transcript
-> LLM classifier for line type
-> filtered game transcript
-> lore/entity/event extractor
-> campaign memory store
-> novel recap generator
-> screenplay generator
```

Read [architecture.md](architecture.md) and [ADR 0001](docs/adr/0001-audio-capture-strategy.md) before changing capture assumptions.

## Current Providers

- Audio ingestion: mock file input
- ASR: mock provider, OpenAI placeholder, Whisper/WhisperX placeholder
- LLM: deterministic mock, OpenAI-compatible placeholder, local placeholder
- Storage: SQLite

## Grounding Rule

Generated prose must not invent critical facts. Novel and screenplay generation are grounded in transcript lines and campaign memory. Embellishment is allowed only for sensory detail, pacing, and readability.

## Next Engineering Milestones

- Add multichannel WAV ingestion with channel-to-speaker mapping.
- Add CoreAudio capture on macOS and ffmpeg capture on Linux.
- Add streaming VAD with chunked ASR.
- Implement OpenAI-compatible ASR and LLM providers.
- Add WhisperX local transcription and optional diarization fallback.
- Add confidence scoring and human review UI for uncertain lines.
- Add remote participant capture profiles using isolated virtual audio devices.
- Add regression tests for prompt outputs and JSON schema validation.

## GitHub

The intended private repository name is `panther`.
