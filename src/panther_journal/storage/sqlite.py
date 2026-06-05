from __future__ import annotations

import sqlite3
from pathlib import Path

from panther_journal.contracts import ClassifiedLine, LoreFact, PantherConfig, TranscriptLine


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  campaign_name TEXT NOT NULL,
  title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS speakers (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL,
  character_name TEXT,
  channel INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS transcript_lines (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  speaker_id TEXT NOT NULL,
  speaker_name TEXT NOT NULL,
  channel INTEGER NOT NULL,
  timestamp_start REAL NOT NULL,
  timestamp_end REAL NOT NULL,
  text TEXT NOT NULL,
  asr_confidence REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS filtered_lines (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  speaker_id TEXT NOT NULL,
  speaker_name TEXT NOT NULL,
  channel INTEGER NOT NULL,
  timestamp_start REAL NOT NULL,
  timestamp_end REAL NOT NULL,
  text TEXT NOT NULL,
  label TEXT NOT NULL,
  classifier_confidence REAL NOT NULL,
  rationale TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  type TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  confidence TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  name TEXT NOT NULL,
  timestamp_start REAL NOT NULL,
  timestamp_end REAL NOT NULL,
  source_line_ids TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lore_facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  type TEXT NOT NULL,
  name TEXT NOT NULL,
  timestamp_start REAL NOT NULL,
  timestamp_end REAL NOT NULL,
  facts_json TEXT NOT NULL,
  status TEXT NOT NULL,
  confidence TEXT NOT NULL,
  source_line_ids_json TEXT NOT NULL
);
"""


class SQLiteStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.executescript(SCHEMA)
        return connection

    def upsert_session(self, config: PantherConfig) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO sessions (id, campaign_name, title)
                VALUES (?, ?, ?)
                """,
                (config.campaign.session_id, config.campaign.name, config.campaign.session_title),
            )
            connection.executemany(
                """
                INSERT OR REPLACE INTO speakers
                (id, session_id, display_name, role, character_name, channel)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        speaker.id,
                        config.campaign.session_id,
                        speaker.display_name,
                        speaker.role,
                        speaker.character_name,
                        speaker.channel,
                    )
                    for speaker in config.speakers
                ],
            )

    def write_transcript_lines(self, lines: list[TranscriptLine]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO transcript_lines
                (id, session_id, speaker_id, speaker_name, channel, timestamp_start,
                 timestamp_end, text, asr_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        line.id,
                        line.session_id,
                        line.speaker_id,
                        line.speaker_name,
                        line.channel,
                        line.timestamp_start,
                        line.timestamp_end,
                        line.text,
                        line.asr_confidence,
                    )
                    for line in lines
                ],
            )

    def write_filtered_lines(self, lines: list[ClassifiedLine]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO filtered_lines
                (id, session_id, speaker_id, speaker_name, channel, timestamp_start,
                 timestamp_end, text, label, classifier_confidence, rationale)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        line.id,
                        line.session_id,
                        line.speaker_id,
                        line.speaker_name,
                        line.channel,
                        line.timestamp_start,
                        line.timestamp_end,
                        line.text,
                        line.label.value,
                        line.classifier_confidence,
                        line.rationale,
                    )
                    for line in lines
                ],
            )

    def write_lore_facts(self, facts: list[LoreFact]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO lore_facts
                (session_id, type, name, timestamp_start, timestamp_end, facts_json,
                 status, confidence, source_line_ids_json)
                VALUES (?, ?, ?, ?, ?, json(?), ?, ?, json(?))
                """,
                [
                    (
                        fact.session_id,
                        fact.type,
                        fact.name,
                        fact.timestamp_start,
                        fact.timestamp_end,
                        _json_dump(fact.facts),
                        fact.status,
                        fact.confidence.value,
                        _json_dump(fact.source_line_ids),
                    )
                    for fact in facts
                ],
            )
            connection.executemany(
                """
                INSERT INTO entities (session_id, type, name, status, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (fact.session_id, fact.type, fact.name, fact.status, fact.confidence.value)
                    for fact in facts
                    if fact.type != "event"
                ],
            )
            connection.executemany(
                """
                INSERT INTO events
                (session_id, name, timestamp_start, timestamp_end, source_line_ids)
                VALUES (?, ?, ?, ?, json(?))
                """,
                [
                    (
                        fact.session_id,
                        fact.name,
                        fact.timestamp_start,
                        fact.timestamp_end,
                        _json_dump(fact.source_line_ids),
                    )
                    for fact in facts
                    if fact.type == "event"
                ],
            )


def _json_dump(value: object) -> str:
    import json

    return json.dumps(value, separators=(",", ":"))
