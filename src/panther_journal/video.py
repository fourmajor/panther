"""Explicitly approved fal comparisons; durable, conservative local spending reservations.

This is not an editorial-worker fallback and never runs from a Step Functions callback.
"""

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit
import uuid

import click
import requests

from panther_journal import cloud
from panther_journal.audio_storage import flush_directory, flush_file, write_json

ROOT = Path.home() / "Library/Application Support/Panther/video-comparison"
LIMIT_CENTS = 5000
PLATFORM = "https://api.fal.ai/v1"
QUEUE = "https://queue.fal.run"
# Reviewed bounded text-to-video profiles only. Do not accept arbitrary model arguments,
# compute-priced models, voice references, multi-shot expansion or automatic prompt rewriting.
PROFILES = {
    "veo-3.1-fast": {
        "endpoint": "fal-ai/veo3.1/fast",
        "floor": "0.15",
        "multiplier": "1",
        "source": "https://fal.ai/models/fal-ai/veo3.1/fast",
    },
    "kling-3-pro": {
        "endpoint": "fal-ai/kling-video/v3/pro/text-to-video",
        "floor": "0.21",
        "multiplier": "1.5",
        "source": "https://fal.ai/models/fal-ai/kling-video/v3/pro/text-to-video",
    },
}


def fail(message):
    raise click.ClickException(message)


def number(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError()
        return result
    except (InvalidOperation, ValueError):
        fail("Invalid monetary value; refusing to spend.")


def cents(value):
    return int((number(value) * 100).to_integral_value(rounding=ROUND_CEILING))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identifier(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value)
        or len(value) > 96
    ):
        fail("Expected a lowercase, hyphenated identifier of at most 96 characters.")
    return value


def private_root():
    root = ROOT.resolve()
    if any((p / ".git").exists() for p in (root, *root.parents)) or root in {
        Path.home(),
        Path("/"),
    }:
        fail("Video state must be in its dedicated private directory outside Git.")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    return root


@contextmanager
def database(*, initialize=False):
    root = private_root()
    path = root / "budget.sqlite3"
    if not initialize and not path.exists():
        fail("Budget not initialized. Run panther video budget init first.")
    # Private journal files too; no user-controlled state-root flag or automatic reset.
    old_umask = os.umask(0o077)
    db = None
    try:
        db = sqlite3.connect(path, timeout=1, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        if initialize:
            db.execute(
                "CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY CHECK(id=1), limit_cents INTEGER NOT NULL CHECK(limit_cents=5000))"
            )
            db.execute("INSERT OR IGNORE INTO budget VALUES (1, ?)", (LIMIT_CENTS,))
            db.execute(
                "CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, content TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, shot TEXT NOT NULL, ordinal INTEGER NOT NULL, reserved_cents INTEGER NOT NULL CHECK(reserved_cents>0), state TEXT NOT NULL, content TEXT NOT NULL, UNIQUE(plan_id,shot,ordinal))"
            )
        if db.execute("SELECT limit_cents FROM budget WHERE id=1").fetchone()[0] != LIMIT_CENTS:
            fail("Unexpected budget configuration; refusing to spend.")
        yield db
        db.commit()
    except sqlite3.Error:
        if db:
            db.rollback()
        fail(
            "Budget ledger unavailable, locked or damaged. Do not reset it or resubmit; inspect first."
        )
    finally:
        if db:
            db.close()
        os.umask(old_umask)


def totals(db):
    held = db.execute("SELECT COALESCE(SUM(reserved_cents),0) FROM attempts").fetchone()[0]
    return {
        "limitUsd": "50.00",
        "reservedLifetimeUsd": f"{held / 100:.2f}",
        "availableToReserveUsd": f"{max(0, LIMIT_CENTS - held) / 100:.2f}",
        "actualProviderSpendUsd": None,
        "reservationCents": held,
    }


class Fal:
    def __init__(self):
        key = cloud.credential_store().get_password("panther.place/fal", "api-key")
        if not key or not key.strip():
            fail("fal key missing from the OS credential store (panther.place/fal, api-key).")
        self.session = requests.Session()
        self.session.trust_env = False  # No netrc or accidental credential-bearing proxy fallback.
        self.session.headers["Authorization"] = "Key " + key

    def billing(self):
        # Admin credentials never enter the generation client or a general-purpose API method.
        key = cloud.credential_store().get_password("panther.place/fal", "admin-key")
        if not key or not key.strip():
            fail("Store the separate admin-key in Keychain for read-only billing checks.")
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.get(
                    PLATFORM + "/account/billing",
                    params={"expand": "credits"},
                    headers={"Authorization": "Key " + key},
                    timeout=(10, 20),
                    allow_redirects=False,
                )
                if response.status_code != 200:
                    fail("Read-only fal billing check failed; generation is blocked.")
                data = response.json()
                if (
                    not isinstance(data, dict)
                    or not data.get("username")
                    or data["credits"]["currency"] != "USD"
                ):
                    raise ValueError()
                balance = number(data["credits"]["current_balance"])
                return {"account": data["username"], "balanceUsd": str(balance)}
        except (requests.RequestException, KeyError, TypeError, ValueError):
            fail("Read-only fal billing response unavailable or invalid; generation is blocked.")

    def request(self, method, url, **kwargs):
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.netloc not in {"api.fal.ai", "queue.fal.run"}
            or parts.username
            or parts.fragment
        ):
            fail("Refusing to send fal credentials to an untrusted URL.")
        try:
            response = self.session.request(
                method, url, timeout=(10, 30), allow_redirects=False, **kwargs
            )
            # Never print provider error bodies/headers: they may echo prompts or credentials.
            if not 200 <= response.status_code < 300:
                fail(f"fal returned HTTP {response.status_code}; no automatic retry was made.")
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (requests.RequestException, ValueError):
            fail("fal response unavailable or invalid. No automatic retry was made.")

    def price(self, model):
        endpoint = PROFILES[model]["endpoint"]
        data = self.request("GET", PLATFORM + "/models/pricing", params={"endpoint_id": endpoint})
        if not isinstance(data.get("prices"), list) or not all(
            isinstance(p, dict) for p in data["prices"]
        ):
            fail("Invalid pricing response; refusing to spend.")
        matches = [p for p in data["prices"] if p.get("endpoint_id") == endpoint]
        if (
            len(matches) != 1
            or matches[0].get("currency") != "USD"
            or matches[0].get("unit") != "seconds"
        ):
            fail("Unknown currency or billing units; refusing to estimate or generate.")
        price = number(matches[0]["unit_price"])
        if price <= 0:
            fail("Missing positive model pricing; refusing to spend.")
        return price


def quote(fal, model):
    profile = PROFILES[model]
    base = fal.price(model)
    # fal pricing API returns a base, not a settings-aware binding quotation. Audio can be
    # a multiplier (Kling); use the higher reviewed rate, then reserve another 25% headroom.
    rate = max(number(profile["floor"]), base * number(profile["multiplier"]))
    estimate = rate * 8
    return {
        "baseUnitPriceUsd": str(base),
        "conservativeEstimateUsd": str(estimate),
        "reserveCents": cents(estimate * Decimal("1.25")),
        "quotedAt": int(time.time()),
        "source": profile["source"],
        "unit": "seconds",
        "durationSeconds": 8,
    }


def validate_manifest(value):
    fields = {"schemaVersion", "gameId", "sessionId", "sourceKeys", "shots"}
    if not isinstance(value, dict) or set(value) != fields or value["schemaVersion"] != 1:
        fail("Expected a version-1 video comparison manifest; see docs/fal-video-comparison.md.")
    for name in ("gameId", "sessionId"):
        identifier(value[name])
    sources = value["sourceKeys"]
    if (
        not isinstance(sources, list)
        or len(sources) > 20
        or any(
            not isinstance(k, str)
            or not k.startswith(f"games/{value['gameId']}/assets/")
            or ".." in k
            or "?" in k
            for k in sources
        )
    ):
        fail("Source keys must refer to immutable assets in the same game.")
    if not isinstance(value["shots"], list) or not 1 <= len(value["shots"]) <= 20:
        fail("Provide 1–20 explicitly bounded comparison shots.")
    seen = set()
    for shot in value["shots"]:
        if not isinstance(shot, dict) or set(shot) != {"id", "model", "prompt", "maxAttempts"}:
            fail(
                "Each shot requires id, model, prompt and maxAttempts; arbitrary provider arguments are forbidden."
            )
        identifier(shot["id"])
        if shot["id"] in seen or shot["model"] not in PROFILES:
            fail("Duplicate shot or unsupported model profile.")
        seen.add(shot["id"])
        if not isinstance(shot["prompt"], str) or not 1 <= len(shot["prompt"].strip()) <= 2500:
            fail("Prompts must contain 1–2500 characters.")
        if type(shot["maxAttempts"]) is not int or not 1 <= shot["maxAttempts"] <= 3:
            fail("Each shot allows at most three attempts, all charged to the same budget.")
    return value


def payload(shot):
    body = {"prompt": shot["prompt"], "aspect_ratio": "16:9", "generate_audio": True}
    if shot["model"] == "veo-3.1-fast":
        body.update(duration="8s", resolution="720p", auto_fix=False)
    else:
        body.update(duration="8", shot_type="customize")
    return body


def prepare(value, fal):
    validate_manifest(value)
    billing = fal.billing()
    quotes = {model: quote(fal, model) for model in {s["model"] for s in value["shots"]}}
    plan = {
        "profileVersion": 1,
        "manifest": value,
        "inputs": {
            s["id"]: {"endpoint": PROFILES[s["model"]]["endpoint"], "payload": payload(s)}
            for s in value["shots"]
        },
        "quotes": quotes,
        "createdAt": int(time.time()),
        "billingAccount": billing["account"],
        "worstCaseReservationCents": sum(
            quotes[s["model"]]["reserveCents"] * s["maxAttempts"] for s in value["shots"]
        ),
    }
    plan_id = hashlib.sha256(canonical(plan).encode()).hexdigest()
    for shot in value["shots"]:
        upload_metadata(
            value,
            shot["id"],
            PROFILES[shot["model"]]["endpoint"],
            "r" * 128,
            plan_id,
            "a" * 64,
            quotes[shot["model"]]["reserveCents"],
            "0" * 64,
        )
    with database() as db:
        if totals(db)["reservationCents"] + plan["worstCaseReservationCents"] > LIMIT_CENTS:
            fail("Plan including all retries exceeds the remaining $50 budget.")
        db.execute(
            "INSERT OR IGNORE INTO plans (id,content) VALUES (?,?)", (plan_id, canonical(plan))
        )
    return {
        "planId": plan_id,
        "approved": False,
        "worstCaseReservationUsd": f"{plan['worstCaseReservationCents'] / 100:.2f}",
        "quotes": quotes,
    }


def read_plan(db, plan_id):
    row = db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        fail("Unknown plan.")
    plan = json.loads(row["content"])
    if (
        hashlib.sha256(canonical(plan).encode()).hexdigest() != plan_id
        or plan.get("profileVersion") != 1
    ):
        fail("Pinned plan changed or is incompatible. Refusing to spend.")
    for shot in plan["manifest"]["shots"]:
        if plan["inputs"][shot["id"]] != {
            "endpoint": PROFILES[shot["model"]]["endpoint"],
            "payload": payload(shot),
        }:
            fail("Model adapter changed. Prepare and approve a new plan.")
    return plan, bool(row["approved"])


def summary(row):
    data = json.loads(row["content"])
    return {
        "attemptId": row["id"],
        "planId": row["plan_id"],
        "shotId": row["shot"],
        "attempt": row["ordinal"],
        "state": row["state"],
        "reservedUsd": f"{row['reserved_cents'] / 100:.2f}",
        "requestId": data.get("requestId"),
        "downloadPath": data.get("downloadPath"),
    }


def update_attempt(attempt_id, state, additions):
    with database() as db:
        row = db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        data = {**json.loads(row["content"]), **additions}
        db.execute(
            "UPDATE attempts SET state=?,content=? WHERE id=?", (state, canonical(data), attempt_id)
        )
        return summary(db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone())


def queue_url(url, request_id, endpoint, kind):
    parts = urlsplit(url)
    # fal may return the model root or the full subpath. Only its exact queue origin,
    # matching request and matching model family are allowed to receive credentials.
    roots = {endpoint, "/".join(endpoint.split("/")[:2])}
    suffixes = {"status": ["/status"], "response": ["", "/response"], "cancel": ["/cancel"]}[kind]
    allowed = {f"/{root}/requests/{request_id}{suffix}" for root in roots for suffix in suffixes}
    if (
        parts.scheme != "https"
        or parts.netloc != "queue.fal.run"
        or parts.path not in allowed
        or parts.query
        or parts.fragment
    ):
        fail("Untrusted queue response URL. Reservation retained; inspect the request.")
    return url


def submit(plan_id, shot_id, ordinal, reason, fal):
    with database() as db:
        previous = db.execute(
            "SELECT * FROM attempts WHERE plan_id=? AND shot=? AND ordinal=?",
            (plan_id, shot_id, ordinal),
        ).fetchone()
        if previous:
            return summary(previous)  # Idempotent locally, even after an uncertain POST.
        plan, approved = read_plan(db, plan_id)
        if not approved:
            fail("Plan is not approved for these models, rights and account settings.")
        shot = next((s for s in plan["manifest"]["shots"] if s["id"] == shot_id), None)
        if not shot or not 1 <= ordinal <= shot["maxAttempts"]:
            fail("Attempt not allowed by the pinned plan.")
    current_quote = quote(fal, shot["model"])
    billing = fal.billing()
    reserve = plan["quotes"][shot["model"]]["reserveCents"]
    if current_quote["reserveCents"] > reserve:
        fail("Pricing increased. Prepare and approve a new plan before spending.")
    if (
        billing["account"] != plan["billingAccount"]
        or number(billing["balanceUsd"]) * 100 < reserve + 500
    ):
        fail(
            "Billing account changed or credit balance cannot cover this reservation plus the $5 safety floor."
        )
    attempt_id = hashlib.sha256(f"{plan_id}:{shot_id}:{ordinal}".encode()).hexdigest()
    endpoint = PROFILES[shot["model"]]["endpoint"]
    content = {
        "endpoint": endpoint,
        "input": payload(shot),
        "quote": current_quote,
        "createdAt": int(time.time()),
        "retryReason": reason,
    }
    with database() as db:
        previous = db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if previous:
            return summary(previous)
        if db.execute(
            "SELECT 1 FROM attempts WHERE state NOT IN ('COMPLETED','FAILED')"
        ).fetchone():
            fail("An outstanding or uncertain request must be resolved before another submission.")
        if ordinal > 1:
            prior = db.execute(
                "SELECT state FROM attempts WHERE plan_id=? AND shot=? AND ordinal=?",
                (plan_id, shot_id, ordinal - 1),
            ).fetchone()
            if not prior or not reason.strip():
                fail("Retries require the previous attempt and an explicit reason.")
        if totals(db)["reservationCents"] + reserve > LIMIT_CENTS:
            fail("The $50 total budget cannot cover this attempt.")
        db.execute(
            "INSERT INTO attempts VALUES (?,?,?,?,?,?,?)",
            (attempt_id, plan_id, shot_id, ordinal, reserve, "SUBMITTING", canonical(content)),
        )
    # The full reservation is durable before any byte of a billable POST is sent.
    # Never automatically retry this POST (including 4xx, 5xx, timeouts and bad JSON).
    try:
        result = fal.request(
            "POST",
            QUEUE + "/" + endpoint,
            json=content["input"],
            headers={
                "X-Fal-No-Retry": "1",
                "x-app-fal-disable-fallback": "true",
                "X-Fal-Request-Timeout": "300",
                "X-Fal-Store-IO": "0",
            },
        )
        request_id = result["request_id"]
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", request_id):
            raise ValueError()
        update_attempt(attempt_id, "UNKNOWN", {"requestId": request_id})
        urls = {
            kind: queue_url(result[kind + "_url"], request_id, endpoint, kind)
            for kind in ("status", "response", "cancel")
        }
        return update_attempt(attempt_id, "SUBMITTED", {"requestId": request_id, "urls": urls})
    except (click.ClickException, KeyError, ValueError, TypeError):
        update_attempt(attempt_id, "UNKNOWN", {})
        fail(
            f"Submission outcome uncertain. Reservation retained. Do NOT resubmit. Inspect attempt {attempt_id} and fal request history."
        )


def poll(attempt_id, fal):
    with database() as db:
        row = db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if not row:
            fail("Unknown attempt.")
        data = json.loads(row["content"])
        if row["state"] in {"COMPLETED", "FAILED"}:
            return summary(row)
        if not data.get("requestId") or not data.get("urls"):
            fail(
                "Request ID or verified queue URLs missing after uncertain submission. Inspect fal history; do not retry or erase the reservation."
            )
    status = fal.request(
        "GET", queue_url(data["urls"]["status"], data["requestId"], data["endpoint"], "status")
    )
    if status.get("status") not in {"IN_QUEUE", "IN_PROGRESS", "COMPLETED"}:
        fail("Unknown queue status; reservation retained.")
    if status["status"] != "COMPLETED":
        return update_attempt(attempt_id, status["status"], {})
    if status.get("error") or status.get("error_type"):
        return update_attempt(attempt_id, "FAILED", {"providerError": True})
    result = fal.request(
        "GET", queue_url(data["urls"]["response"], data["requestId"], data["endpoint"], "response")
    )
    if not isinstance(result.get("video"), dict) or not isinstance(result["video"].get("url"), str):
        fail("Completed response has no video. Reservation retained; inspect before retrying.")
    return update_attempt(attempt_id, "COMPLETED", {"result": result})


def media_url(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or parts.port not in {None, 443}
        or parts.fragment
    ):
        fail("Untrusted generated-media URL.")
    if host == "fal.media" or host.endswith(".fal.media"):
        return url
    if host == "storage.googleapis.com" and parts.path.startswith("/falserverless/"):
        return url
    fail("Generated media is not on an approved fal delivery host.")


def upload_metadata(manifest, shot, endpoint, request_id, plan_id, attempt_id, reserve, digest):
    metadata = {
        "title": f"Video comparison — {shot}",
        "category": "creative-reimagining",
        "sessionId": manifest["sessionId"],
        "sourceKeys": manifest["sourceKeys"],
        "tags": ["video-comparison", "ai-generated"],
        "extra": {
            "provider": "fal",
            "endpoint": endpoint,
            "requestId": request_id,
            "planId": plan_id,
            "attemptId": attempt_id,
            "sha256": digest,
            "reviewStatus": "unreviewed",
            "reservedUsd": f"{reserve / 100:.2f}",
        },
    }
    # Leave headroom for S3's base64 encoding and Panther's authenticated metadata headers.
    if len(canonical(metadata).encode()) > 1100:
        fail(
            "Upload metadata is too large. Reference a compact same-game provenance asset instead of many source keys."
        )
    return metadata


def download(attempt_id):
    with database() as db:
        row = db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if not row or row["state"] != "COMPLETED":
            fail("Only completed video attempts can be downloaded.")
        data = json.loads(row["content"])
        plan, _ = read_plan(db, row["plan_id"])
    url = media_url(data["result"]["video"]["url"])
    folder = private_root() / "outputs"
    folder.mkdir(mode=0o700, exist_ok=True)
    target = folder / f"{attempt_id}.mp4"
    metadata = folder / f"{attempt_id}.metadata.json"
    if target.exists():
        fail(
            f"Original already exists at {target}; inspect it instead of overwriting or regenerating."
        )
    temporary = folder / f".{uuid.uuid4().hex}.partial"
    digest, size = hashlib.sha256(), 0
    try:
        # A separate, unauthenticated client: never attach either API key to a CDN download.
        with requests.Session() as session:
            session.trust_env = False
            with session.get(url, stream=True, timeout=(10, 30), allow_redirects=False) as response:
                if response.status_code != 200:
                    fail(
                        "Media download failed; poll/inspect the existing request, do not regenerate."
                    )
                with os.fdopen(
                    os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
                ) as stream:
                    for chunk in response.iter_content(1024 * 1024):
                        size += len(chunk)
                        if size > 128 * 1024**2:
                            fail("Generated video exceeds the 128 MiB download limit.")
                        digest.update(chunk)
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
        with temporary.open("rb") as stream:
            if size < 12 or stream.read(12)[4:8] != b"ftyp":
                fail("Expected an MP4 original; inspect the provider output without rerunning it.")
        flush_file(temporary)
        os.link(temporary, target)
        flush_directory(folder)
    except requests.RequestException:
        fail("Download interrupted. Retry the download, not the generation.")
    finally:
        temporary.unlink(missing_ok=True)
    manifest = plan["manifest"]
    write_json(
        metadata,
        upload_metadata(
            manifest,
            row["shot"],
            data["endpoint"],
            data["requestId"],
            row["plan_id"],
            attempt_id,
            row["reserved_cents"],
            digest.hexdigest(),
        ),
    )
    return update_attempt(
        attempt_id,
        "COMPLETED",
        {"downloadPath": str(target), "metadataPath": str(metadata), "sha256": digest.hexdigest()},
    )


@click.group()
def video():
    """Explicitly approved fal video comparisons with a single lifetime $50 local budget."""


@video.command("check")
def check():
    """Check authentication/pricing only. Never submits a generation."""
    fal = Fal()
    result = {
        "authenticated": True,
        "quotes": {model: quote(fal, model) for model in PROFILES},
        "billingAccess": False,
    }
    try:
        billing = fal.billing()
        result.update(billingAccess=True, billing=billing)
    except click.ClickException:
        result["billingNote"] = (
            "Balance unavailable. Store the separate admin-key; paid submission remains blocked."
        )
    click.echo(json.dumps(result, indent=2))


@video.group()
def budget():
    """Inspect conservative reservations, not an assertion of actual provider charges."""


@budget.command("init")
def initialize():
    """Initialize once; repeated invocations preserve all reservations. No reset or top-up."""
    with database(initialize=True) as db:
        click.echo(json.dumps(totals(db), indent=2))


@budget.command("status")
def budget_status():
    with database() as db:
        click.echo(
            json.dumps(
                {
                    **totals(db),
                    "attempts": [
                        summary(r) for r in db.execute("SELECT * FROM attempts ORDER BY rowid")
                    ],
                },
                indent=2,
            )
        )


@video.command("prepare")
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def prepare_command(manifest):
    """Pin a private plan and conservative live quotes; no generation or approval."""
    if manifest.stat().st_size > 100000:
        fail("Manifest too large.")
    try:
        value = json.loads(manifest.read_text())
    except ValueError:
        fail("Invalid JSON manifest.")
    click.echo(json.dumps(prepare(value, Fal()), indent=2))


@video.command("show-plan")
@click.argument("plan_id")
def show_plan(plan_id):
    """Inspect pinned prompts/settings/quotes privately before approving or retrying."""
    with database() as db:
        plan, approved = read_plan(db, plan_id)
        click.echo(json.dumps({"planId": plan_id, "approved": approved, **plan}, indent=2))


@video.command("approve")
@click.argument("plan_id")
@click.option(
    "--models-and-rights-approved",
    is_flag=True,
    required=True,
    help="Owner explicitly approved these models, prompts, native audio and rights; no voice cloning.",
)
@click.option(
    "--auto-topup-disabled",
    is_flag=True,
    required=True,
    help="Owner confirmed auto-top-up is disabled and this is the dedicated $50 comparison balance.",
)
def approve(plan_id, models_and_rights_approved, auto_topup_disabled):
    """Record explicit owner decisions only; never infer them from an AI review."""
    if not models_and_rights_approved or not auto_topup_disabled:
        fail("Both owner declarations are required.")
    with database() as db:
        plan, _ = read_plan(db, plan_id)
        if totals(db)["reservationCents"] + plan["worstCaseReservationCents"] > LIMIT_CENTS:
            fail("Plan no longer fits the remaining budget.")
        db.execute("UPDATE plans SET approved=1 WHERE id=?", (plan_id,))
    click.echo("Plan approved; no generation submitted.")


@video.command("submit")
@click.argument("plan_id")
@click.option("--shot", required=True)
@click.option("--attempt", type=click.IntRange(1, 3), default=1)
@click.option("--reason", default="", help="Required for another paid attempt.")
def submit_command(plan_id, shot, attempt, reason):
    """Submit one explicitly approved attempt. Repeating the command never duplicates it."""
    click.echo(json.dumps(submit(plan_id, shot, attempt, reason, Fal()), indent=2))


@video.command("poll")
@click.argument("attempt_id")
def poll_command(attempt_id):
    """Resume one existing request; does not submit or retry a generation."""
    click.echo(json.dumps(poll(attempt_id, Fal()), indent=2))


@video.command("download")
@click.argument("attempt_id")
def download_command(attempt_id):
    """Keep the original MP4 and upload-ready metadata privately; no generation or S3 write."""
    click.echo(json.dumps(download(attempt_id), indent=2))
