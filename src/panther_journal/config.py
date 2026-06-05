from __future__ import annotations

from pathlib import Path

import yaml

from panther_journal.contracts import PantherConfig


def load_config(path: str | Path) -> PantherConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return PantherConfig.model_validate(raw)
