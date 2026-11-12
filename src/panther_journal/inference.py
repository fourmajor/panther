"""Pluggable editorial inference. Claude Code is the default. Codex stays optional.

No backend may select a Fast mode or a priority tier. Keys are read at call time and are not
written to invocation records, logs, or exceptions.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

from panther_journal import model_workflow as local


def _failure(message):
    from panther_journal.editorial import DeterministicFailure

    raise DeterministicFailure(message)

# Conservative byte budgets so a stage stays inside the backend context window.
BYTE_LIMITS = {"claude": 540_000, "grok": 600_000, "codex": 1_000_000}
CLAUDE_HIGH = "claude-opus-4-6"
CLAUDE_MEDIUM = "claude-sonnet-4-6"
GROK_MODEL = "grok-4.7"
GROK_URL = "https://api.x.ai/v1/chat/completions"
KEY_SERVICE = "panther-xai"
KEY_ACCOUNT = "api-key"
# These switch Claude Code off the subscription login and onto API billing.
API_OVERRIDE_NAMES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


def reject_fast(model, tier=None):
    if isinstance(tier, str) and tier.casefold() in {"priority", "fast"}:
        _failure("Inference selected a priority or Fast tier. The stage was not accepted.")
    if not isinstance(model, str):
        return
    folded = model.casefold()
    if (
        folded in {"fast", "priority"}
        or folded.endswith("-fast")
        or folded.startswith("fast-")
        or "-fast-" in folded
    ):
        _failure("Inference selected a Fast model. The stage was not accepted.")


def default_model(backend, effort):
    if backend == "claude":
        return CLAUDE_HIGH if effort in {"high", "xhigh"} else CLAUDE_MEDIUM
    if backend == "grok":
        return GROK_MODEL
    return None


def xai_key():
    key = os.environ.get("XAI_API_KEY", "").strip()
    if key:
        return key
    try:
        import keyring
        from keyring.errors import KeyringError
    except ImportError:
        return ""
    try:
        stored = keyring.get_password(KEY_SERVICE, KEY_ACCOUNT)
    except KeyringError:
        return ""
    return stored.strip() if isinstance(stored, str) else ""


def _usage(payload):
    usage = {"inputTokens": None, "outputTokens": None, "cacheReadTokens": None, "costUsd": None, "costStatus": "unknown"}
    if not isinstance(payload, dict):
        return usage
    source = payload.get("usage") if isinstance(payload.get("usage"), dict) else payload
    mapping = (
        ("inputTokens", ("input_tokens", "prompt_tokens", "inputTokens")),
        ("outputTokens", ("output_tokens", "completion_tokens", "outputTokens")),
        ("cacheReadTokens", ("cache_read_input_tokens", "cached_tokens", "cached_input_tokens", "cacheReadTokens")),
    )
    for field, names in mapping:
        for name in names:
            value = source.get(name)
            if isinstance(value, int) and not isinstance(value, bool):
                usage[field] = value
                break
        details = source.get("prompt_tokens_details") or source.get("input_tokens_details")
        if usage[field] is None and isinstance(details, dict):
            for name in mapping[2][1] if field == "cacheReadTokens" else ():
                value = details.get(name)
                if isinstance(value, int) and not isinstance(value, bool):
                    usage[field] = value
    cost = source.get("cost") or source.get("cost_usd") or source.get("costUsd")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        usage["costUsd"] = cost
        usage["costStatus"] = "reported"
    return usage


def _model_arguments(model, effort):
    arguments = ["-c", f'model_reasoning_effort="{effort}"']
    if model:
        arguments = ["-m", model, *arguments]
    return arguments


def codex_command(model, effort, schema, result, folder, image):
    command = [
        *local.codex_base(),
        "exec",
        *_model_arguments(model, effort),
        "--ignore-user-config",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--disable",
        "shell_tool",
        "--disable",
        "unified_exec",
        "--disable",
        "apps",
        "--disable",
        "multi_agent",
        "--disable",
        "image_generation",
        "-c",
        'web_search="disabled"',
        "--json",
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(result),
        "--cd",
        str(folder),
    ]
    if image is not None:
        command.extend(["--image", str(image)])
    command.append("-")
    return command


def subscription_environment():
    """The headless CLI reads the Mac subscription login. An API key must not override it."""
    env = local.clean_environment()
    for name in API_OVERRIDE_NAMES:
        env.pop(name, None)
    return env


def claude_executable():
    """Absolute CLI. Launchd records it in PANTHER_CLAUDE because it has no shell PATH."""
    override = os.environ.get("PANTHER_CLAUDE", "").strip()
    if override:
        if not os.path.isabs(override) or not os.access(override, os.X_OK):
            _failure("PANTHER_CLAUDE must be the absolute Claude Code executable on the LaunchAgent PATH.")
        return override
    found = shutil.which("claude")
    if not found or not os.path.isabs(found):
        _failure(
            "Claude Code is not on PATH. The editorial installer records its absolute path for launchd."
        )
    return found


def claude_command(model):
    # -p is the subscription-authenticated headless mode. No API key is passed.
    return [claude_executable(), "-p", "--output-format", "json", "--model", model]


def require_subscription(executable, runner=None):
    """Refuse to start unless the CLI is the Claude subscription login."""
    run = runner or subprocess.run
    status = run(
        [executable, "auth", "status"],
        env=subscription_environment(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if status.returncode:
        _failure("Sign in to Claude Code with the Claude subscription. The editorial worker does not use an API key.")
    try:
        payload = json.loads(status.stdout)
    except json.JSONDecodeError:
        _failure("Claude Code auth status was not JSON. Sign in with the Claude subscription.")
    if not isinstance(payload, dict) or payload.get("loggedIn") is not True or payload.get("authMethod") != "claude.ai":
        _failure(
            "Claude Code must be the subscription login (authMethod claude.ai). An API key is not the editorial backend."
        )
    return payload.get("authMethod")


def _scan(event, depth=0):
    model = tier = None
    usage = None
    if depth > 4 or not isinstance(event, dict):
        return model, tier, usage
    if isinstance(event.get("model"), str):
        model = event["model"]
    for key in ("service_tier", "serviceTier"):
        if isinstance(event.get(key), str):
            tier = event[key]
    if isinstance(event.get("usage"), dict):
        usage = event["usage"]
    for value in event.values():
        if isinstance(value, dict):
            nested_model, nested_tier, nested_usage = _scan(value, depth + 1)
            model = nested_model or model
            tier = nested_tier or tier
            usage = nested_usage or usage
    return model, tier, usage


def observed_codex(log_path):
    model = tier = None
    usage = {}
    if not log_path.is_file():
        return model, tier, _usage(usage)
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        found_model, found_tier, found_usage = _scan(event)
        if found_model:
            model = found_model
        if found_tier:
            tier = found_tier
        if found_usage:
            usage = found_usage
    return model, tier, _usage({"usage": usage} if usage else {})


def _json_object(text):
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            _failure("Inference did not return JSON.")
        value = json.loads(text[start: end + 1])
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        _failure("Inference JSON was not an object.")
    return value


def _claude_result(log_path):
    if not log_path.is_file():
        _failure("Claude Code returned no output.")
    payload = _json_object(log_path.read_text(encoding="utf-8"))
    if payload.get("is_error") or payload.get("subtype") == "error":
        _failure("Claude Code reported an error. The stage was not accepted.")
    result = payload.get("result", payload)
    if isinstance(result, str):
        result = _json_object(result)
    if not isinstance(result, dict):
        _failure("Claude Code did not return the stage JSON.")
    model = payload.get("model")
    return result, model, _usage(payload)


def _grok_request(model, prompt, key, opener):
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
    ).encode()
    request = urllib.request.Request(
        GROK_URL,
        data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener(request, timeout=180) as response:
            raw = response.read(2 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        # The status is enough. The body and the Authorization header stay off the exception.
        _failure(f"xAI request failed ({exc.code}).")
    except TimeoutError as exc:
        raise local.Deferred("xAI timed out after the request was sent. It was not repeated.") from exc
    payload = json.loads(raw)
    choices = payload.get("choices") if isinstance(payload, dict) else None
    content = choices[0].get("message", {}).get("content") if choices else None
    if not isinstance(content, str):
        _failure("xAI returned no stage JSON.")
    return _json_object(content), payload.get("model"), _usage(payload)


def complete(backend, model, effort, prompt, schema, result, folder, heartbeat, image=None, opener=None):
    """Run one stage. A structured-output failure is retried once. An uncertain paid POST is not."""
    reject_fast(model, None)
    log = folder / "agent.jsonl"
    if backend == "codex":
        command = codex_command(model, effort, schema, result, folder, image)
        code = local.run_process(command, folder=folder, log=log, heartbeat=heartbeat, timeout=1800, stdin=prompt)
        if code:
            raise local.Deferred("Codex paused/failed; preserve checkpoints, no paid fallback.")
        observed, tier, usage = observed_codex(log)
        reject_fast(observed, tier)
        return {"observedModel": observed, "serviceTier": tier or "default", "usage": usage}
    if backend == "claude":
        command = claude_command(model)
        last = None
        for _attempt in range(2):
            code = local.run_process(
                command,
                folder=folder,
                log=log,
                heartbeat=heartbeat,
                timeout=1800,
                stdin=prompt,
                env=subscription_environment(),
            )
            if code:
                raise local.Deferred("Claude Code paused/failed; preserve checkpoints, no paid fallback.")
            try:
                value, observed, usage = _claude_result(log)
                last = None
                break
            except (Exception, json.JSONDecodeError) as exc:
                from panther_journal.editorial import DeterministicFailure

                if not isinstance(exc, (DeterministicFailure, json.JSONDecodeError)):
                    raise
                last = exc
                continue
        if last is not None:
            _failure("Claude Code did not return valid stage JSON.")
        reject_fast(observed or model, None)
        result.write_text(json.dumps(value))
        return {"observedModel": observed, "serviceTier": "default", "usage": usage}
    if backend == "grok":
        key = xai_key()
        if not key:
            _failure(
                "xAI API key is not configured. Set XAI_API_KEY or store it in the OS keychain "
                f"service {KEY_SERVICE}, account {KEY_ACCOUNT}."
            )
        call = opener or urllib.request.urlopen
        last = None
        value = observed = usage = None
        for _attempt in range(2):
            try:
                value, observed, usage = _grok_request(model, prompt, key, call)
                last = None
                break
            except json.JSONDecodeError as exc:
                last = exc
                continue
            except Exception as exc:
                from panther_journal.editorial import DeterministicFailure

                if not isinstance(exc, DeterministicFailure):
                    raise
                last = exc
                if any(code in str(exc) for code in ("429", "500", "502", "503")):
                    continue
                if "no stage JSON" in str(exc) or "did not return JSON" in str(exc):
                    continue
                raise
        if last is not None:
            _failure("xAI did not return valid stage JSON.")
        reject_fast(observed or model, None)
        result.write_text(json.dumps(value))
        log.write_text(json.dumps({"model": observed or model, "usage": usage}))
        return {"observedModel": observed, "serviceTier": "default", "usage": usage}
    _failure("Editorial backend must be claude, grok, or codex.")
