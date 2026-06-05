from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, TypeVar

from pydantic import BaseModel, TypeAdapter

T = TypeVar("T", bound=BaseModel)


def ensure_run_dir(run_dir: str | Path) -> Path:
    path = Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_models(path: str | Path, models: Iterable[BaseModel]) -> None:
    payload = [model.model_dump(mode="json") for model in models]
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_models(path: str | Path, model_type: type[T]) -> list[T]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return TypeAdapter(list[model_type]).validate_python(payload)


def write_json(path: str | Path, payload: object) -> None:
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_json(path: str | Path) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))
