from __future__ import annotations

from pathlib import Path

import click

from panther_journal.artifacts import ensure_run_dir, read_models, write_models
from panther_journal.config import load_config
from panther_journal.contracts import ClassifiedLine, LoreFact, TranscriptLine
from panther_journal.generation.novel import generate_novel_recap
from panther_journal.generation.screenplay import generate_screenplay_recap
from panther_journal.pipeline.factory import audio_ingestor, llm_provider
from panther_journal.pipeline.filtering import filter_game_lines
from panther_journal.pipeline.rendering import render_transcript_markdown
from panther_journal.storage.sqlite import SQLiteStore


DEFAULT_CONFIG = "config/example.yaml"
DEFAULT_RUN_DIR = "runs/sample-session"


@click.group()
def main() -> None:
    """Panther TTRPG session journal automation."""


@main.command("ingest-sample")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
@click.option("--out", "run_dir", default=DEFAULT_RUN_DIR, show_default=True)
def ingest_sample(config_path: str, run_dir: str) -> None:
    config = load_config(config_path)
    run_path = ensure_run_dir(run_dir)
    provider = audio_ingestor(config.audio["input_provider"])
    lines = provider.ingest(config)
    write_models(run_path / "raw_transcript.json", lines)

    store = SQLiteStore(run_path / "panther.sqlite")
    store.upsert_session(config)
    store.write_transcript_lines(lines)
    click.echo(f"Wrote {len(lines)} raw transcript lines to {run_path}")


@main.command("classify-sample")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
@click.option("--run-dir", default=DEFAULT_RUN_DIR, show_default=True)
def classify_sample(config_path: str, run_dir: str) -> None:
    config = load_config(config_path)
    run_path = ensure_run_dir(run_dir)
    lines = read_models(run_path / "raw_transcript.json", TranscriptLine)
    provider = llm_provider(config.models["llm_provider"])
    classified = [provider.classify_line(line) for line in lines]
    write_models(run_path / "classified_lines.json", classified)
    click.echo(f"Wrote {len(classified)} classified lines to {run_path}")


@main.command("generate-transcript")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
@click.option("--run-dir", default=DEFAULT_RUN_DIR, show_default=True)
def generate_transcript(config_path: str, run_dir: str) -> None:
    config = load_config(config_path)
    run_path = ensure_run_dir(run_dir)
    classified = read_models(run_path / "classified_lines.json", ClassifiedLine)
    filtered = filter_game_lines(classified, config)
    write_models(run_path / "filtered_lines.json", filtered)
    (run_path / "game_transcript.md").write_text(render_transcript_markdown(filtered), encoding="utf-8")

    SQLiteStore(run_path / "panther.sqlite").write_filtered_lines(filtered)
    click.echo(f"Wrote {len(filtered)} filtered game lines to {run_path}")


@main.command("extract-lore")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
@click.option("--run-dir", default=DEFAULT_RUN_DIR, show_default=True)
def extract_lore(config_path: str, run_dir: str) -> None:
    config = load_config(config_path)
    run_path = ensure_run_dir(run_dir)
    lines = read_models(run_path / "filtered_lines.json", ClassifiedLine)
    provider = llm_provider(config.models["llm_provider"])
    facts = provider.extract_lore(lines)
    write_models(run_path / "campaign_memory.json", facts)
    SQLiteStore(run_path / "panther.sqlite").write_lore_facts(facts)
    click.echo(f"Wrote {len(facts)} lore facts to {run_path}")


@main.command("generate-novel")
@click.option("--run-dir", default=DEFAULT_RUN_DIR, show_default=True)
def generate_novel(run_dir: str) -> None:
    run_path = Path(run_dir)
    lines = read_models(run_path / "filtered_lines.json", ClassifiedLine)
    facts = read_models(run_path / "campaign_memory.json", LoreFact)
    output = generate_novel_recap(lines, facts)
    (run_path / "novel_recap.md").write_text(output, encoding="utf-8")
    click.echo(f"Wrote novel recap to {run_path / 'novel_recap.md'}")


@main.command("generate-screenplay")
@click.option("--run-dir", default=DEFAULT_RUN_DIR, show_default=True)
def generate_screenplay(run_dir: str) -> None:
    run_path = Path(run_dir)
    lines = read_models(run_path / "filtered_lines.json", ClassifiedLine)
    facts = read_models(run_path / "campaign_memory.json", LoreFact)
    output = generate_screenplay_recap(lines, facts)
    (run_path / "screenplay_recap.md").write_text(output, encoding="utf-8")
    click.echo(f"Wrote screenplay recap to {run_path / 'screenplay_recap.md'}")


if __name__ == "__main__":
    main()
