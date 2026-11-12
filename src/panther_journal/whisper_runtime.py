"""Shared whisper.cpp settings for live preview and session finalization.

Weights stay on the machine that runs recognition. This module never downloads during a test
import; the session installer calls ensure_model explicitly.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import sys
import tempfile
import urllib.request

MODEL_NAME = "ggml-large-v3-turbo.bin"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin"
DEFAULT_MODEL = Path.home() / ".cache/whisper.cpp" / MODEL_NAME
BEAM_SIZE = 5
BEST_OF = 5
MAX_CONTEXT = 224
PROMPT_CHARS = 800
LOGPROB_FLOOR = -1.0
# A stub or a partial download must not be treated as the turbo weights.
MINIMUM_BYTES = 100_000_000


def threads():
    """More than the old two-thread cap, still bounded on a laptop."""
    count = os.cpu_count() or 4
    return max(4, min(8, count))


def gpu_default():
    """Metal is available on the Mac worker. Other hosts stay on CPU unless asked."""
    return sys.platform == "darwin"


def command(executable, model, wav, output, *, prompt=None, use_gpu=False):
    args = [
        executable,
        "-m",
        str(model),
        "-f",
        str(wav),
        "-l",
        "en",
        "-t",
        str(threads()),
        "-p",
        "1",
        "-bs",
        str(BEAM_SIZE),
        "-bo",
        str(BEST_OF),
        "-nf",
        "-mc",
        str(MAX_CONTEXT),
        "-ojf",
        "-of",
        str(output),
    ]
    if not use_gpu:
        args[args.index("-bs"): args.index("-bs")] = ["-ng"]
    text = (prompt or "").strip()
    if text:
        args.extend(["--prompt", text[:PROMPT_CHARS]])
    return args


def names_prompt(names, limit=PROMPT_CHARS):
    cleaned = []
    for name in names:
        if not isinstance(name, str):
            continue
        text = " ".join(name.split())
        if text and text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        return ""
    return ("Names: " + ", ".join(cleaned))[:limit]


def _add_name(names, value):
    if isinstance(value, str) and value.strip():
        names.append(value.strip())


def catalog_names(catalog, players=()):
    """Spoken names only. Player ids are not names, and a missing catalog is not an error."""
    names = []
    if isinstance(catalog, dict):
        for key in ("characters", "locations", "places", "npcs", "items", "players"):
            for item in catalog.get(key) or []:
                if isinstance(item, str):
                    _add_name(names, item)
                elif isinstance(item, dict):
                    _add_name(names, item.get("name"))
                    _add_name(names, item.get("title"))
                    aliases = item.get("aliases")
                    if isinstance(aliases, str):
                        _add_name(names, aliases)
                    elif isinstance(aliases, list):
                        for alias in aliases:
                            _add_name(names, alias)
    for player in players or []:
        if isinstance(player, dict):
            _add_name(names, player.get("name") or player.get("displayName"))
        elif isinstance(player, str):
            _add_name(names, player)
    return names_prompt(names)


def repeated(text):
    words = (text or "").split()
    if len(words) < 12:
        return False
    for size in (4, 5):
        counts = {}
        for index in range(len(words) - size + 1):
            gram = " ".join(words[index: index + size]).casefold()
            counts[gram] = counts.get(gram, 0) + 1
            if counts[gram] >= 3:
                return True
    return False


def average_logprob(raw):
    if not isinstance(raw, dict):
        return None
    values = []
    for item in raw.get("transcription") or []:
        if not isinstance(item, dict):
            continue
        score = item.get("avg_logprob")
        if isinstance(score, (int, float)) and math.isfinite(score):
            values.append(float(score))
        for token in item.get("tokens") or []:
            if not isinstance(token, dict):
                continue
            probability = token.get("p")
            if isinstance(probability, (int, float)) and 0 < probability <= 1:
                values.append(math.log(probability))
    if not values:
        return None
    return sum(values) / len(values)


def reset_context(text, avg_logprob):
    if avg_logprob is not None and avg_logprob < LOGPROB_FLOOR:
        return True
    return repeated(text)


def utterance_text(lines):
    parts = []
    for line in lines or []:
        if not isinstance(line, dict) or line.get("kind") == "preview-gap":
            return ""
        text = line.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return " ".join(parts)


def carry(base, lines, raw=None):
    """Keep the name prompt plus the latest chunk, or the name prompt alone after a loop."""
    text = utterance_text(lines)
    if not text or reset_context(text, average_logprob(raw)):
        return base, True
    tail = " ".join(text.split()[-50:])
    merged = base if not tail else f"{base}\n{tail}"
    return merged[:PROMPT_CHARS], False


def ensure_model(directory=None, *, opener=None, minimum_bytes=MINIMUM_BYTES):
    """Cache the turbo weights. An existing large file is reused and never overwritten."""
    directory = Path(directory) if directory else DEFAULT_MODEL.parent
    target = directory / MODEL_NAME
    if target.is_file() and not target.is_symlink() and target.stat().st_size >= minimum_bytes:
        return target
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = Path(tempfile.mkstemp(prefix=".whisper-", suffix=".partial", dir=directory)[1])
    os.chmod(temporary, 0o600)
    try:
        source = opener or urllib.request.urlopen
        with source(MODEL_URL, timeout=120) as response, temporary.open("wb") as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
        if temporary.stat().st_size < minimum_bytes:
            raise OSError("Whisper model download was incomplete")
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target
