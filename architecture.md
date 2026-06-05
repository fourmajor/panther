# Architecture

Panther is built around known-speaker channel mapping. A 5-person in-person session should ideally produce five isolated channels or five synchronized mono files. Remote participants are additional isolated digital channels.

## Core Principles

- Prefer one audio channel per speaker.
- Do not rely on diarization as the primary attribution method.
- Keep uncertain story content instead of deleting it.
- Store every pipeline stage as JSON for review and replay.
- Ground generated prose in transcript line IDs and campaign memory facts.
- Keep cloud and local provider integrations behind small interfaces.

## Package Layout

```text
src/panther_journal/
  audio/        ingestion abstractions and mock input
  asr/          ASR provider interface and placeholders
  llm/          classifier/extractor/generator provider interface
  pipeline/     orchestration and artifact contracts
  storage/      SQLite schema and repository helpers
  generation/   grounded recap renderers
  cli.py        command entrypoint
```

## Data Flow

1. `ingest-sample` reads fixture audio events and produces `raw_transcript.json`.
2. `classify-sample` labels lines using the configured classifier provider and writes `classified_lines.json`.
3. `generate-transcript` applies filtering policy and writes `game_transcript.md` and `filtered_lines.json`.
4. `extract-lore` extracts structured campaign memory into `campaign_memory.json` and SQLite.
5. `generate-novel` renders a grounded novel-style recap.
6. `generate-screenplay` renders a grounded screenplay-style recap.

## Provider Strategy

Audio ingestion:

- Current: mock fixture input.
- Planned: CoreAudio, ffmpeg capture, multichannel WAV, synchronized mono files.

ASR:

- Current: mock lines from fixture.
- Planned: OpenAI-compatible transcription, local Whisper, WhisperX alignment, diarization fallback.

LLM:

- Current: deterministic local mock for reproducible sample output.
- Planned: OpenAI-compatible chat/completions provider and local model provider.

## Storage

SQLite is the initial source of durable truth. JSON artifacts remain useful for repeatable tests, review, prompt regression, and export.

Tables:

- `sessions`
- `speakers`
- `transcript_lines`
- `filtered_lines`
- `entities`
- `events`
- `lore_facts`

## Grounded Generation

Generators receive only filtered transcript lines and campaign memory facts. Output sections cite source line IDs internally in metadata where possible. The generated prose may improve pacing and sensory readability, but it must not create critical facts absent from source data.
