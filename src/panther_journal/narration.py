"""Explicit premium narration, durable reservations, no local-TTS fallback."""

import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
from decimal import Decimal

import click
import requests

from panther_journal import video as v, generation_metadata as generation
from panther_journal.audio_storage import flush_directory, write_json

ENDPOINT = "fal-ai/elevenlabs/tts/eleven-v3"
VOICES = {"Bill", "George", "Brian", "Roger", "Callum", "Alice", "Charlotte", "Lily"}
POLICY = "premium-narration-v1"


def schema(db):
    # Additive migration in the existing private ledger; never reset historical budgets.
    db.execute(
        "CREATE TABLE IF NOT EXISTS narration_budgets (id TEXT PRIMARY KEY, content TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS narration_plans (id TEXT PRIMARY KEY, content TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS narration_attempts (id TEXT PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE, project TEXT NOT NULL, reserved_cents INTEGER NOT NULL CHECK(reserved_cents>0), state TEXT NOT NULL, content TEXT NOT NULL, voice_accepted INTEGER NOT NULL DEFAULT 0)"
    )


def budget_status(db, project):
    row = db.execute("SELECT content FROM narration_budgets WHERE id=?", (project,)).fetchone()
    if not row:
        v.fail("No approved project allocation. Create it once; never reconstruct lost history.")
    b = json.loads(row["content"])
    if (
        b.get("policy") != POLICY
        or b.get("projectId") != project
        or not b.get("approvalEvidence")
        or type(b.get("capCents")) is not int
        or type(b.get("otherHeldCents")) is not int
        or not 0 <= b["otherHeldCents"] < b["capCents"] <= 100000
    ):
        v.fail("Invalid project budget audit; refusing to spend.")
    held = db.execute(
        "SELECT COALESCE(SUM(reserved_cents),0) FROM narration_attempts WHERE project=?", (project,)
    ).fetchone()[0]
    return {
        **b,
        "narrationReservedCents": held,
        "availableNarrationCents": max(0, b["capCents"] - b["otherHeldCents"] - held),
        "videoReservedCents": v.reserved_for(db, project),
        "videoZeroChargeCreditsCents": v.rejection_credits(db, project),
        "availableVideoCents": max(0, b["otherHeldCents"] - v.reserved_for(db, project)),
    }


def create_budget(project, game, cap, other, reason, fal):
    v.identifier(project)
    v.identifier(game)
    limit, hold = v.cents(cap), v.cents(other)
    if not 0 <= hold < limit <= 100000 or not 1 <= len(reason.strip()) <= 1000:
        v.fail(
            "Provide an explicit total ceiling, protected other-media allowance, and approval evidence."
        )
    account = fal.billing()["account"]
    facts = dict(
        policy=POLICY,
        projectId=project,
        gameId=game,
        capCents=limit,
        otherHeldCents=hold,
        approvalEvidence=reason.strip(),
        billingAccount=account,
    )
    with v.database() as db:
        schema(db)
        old = db.execute("SELECT content FROM narration_budgets WHERE id=?", (project,)).fetchone()
        if old:
            previous = json.loads(old["content"])
            previous.pop("createdAt")
            if previous != facts:
                v.fail(
                    "Allocation already exists with different facts. No reset or increase is supported."
                )
        else:
            if v.has_unresolved(db):
                v.fail("Resolve outstanding requests before allocating another project.")
            db.execute(
                "INSERT INTO narration_budgets VALUES (?,?)",
                (project, v.canonical({**facts, "createdAt": int(time.time())})),
            )
        return budget_status(db, project)


def validate(m):
    fields = {
        "schemaVersion",
        "gameId",
        "projectId",
        "purpose",
        "text",
        "voice",
        "direction",
        "sourceKeys",
    }
    if (
        not isinstance(m, dict)
        or not fields <= m.keys()
        or m.keys() - fields - {"approvedAudition"}
        or m["schemaVersion"] != 1
    ):
        v.fail("Expected version-1 narration manifest; see docs/narration-workflow.md.")
    v.identifier(m["gameId"])
    v.identifier(m["projectId"])
    if (
        not isinstance(m["purpose"], str)
        or not isinstance(m["voice"], str)
        or m["purpose"] not in {"audition", "production"}
        or m["voice"] not in VOICES
    ):
        v.fail("Use audition/production and an approved stock voice; cloning is not supported.")
    limit = 600 if m["purpose"] == "audition" else 5000
    if not isinstance(m["text"], str) or not m["text"].strip() or len(m["text"]) > limit:
        v.fail(f"Narration text must contain 1–{limit} characters, including performance tags.")
    if not isinstance(m["direction"], str) or not 1 <= len(m["direction"].strip()) <= 2000:
        v.fail("Record the intended performance and pronunciation direction.")
    if (
        not isinstance(m["sourceKeys"], list)
        or not 1 <= len(m["sourceKeys"]) <= 8
        or any(
            not isinstance(k, str)
            or not k.startswith(f"games/{m['gameId']}/assets/")
            or ".." in k
            or "?" in k
            for k in m["sourceKeys"]
        )
    ):
        v.fail("Pin existing same-game source assets; only the text is sent to fal.")
    if m["purpose"] == "production" and (
        not isinstance(m.get("approvedAudition"), str)
        or not re.fullmatch("[a-f0-9]{64}", m["approvedAudition"])
    ):
        v.fail("Full narration requires an accepted audition from this project.")
    if m["purpose"] == "audition" and "approvedAudition" in m:
        v.fail("An audition cannot claim prior voice acceptance.")
    return m


def payload(m):
    return dict(
        text=m["text"],
        voice=m["voice"],
        stability=0.5,
        timestamps=True,
        language_code="en",
        apply_text_normalization="auto",
    )


def quote(fal, text):
    data = fal.request("GET", v.PLATFORM + "/models/pricing", params={"endpoint_id": ENDPOINT})
    prices = data.get("prices")
    if not isinstance(prices, list) or not all(isinstance(p, dict) for p in prices):
        v.fail("Invalid narration pricing response.")
    matches = [p for p in prices if p.get("endpoint_id") == ENDPOINT]
    if (
        len(matches) != 1
        or matches[0].get("unit") != "1000 characters"
        or matches[0].get("currency") != "USD"
    ):
        v.fail("Unknown narration billing units; refusing to spend.")
    rate = v.number(matches[0]["unit_price"])
    if rate <= 0:
        v.fail("Missing positive narration price.")
    # UTF-8 byte count conservatively exceeds Unicode/UTF-16 character counts.
    estimate = max(rate, Decimal("0.10")) * len(text.encode("utf-8")) / 1000
    return dict(
        unit="1000 characters",
        unitPriceUsd=str(rate),
        estimatedUsd=str(estimate),
        reserveCents=v.cents(estimate * Decimal("1.25")),
        checkedAt=int(time.time()),
    )


def read_plan(db, pid):
    row = db.execute("SELECT * FROM narration_plans WHERE id=?", (pid,)).fetchone()
    if not row:
        v.fail("Unknown narration plan.")
    p = json.loads(row["content"])
    if hashlib.sha256(v.canonical(p).encode()).hexdigest() != pid or p.get("policy") != POLICY:
        v.fail("Narration plan changed; refusing to spend.")
    validate(p["manifest"])
    if p["endpoint"] != ENDPOINT or p["input"] != payload(p["manifest"]):
        v.fail("Narration adapter changed; prepare a new plan.")
    return p, bool(row["approved"])


def accepted_voice(db, m):
    v.assert_generation_open(db, m['projectId'])
    if m["purpose"] == "audition":
        return
    row = db.execute(
        "SELECT * FROM narration_attempts WHERE id=?", (m["approvedAudition"],)
    ).fetchone()
    if not row or row["state"] != "COMPLETED" or not row["voice_accepted"]:
        v.fail("The audition has not been accepted.")
    prior, _ = read_plan(db, row["plan_id"])
    if (
        prior["manifest"]["projectId"] != m["projectId"]
        or prior["manifest"]["gameId"] != m["gameId"]
        or prior["manifest"]["voice"] != m["voice"]
        or prior["manifest"]["purpose"] != "audition"
    ):
        v.fail("Production voice must match the accepted same-project audition.")


def prepare(m, fal):
    validate(m)
    q, billing = quote(fal, m["text"]), fal.billing()
    p = dict(
        policy=POLICY,
        manifest=m,
        endpoint=ENDPOINT,
        input=payload(m),
        quote=q,
        billingAccount=billing["account"],
        createdAt=int(time.time()),
    )
    pid = hashlib.sha256(v.canonical(p).encode()).hexdigest()
    with v.database() as db:
        schema(db)
        b = budget_status(db, m["projectId"])
        accepted_voice(db, m)
        if b["gameId"] != m["gameId"] or b["billingAccount"] != billing["account"]:
            v.fail("Project, game, or billing account mismatch.")
        if q["reserveCents"] > b["availableNarrationCents"]:
            v.fail(
                "Narration would consume the protected video allowance or exceed the project cap."
            )
        db.execute(
            "INSERT OR IGNORE INTO narration_plans (id,content) VALUES (?,?)", (pid, v.canonical(p))
        )
    return dict(planId=pid, approved=False, **p)


def summary(row):
    d = json.loads(row["content"])
    return dict(
        attemptId=row["id"],
        planId=row["plan_id"],
        state=row["state"],
        reservedUsd=f"{row['reserved_cents'] / 100:.2f}",
        requestId=d.get("requestId"),
        downloadPath=d.get("downloadPath"),
        voiceAccepted=bool(row["voice_accepted"]),
    )


def update(aid, state, extra):
    with v.database() as db:
        row = db.execute("SELECT * FROM narration_attempts WHERE id=?", (aid,)).fetchone()
        if not row:
            v.fail("Unknown narration attempt.")
        d = {**json.loads(row["content"]), **extra}
        db.execute(
            "UPDATE narration_attempts SET state=?,content=? WHERE id=?",
            (state, v.canonical(d), aid),
        )
        return summary(db.execute("SELECT * FROM narration_attempts WHERE id=?", (aid,)).fetchone())


def submit(pid, fal):
    aid = hashlib.sha256(("narration:" + pid).encode()).hexdigest()
    with v.database() as db:
        schema(db)
        row = db.execute("SELECT * FROM narration_attempts WHERE id=?", (aid,)).fetchone()
        if row:
            return summary(row)
        p, approved = read_plan(db, pid)
        if not approved:
            v.fail("Approve the exact text, voice, rights and spending before submission.")
    m = p["manifest"]
    q = quote(fal, m["text"])
    billing = fal.billing()
    reserve = p["quote"]["reserveCents"]
    if q["reserveCents"] > reserve or billing["account"] != p["billingAccount"]:
        v.fail("Price increased or billing account changed; no request submitted.")
    with v.database() as db:
        row = db.execute("SELECT * FROM narration_attempts WHERE id=?", (aid,)).fetchone()
        if row:
            return summary(row)
        b = budget_status(db, m["projectId"])
        accepted_voice(db, m)
        if v.has_unresolved(db):
            v.fail("An outstanding video or narration request must be resolved first.")
        if reserve > b["availableNarrationCents"] or billing["account"] != b["billingAccount"]:
            v.fail("Project narration allowance exceeded or account changed.")
        if v.number(billing["balanceUsd"]) * 100 < b["otherHeldCents"] + reserve + 500:
            v.fail("Balance must protect other-media allowance plus the $5 safety floor.")
        db.execute(
            "INSERT INTO narration_attempts VALUES (?,?,?,?,?,?,0)",
            (
                aid,
                pid,
                m["projectId"],
                reserve,
                "SUBMITTING",
                v.canonical({"createdAt": int(time.time())}),
            ),
        )
    try:
        result = fal.request(
            "POST",
            v.QUEUE + "/" + ENDPOINT,
            json=p["input"],
            headers={
                "X-Fal-No-Retry": "1",
                "x-app-fal-disable-fallback": "true",
                "X-Fal-Request-Timeout": "300",
                "X-Fal-Store-IO": "1",
            },
        )
        rid = result["request_id"]
        if not isinstance(rid, str) or not re.fullmatch("[a-zA-Z0-9_-]{1,128}", rid):
            raise ValueError()
        update(aid, "UNKNOWN", {"requestId": rid})
        urls = {
            k: v.queue_url(result[k + "_url"], rid, ENDPOINT, k)
            for k in ("status", "response", "cancel")
        }
        return update(aid, "SUBMITTED", {"requestId": rid, "urls": urls})
    except (click.ClickException, KeyError, ValueError, TypeError):
        update(aid, "UNKNOWN", {})
        v.fail(f"Uncertain submission. Reservation retained. Do not retry; inspect {aid}.")


def poll(aid, fal):
    with v.database() as db:
        row = db.execute("SELECT * FROM narration_attempts WHERE id=?", (aid,)).fetchone()
        if not row:
            v.fail("Unknown narration attempt.")
        if row["state"] in {"COMPLETED", "FAILED", "UNAVAILABLE"}:
            return summary(row)
        d = json.loads(row["content"])
    if not d.get("urls") or not d.get("requestId"):
        v.fail("Uncertain request has no verified URLs. Inspect history; never resubmit.")
    status = fal.request(
        "GET", v.queue_url(d["urls"]["status"], d["requestId"], ENDPOINT, "status")
    )
    if status.get("request_id", d["requestId"]) != d["requestId"]:
        v.fail("Mismatched request identity.")
    if status.get("status") in {"IN_QUEUE", "IN_PROGRESS"}:
        return update(aid, status["status"], {})
    if status.get("status") != "COMPLETED":
        v.fail("Unknown provider state; reservation retained.")
    try:
        result = fal.request(
            "GET",
            v.queue_url(d["urls"]["response"], d["requestId"], ENDPOINT, "response"),
            completed_result=True,
        )
    except v.TerminalModelRejection:
        return update(
            aid, "FAILED", {"reason": "Provider rejected generation; reservation retained."}
        )
    except v.UnavailableResult:
        v.fail(
            "Result unavailable. Reservation retained; inspect provider history, do not regenerate."
        )
    if not isinstance(result.get("audio"), dict) or not isinstance(result["audio"].get("url"), str):
        v.fail("No audio result. Reservation retained.")
    v.media_url(result["audio"]["url"])
    return update(aid, "COMPLETED", {"result": result})


def reconcile_unavailable(aid, fal, reason):
    """Acknowledge a verifiably finished lost result; retain its charge and reservation."""
    if not reason.strip() or len(reason) > 1000:
        v.fail("Provide the owner's explicit lost-result/retry authorization.")
    with v.database() as db:
        row = db.execute("SELECT * FROM narration_attempts WHERE id=?", (aid,)).fetchone()
        if not row:
            v.fail("Unknown narration attempt.")
        if row['state'] == 'UNAVAILABLE':
            return summary(row)
        if row['state'] not in {'SUBMITTED', 'IN_QUEUE', 'IN_PROGRESS'}:
            v.fail("Only acknowledged submissions can be reconciled; uncertainty stays blocked.")
        old_state, old_content = row['state'], row['content']
        data = json.loads(old_content)
        plan, _ = read_plan(db, row['plan_id'])
    if fal.billing()['account'] != plan['billingAccount']:
        v.fail("Billing account changed.")
    rid = data.get('requestId')
    if not rid or not data.get('urls'):
        v.fail("Missing verified request identity.")
    status = fal.request('GET', v.queue_url(data['urls']['status'], rid, ENDPOINT, 'status'))
    if status.get('request_id') != rid or status.get('status') != 'COMPLETED':
        v.fail("Request is not verifiably completed.")
    try:
        fal.request('GET', v.queue_url(data['urls']['response'], rid, ENDPOINT, 'response'), completed_result=True)
    except v.UnavailableResult:
        pass
    else:
        v.fail("Result is available; use poll/download.")
    billed = fal.billing_events([rid]).get(rid)
    if not billed or billed.get('endpoint') != ENDPOINT or not v.number(billed.get('amount')).is_finite() or v.number(billed['amount']) < 0:
        v.fail("Exact valid billing evidence required.")
    evidence = dict(verifiedAt=int(time.time()), requestId=rid, billingEvent=billed,
                    responseHttpStatus=404, queueStatus='COMPLETED', ownerAuthorization=reason,
                    reservationRetained=True, outcome='output-unavailable', previousState=old_state,
                    previousContentSha256=hashlib.sha256(old_content.encode()).hexdigest())
    with v.database() as db:
        current = db.execute('SELECT * FROM narration_attempts WHERE id=?', (aid,)).fetchone()
        if current['state'] != old_state or current['content'] != old_content:
            v.fail("Attempt changed; inspect before retrying reconciliation.")
        data['reconciliation'] = evidence
        db.execute("UPDATE narration_attempts SET state='UNAVAILABLE',content=? WHERE id=?", (v.canonical(data), aid))
        return summary(db.execute('SELECT * FROM narration_attempts WHERE id=?', (aid,)).fetchone())


def download(aid, fal):
    with v.database() as db:
        row = db.execute("SELECT * FROM narration_attempts WHERE id=?", (aid,)).fetchone()
        if not row or row["state"] != "COMPLETED":
            v.fail("Only completed narration can be downloaded.")
        d = json.loads(row["content"])
        p, _ = read_plan(db, row["plan_id"])
    folder = v.private_root() / "narration-outputs"
    folder.mkdir(exist_ok=True, mode=0o700)
    target = folder / (aid + ".mp3")
    tmp = folder / ("." + uuid.uuid4().hex + ".partial")
    digest = hashlib.sha256()
    size = 0
    if target.exists():
        v.fail("Original exists; inspect/recover it without overwriting or regenerating.")
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get(
                v.media_url(d["result"]["audio"]["url"]),
                stream=True,
                timeout=(10, 30),
                allow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    v.fail("Audio download failed; retry only the download.")
                with os.fdopen(
                    os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
                ) as f:
                    for chunk in response.iter_content(1024 * 1024):
                        size += len(chunk)
                        if size > 32 * 1024**2:
                            v.fail("Audio exceeds the bounded 32 MiB limit.")
                        digest.update(chunk)
                        f.write(chunk)
                    f.flush()
                    os.fsync(f.fileno())
        with tmp.open("rb") as f:
            head = f.read(3)
        if size < 100 or not (head == b"ID3" or (head[0] == 255 and head[1] & 224 == 224)):
            v.fail("Expected an MP3 original; inspect without regenerating.")
        os.link(tmp, target)
        flush_directory(folder)
    except requests.RequestException:
        v.fail("Download interrupted; generation remains completed.")
    finally:
        tmp.unlink(missing_ok=True)
    billed = None
    try:
        event = fal.billing_events([d["requestId"]]).get(d["requestId"])
        if event and event["endpoint"] == ENDPOINT:
            billed = event["amount"]
    except click.ClickException:
        pass
    m = p["manifest"]
    metadata = dict(
        title="Narration — " + m["purpose"],
        category="creative-reimagining",
        sourceKeys=m["sourceKeys"],
        extra=dict(
            relationshipRole="finished",
            contextUse="exclude",
            generation=generation.fal(ENDPOINT, d["requestId"], billed),
            narrationPolicy=POLICY,
            voice=m["voice"],
            reviewStatus="audition" if m["purpose"] == "audition" else "candidate",
        ),
    )
    mp = folder / (aid + ".metadata.json")
    write_json(mp, metadata)
    write_json(
        folder / (aid + ".provenance.json"),
        dict(
            policy=POLICY,
            plan=p,
            requestId=d["requestId"],
            sha256=digest.hexdigest(),
            reservationCents=row["reserved_cents"],
            generation=metadata["extra"]["generation"],
            sourceKeys=m["sourceKeys"],
            review="No performance-quality approval implied by a successful API response.",
        ),
    )
    return update(
        aid,
        "COMPLETED",
        dict(downloadPath=str(target), metadataPath=str(mp), sha256=digest.hexdigest()),
    )


@click.group()
def narration():
    """Premium voice auditions and narration; no automatic generation or cheap fallback."""


@narration.command("allocate")
@click.option("--project", required=True)
@click.option("--game", required=True)
@click.option("--cap", required=True)
@click.option("--hold-for-other-media", required=True)
@click.option("--reason", required=True)
@click.option("--owner-approved", is_flag=True, required=True)
def allocate(project, game, cap, hold_for_other_media, reason, owner_approved):
    if not owner_approved:
        v.fail("Explicit project budget approval required.")
    click.echo(
        json.dumps(
            create_budget(project, game, cap, hold_for_other_media, reason, v.Fal()), indent=2
        )
    )


@narration.command("budget")
@click.argument("project")
def budget_command(project):
    with v.database() as db:
        schema(db)
        click.echo(json.dumps(budget_status(db, project), indent=2))


@narration.command("prepare")
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def prepare_command(manifest):
    if manifest.stat().st_size > 50000:
        v.fail("Narration manifest too large.")
    click.echo(json.dumps(prepare(json.loads(manifest.read_text()), v.Fal()), indent=2))


@narration.command("approve")
@click.argument("plan_id")
@click.option("--text-voice-rights-approved", is_flag=True, required=True)
@click.option("--auto-topup-disabled", is_flag=True, required=True)
def approve(plan_id, text_voice_rights_approved, auto_topup_disabled):
    if not text_voice_rights_approved or not auto_topup_disabled:
        v.fail("Both explicit owner declarations are required.")
    with v.database() as db:
        p, _ = read_plan(db, plan_id)
        accepted_voice(db, p["manifest"])
        if (
            p["quote"]["reserveCents"]
            > budget_status(db, p["manifest"]["projectId"])["availableNarrationCents"]
        ):
            v.fail("Plan no longer fits the protected project allowance.")
        db.execute("UPDATE narration_plans SET approved=1 WHERE id=?", (plan_id,))
    click.echo("Approved one exact narration request; nothing generated.")


@narration.command("submit")
@click.argument("plan_id")
def submit_command(plan_id):
    click.echo(json.dumps(submit(plan_id, v.Fal()), indent=2))


@narration.command("poll")
@click.argument("attempt_id")
def poll_command(attempt_id):
    click.echo(json.dumps(poll(attempt_id, v.Fal()), indent=2))


@narration.command("download")
@click.argument("attempt_id")
def download_command(attempt_id):
    click.echo(json.dumps(download(attempt_id, v.Fal()), indent=2))


@narration.command("reconcile-unavailable")
@click.argument("attempt_id")
@click.option("--owner-approved", is_flag=True, required=True)
@click.option("--reason", required=True)
def reconcile_command(attempt_id, owner_approved, reason):
    if not owner_approved:
        v.fail("Explicit owner approval required.")
    click.echo(json.dumps(reconcile_unavailable(attempt_id, v.Fal(), reason), indent=2))


@narration.command("accept-voice")
@click.argument("attempt_id")
@click.option("--owner-approved", is_flag=True, required=True)
def accept_voice(attempt_id, owner_approved):
    with v.database() as db:
        row = db.execute("SELECT * FROM narration_attempts WHERE id=?", (attempt_id,)).fetchone()
        if not owner_approved or not row or row["state"] != "COMPLETED":
            v.fail("An explicit audition approval is required.")
        p, _ = read_plan(db, row["plan_id"])
        d = json.loads(row["content"])
        if p["manifest"]["purpose"] != "audition" or not d.get("downloadPath"):
            v.fail("Download and review the audition first.")
        d.setdefault("voiceAcceptedAt", int(time.time()))
        db.execute(
            "UPDATE narration_attempts SET voice_accepted=1,content=? WHERE id=?",
            (v.canonical(d), attempt_id),
        )
    click.echo("Voice selection recorded; full narration still needs its own approved plan.")
