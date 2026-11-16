"""Editorial inference is a file handoff to Grok Bot. This process never calls an LLM.

For every editorial call the worker writes a request folder with ``prompt.md``, ``schema.json``
and ``request.json``. A Grok Bot routine writes ``answer.json`` (a JSON object that satisfies
``schema.json``) with ``panther editorial agent-answer``. The worker keeps the stage lease alive
while it waits, validates the answer, and continues the deterministic pipeline. There is no
Claude, Codex, or paid API backend and no fallback to one.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import time

import jsonschema

from panther_journal import model_workflow as local

BACKEND = "grok-bot"
MODEL = "grok-bot"
# Conservative byte budget so a prompt stays readable in one agent turn.
BYTE_LIMITS = {BACKEND: 540_000}
ANSWER_LIMIT = 2 * 1024**2
DEFAULT_WAIT_SECONDS = 6 * 3600
POLL_SECONDS = 15
REQUESTS_ENV = "PANTHER_AGENT_REQUESTS"


def _failure(message):
    from panther_journal.editorial import DeterministicFailure

    raise DeterministicFailure(message)


def reject_fast(model, tier=None):
    if isinstance(tier, str) and tier.casefold() in {"priority", "fast"}:
        _failure("Inference selected a priority or Fast tier. The stage was not accepted.")


def default_model(_backend=None, _effort=None):
    return MODEL


def requests_root(folder=None):
    configured = os.environ.get(REQUESTS_ENV, "").strip()
    if configured:
        return Path(configured)
    if folder is None:
        raise ValueError(f"{REQUESTS_ENV} is not set")
    return Path(folder) / "agent-requests"


def request_id(stage, prompt, schema_text):
    digest = hashlib.sha256()
    for part in (stage, prompt, schema_text):
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()[:24]


def validate_answer(path, schema):
    """Return the answer object or raise ValueError with a message the agent can act on."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("answer.json must be a regular file")
    if path.stat().st_size > ANSWER_LIMIT:
        raise ValueError(f"answer.json is larger than {ANSWER_LIMIT} bytes")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"answer.json is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("answer.json must be one JSON object")
    try:
        jsonschema.validate(value, schema)
    except jsonschema.ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path) or "(top level)"
        raise ValueError(f"answer.json does not match schema.json at {where}: {exc.message}") from exc
    return value


def _write(path, text):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _record(directory):
    return json.loads((directory / "request.json").read_text())


def _mark(directory, **changes):
    record = _record(directory)
    record.update(changes)
    _write(directory / "request.json", json.dumps(record, indent=2))


def prepare(stage, effort, prompt, schema, folder, *, job_id=None, image=None):
    schema_text = Path(schema).read_text()
    rid = request_id(stage, prompt, schema_text)
    directory = requests_root(folder) / rid
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not (directory / "request.json").is_file():
        _write(directory / "prompt.md", prompt)
        _write(directory / "schema.json", schema_text)
        copied = None
        if image is not None:
            copied = "image" + Path(image).suffix
            shutil.copyfile(image, directory / copied)
        record = {
            "requestId": rid,
            "stage": stage,
            "jobId": job_id,
            "reasoningEffort": effort,
            "status": "pending",
            "createdAt": int(time.time()),
            "prompt": "prompt.md",
            "schema": "schema.json",
            "image": copied,
            "answer": "answer.json",
            "lastError": None,
        }
        _write(directory / "request.json", json.dumps(record, indent=2))
    _write(Path(folder) / "agent-request.json", json.dumps({"requestId": rid, "dir": str(directory)}))
    return directory


def complete(stage, effort, prompt, schema, result, folder, heartbeat, image=None, *,
             job_id=None, wait_seconds=None, clock=time.monotonic, sleep=time.sleep):
    """Wait for Grok Bot's answer to this exact prompt, then write it to ``result``."""
    directory = prepare(stage, effort, prompt, schema, folder, job_id=job_id, image=image)
    contract = json.loads((directory / "schema.json").read_text())
    if wait_seconds is None:
        wait_seconds = int(os.environ.get("PANTHER_AGENT_WAIT_SECONDS", DEFAULT_WAIT_SECONDS))
    deadline = clock() + wait_seconds
    answer = directory / "answer.json"
    while True:
        if answer.exists():
            try:
                value = validate_answer(answer, contract)
            except ValueError as exc:
                rejected = len(list(directory.glob("rejected-*.json"))) + 1
                os.replace(answer, directory / f"rejected-{rejected}.json")
                _mark(directory, status="pending", lastError=str(exc)[:2000])
            else:
                _write(Path(result), json.dumps(value))
                if _record(directory).get("status") != "answered":
                    _mark(directory, status="answered", answeredAt=int(time.time()), lastError=None)
                return {"observedModel": MODEL, "serviceTier": "default", "usage": {"costUsd": 0,
                        "costStatus": "no-api"}, "requestId": directory.name}
        if clock() >= deadline:
            _mark(directory, status="pending")
            raise local.Deferred(
                f"No Grok Bot answer for request {directory.name} within {wait_seconds}s. "
                "The stage is deferred; there is no model fallback."
            )
        heartbeat()
        sleep(POLL_SECONDS)


def pending(root):
    """Unanswered requests, oldest first, with absolute paths for the routine."""
    found = []
    base = Path(root)
    if not base.is_dir():
        return found
    for directory in sorted(p for p in base.iterdir() if p.is_dir()):
        try:
            record = _record(directory)
        except (OSError, ValueError):
            continue
        if record.get("status") == "answered" or (directory / "answer.json").exists():
            continue
        found.append({
            **record,
            "dir": str(directory),
            "prompt": str(directory / record["prompt"]),
            "schema": str(directory / record["schema"]),
            "answer": str(directory / record["answer"]),
            "image": str(directory / record["image"]) if record.get("image") else None,
        })
    return sorted(found, key=lambda item: item.get("createdAt") or 0)


def submit_answer(root, rid, source):
    """Validate a written answer against its request schema and install it atomically."""
    directory = Path(root) / rid
    if not (directory / "request.json").is_file() or "/" in rid or rid.startswith("."):
        raise ValueError(f"Unknown request {rid}")
    if _record(directory).get("status") == "answered":
        raise ValueError(f"Request {rid} is already answered")
    value = validate_answer(source, json.loads((directory / "schema.json").read_text()))
    _write(directory / "answer.json", json.dumps(value, ensure_ascii=False))
    return directory / "answer.json"
