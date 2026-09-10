from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import base64
import hashlib
import struct
import zlib
from threading import Barrier

import click
from click.testing import CliRunner
import pytest

from panther_journal import video as v
from panther_journal.cli import main


class FakeFal:
    def __init__(self):
        self.posts = []
        self.rate = Decimal("0.15")
        self.balance = "50.00"
        self.account = "synthetic-account"
        self.error = False
        self.status = "COMPLETED"

    def price(self, model):
        return self.rate

    def billing(self):
        return {"balanceUsd": self.balance, "account": self.account}

    def request(self, method, url, **kwargs):
        if method == "POST":
            self.posts.append((url, kwargs))
            if self.error:
                raise click.ClickException("Synthetic uncertain response")
            root = url + "/requests/synthetic-request"
            return {
                "request_id": "synthetic-request",
                "status_url": root + "/status",
                "response_url": root,
                "cancel_url": root + "/cancel",
            }
        if url.endswith("/status"):
            return {"status": self.status}
        return {"video": {"url": "https://v3.fal.media/files/synthetic.mp4"}}


def manifest():
    return {
        "schemaVersion": 1,
        "gameId": "synthetic-game",
        "sessionId": "synthetic-session",
        "sourceKeys": [],
        "shots": [
            {
                "id": "scene-veo",
                "model": "veo-3.1-fast",
                "prompt": "A fictional harbor at dusk.",
                "maxAttempts": 3,
            }
        ],
    }


def image_manifest(tmp_path, monkeypatch):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1280, 720, 8, 2, 0, 0, 0))
    data += chunk(b"IDAT", zlib.compress((b"\x00" + b"\x11\x22\x33" * 1280) * 720)) + chunk(
        b"IEND", b""
    )
    path = tmp_path / "frame.png"
    path.write_bytes(data)
    ref = {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "key": "games/synthetic-game/assets/frame/original/frame.png",
    }
    m = manifest()
    m["sourceKeys"] = [ref["key"]]
    m["characterIds"] = ["hero"]
    m["shots"][0].update(model="veo-3.1-fast-image", image=ref, maxAttempts=1)
    monkeypatch.setattr(v.cloud, "configuration", lambda: {})
    monkeypatch.setattr(
        v.cloud,
        "api",
        lambda *a, **kw: {
            "size": len(data),
            "contentType": "image/png",
            "sha256": base64.b64encode(hashlib.sha256(data).digest()).decode(),
        },
    )
    return m, path


def test_image_plan_pins_local_and_cloud_bytes_without_uploading_or_spending(
    setup, tmp_path, monkeypatch
):
    m, path = image_manifest(tmp_path, monkeypatch)
    plan_id = v.prepare(m, setup)["planId"]
    assert setup.posts == []
    assert (
        CliRunner()
        .invoke(
            main,
            ["video", "approve", plan_id, "--models-and-rights-approved", "--auto-topup-disabled"],
        )
        .exit_code
        == 0
    )
    attempt = v.submit(plan_id, "scene-veo", 1, "", setup)
    assert attempt["reservedUsd"] == "1.50"
    assert setup.posts[0][0].endswith("/fast/image-to-video")
    assert setup.posts[0][1]["json"]["image_url"].startswith("data:image/png;base64,")
    with v.database() as db:
        assert "data:image" not in db.execute("SELECT content FROM attempts").fetchone()[0]
    path.write_bytes(b"changed")
    # An existing attempt remains idempotent even when local inputs later disappear.
    assert v.submit(plan_id, "scene-veo", 1, "", setup)["attemptId"] == attempt["attemptId"]


def test_changed_image_fails_before_reservation(setup, tmp_path, monkeypatch):
    m, path = image_manifest(tmp_path, monkeypatch)
    plan = v.prepare(m, setup)["planId"]
    CliRunner().invoke(
        main, ["video", "approve", plan, "--models-and-rights-approved", "--auto-topup-disabled"]
    )
    path.write_bytes(b"changed")
    with pytest.raises(click.ClickException, match="changed"):
        v.submit(plan, "scene-veo", 1, "", setup)
    assert not setup.posts
    with v.database() as db:
        assert v.totals(db)["reservationCents"] == 0


def test_image_reference_must_match_cloud_and_have_bounded_profile(setup, tmp_path, monkeypatch):
    m, _ = image_manifest(tmp_path, monkeypatch)
    monkeypatch.setattr(v.cloud, "api", lambda *a, **kw: {})
    with pytest.raises(click.ClickException, match="immutable Panther"):
        v.prepare(m, setup)
    m["shots"][0]["model"] = "kling-3-pro-image"
    assert "aspect_ratio" not in v.payload(m["shots"][0])
    assert v.payload(m["shots"][0])["start_image_url"] == m["shots"][0]["image"]
    m["shots"][0]["model"] = "veo-3.1-fast"
    with pytest.raises(click.ClickException, match="text profiles forbid"):
        v.validate_manifest(m)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "ROOT", tmp_path / "private-video")
    with v.database(initialize=True):
        pass
    return FakeFal()


def approved(fal):
    plan = v.prepare(manifest(), fal)["planId"]
    result = CliRunner().invoke(
        main, ["video", "approve", plan, "--models-and-rights-approved", "--auto-topup-disabled"]
    )
    assert result.exit_code == 0, result.output
    return plan


def test_prepare_never_generates_and_approval_is_explicit(setup):
    fal = setup
    plan = v.prepare(manifest(), fal)
    assert plan["worstCaseReservationUsd"] == "4.50"
    assert plan["quotes"]["veo-3.1-fast"]["reserveCents"] == 150
    with pytest.raises(click.ClickException, match="not approved"):
        v.submit(plan["planId"], "scene-veo", 1, "", fal)
    assert CliRunner().invoke(main, ["video", "approve", plan["planId"]]).exit_code != 0
    assert fal.posts == []


def test_standalone_comparison_does_not_invent_a_game_session(setup):
    value = manifest()
    value["sessionId"] = None
    assert v.prepare(value, setup)["approved"] is False
    metadata = v.upload_metadata(
        value, "scene-veo", "endpoint", "request", "plan", "attempt", 150, "0" * 64
    )
    assert "sessionId" not in metadata


def test_initialization_never_resets_lifetime_reservations(setup):
    fal = setup
    plan = approved(fal)
    attempt = v.submit(plan, "scene-veo", 1, "", fal)
    with v.database(initialize=True) as db:
        assert v.totals(db)["reservedLifetimeUsd"] == "1.50"
        assert v.totals(db)["actualProviderSpendUsd"] is None
    again = v.submit(plan, "scene-veo", 1, "", fal)
    assert again == attempt and len(fal.posts) == 1
    url, request = fal.posts[0]
    assert url == v.QUEUE + "/fal-ai/veo3.1/fast"
    assert request["json"]["auto_fix"] is False
    assert request["json"]["duration"] == "8s"
    assert request["headers"]["X-Fal-No-Retry"] == "1"
    assert request["headers"]["x-app-fal-disable-fallback"] == "true"


def test_uncertain_submit_holds_funds_and_blocks_duplicates_and_other_requests(setup):
    fal = setup
    plan = approved(fal)
    fal.error = True
    with pytest.raises(click.ClickException, match="Do NOT resubmit"):
        v.submit(plan, "scene-veo", 1, "", fal)
    assert v.submit(plan, "scene-veo", 1, "", fal)["state"] == "UNKNOWN"
    with pytest.raises(click.ClickException, match="outstanding or uncertain"):
        v.submit(plan, "scene-veo", 2, "Another candidate", fal)
    with v.database() as db:
        assert v.totals(db)["reservedLifetimeUsd"] == "1.50"
    assert len(fal.posts) == 1


def test_process_crash_after_reservation_never_resubmits(setup, monkeypatch):
    fal = setup
    plan = approved(fal)
    monkeypatch.setattr(fal, "request", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        v.submit(plan, "scene-veo", 1, "", fal)
    assert v.submit(plan, "scene-veo", 1, "", fal)["state"] == "SUBMITTING"


def test_completion_poll_and_retry_each_keep_the_full_reservation(setup):
    fal = setup
    plan = approved(fal)
    first = v.submit(plan, "scene-veo", 1, "", fal)
    fal.status = "IN_PROGRESS"
    assert v.poll(first["attemptId"], fal)["state"] == "IN_PROGRESS"
    fal.status = "COMPLETED"
    assert v.poll(first["attemptId"], fal)["state"] == "COMPLETED"
    assert v.poll(first["attemptId"], fal)["state"] == "COMPLETED"
    with pytest.raises(click.ClickException, match="explicit reason"):
        v.submit(plan, "scene-veo", 2, "", fal)
    second = v.submit(plan, "scene-veo", 2, "Motion failed the approved acceptance test", fal)
    assert second["attemptId"] != first["attemptId"]
    assert len(fal.posts) == 2
    with v.database() as db:
        assert v.totals(db)["reservedLifetimeUsd"] == "3.00"
    with pytest.raises(click.ClickException, match="not allowed"):
        v.submit(plan, "scene-veo", 4, "Excessive", fal)


def test_concurrent_duplicate_submit_is_sent_once(setup):
    fal = setup
    plan = approved(fal)
    barrier = Barrier(2)
    original = fal.price

    def price(model):
        barrier.wait(timeout=5)
        return original(model)

    fal.price = price
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: v.submit(plan, "scene-veo", 1, "", fal), range(2)))
    assert len(fal.posts) == 1
    assert len({r["attemptId"] for r in results}) == 1


def test_all_plans_share_one_cap_and_all_planned_retries_must_fit(setup):
    fal = setup
    large = manifest()
    large["shots"] = [{**large["shots"][0], "id": f"shot-{i}"} for i in range(20)]
    with pytest.raises(click.ClickException, match="including all retries"):
        v.prepare(large, fal)
    plan = approved(fal)
    # Synthetic historical reservations, not real game or billing data.
    with v.database() as db:
        db.execute("INSERT INTO attempts VALUES ('history','old','old',1,4999,'COMPLETED','{}')")
    with pytest.raises(click.ClickException, match="cannot cover"):
        v.submit(plan, "scene-veo", 1, "", fal)
    assert not fal.posts


@pytest.mark.parametrize("change", ["price", "balance", "account"])
def test_pre_submit_checks_fail_closed(setup, change):
    fal = setup
    plan = approved(fal)
    if change == "price":
        fal.rate = Decimal("9")
    elif change == "balance":
        fal.balance = "6.49"  # Reservation is $1.50; floor is another $5.
    else:
        fal.account = "different-account"
    with pytest.raises(click.ClickException):
        v.submit(plan, "scene-veo", 1, "", fal)
    assert not fal.posts
    with v.database() as db:
        assert v.totals(db)["reservationCents"] == 0


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "not-money", True])
def test_money_fails_closed(bad):
    with pytest.raises(click.ClickException):
        v.number(bad)


def test_manifest_rejects_unbounded_provider_inputs_and_cross_game_sources():
    value = manifest()
    value["shots"][0]["duration"] = 600
    with pytest.raises(click.ClickException):
        v.validate_manifest(value)
    value = manifest()
    value["shots"][0]["model"] = "unknown-compute-model"
    with pytest.raises(click.ClickException):
        v.validate_manifest(value)
    value = manifest()
    value["sourceKeys"] = ["games/other-game/assets/a/original/script.txt"]
    with pytest.raises(click.ClickException):
        v.validate_manifest(value)


def test_foreign_queue_urls_never_receive_credentials(setup):
    endpoint = v.PROFILES["veo-3.1-fast"]["endpoint"]
    for url in [
        "https://evil.invalid/requests/a/status",
        "https://queue.fal.run.evil.invalid/x",
        "https://queue.fal.run/fal-ai/other/requests/a/status",
        "https://queue.fal.run/fal-ai/veo3.1/requests/b/status",
    ]:
        with pytest.raises(click.ClickException):
            v.queue_url(url, "a", endpoint, "status")
    for root in [endpoint, "fal-ai/veo3.1"]:
        url = f"https://queue.fal.run/{root}/requests/a/status"
        assert v.queue_url(url, "a", endpoint, "status") == url


def test_regular_and_admin_keys_are_separate_and_errors_do_not_expose_them(monkeypatch):
    from types import SimpleNamespace

    calls = []

    class Session:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "username": "test",
                    "credits": {"currency": "USD", "current_balance": 50},
                },
            )

        def request(self, method, url, **kwargs):
            calls.append((url, kwargs, dict(self.headers)))
            return SimpleNamespace(status_code=401, json=lambda: {"error": "SYNTHETIC-SECRET"})

    monkeypatch.setattr(
        v.cloud,
        "credential_store",
        lambda: SimpleNamespace(
            get_password=lambda service, account: (
                "SYNTHETIC-ADMIN" if account == "admin-key" else "SYNTHETIC-GENERATION"
            )
        ),
    )
    monkeypatch.setattr(v.requests, "Session", Session)
    fal = v.Fal()
    assert fal.billing()["balanceUsd"] == "50"
    assert calls[0][0] == v.PLATFORM + "/account/billing"
    assert calls[0][1]["headers"]["Authorization"] == "Key SYNTHETIC-ADMIN"
    with pytest.raises(click.ClickException) as error:
        fal.request("POST", v.QUEUE + "/fal-ai/veo3.1/fast")
    assert "SECRET" not in str(error.value)
    assert calls[1][2]["Authorization"] == "Key SYNTHETIC-GENERATION"
    assert calls[1][1]["allow_redirects"] is False


def test_unknown_pricing_units_block_inference(monkeypatch):
    fal = object.__new__(v.Fal)
    monkeypatch.setattr(
        fal,
        "request",
        lambda *a, **k: {
            "prices": [
                {
                    "endpoint_id": v.PROFILES["veo-3.1-fast"]["endpoint"],
                    "unit": "compute seconds",
                    "currency": "USD",
                    "unit_price": 0.01,
                }
            ]
        },
    )
    with pytest.raises(click.ClickException, match="billing units"):
        fal.price("veo-3.1-fast")


@pytest.mark.parametrize("unit", ["seconds", "tokens", "1000 tokens"])
@pytest.mark.parametrize("model", ["seedance-2.0", "seedance-2.0-image"])
def test_seedance_requires_exact_token_unit(monkeypatch, unit, model):
    fal = object.__new__(v.Fal)
    monkeypatch.setattr(
        fal,
        "request",
        lambda *a, **k: {
            "prices": [
                {
                    "endpoint_id": v.PROFILES[model]["endpoint"],
                    "unit": unit,
                    "currency": "USD",
                    "unit_price": "0.014",
                }
            ]
        },
    )
    if unit == "1000 tokens":
        assert fal.price(model) == Decimal("0.014")
    else:
        with pytest.raises(click.ClickException, match="billing units"):
            fal.price(model)


def test_seedance_image_fixed_payload_and_shared_guard(setup, tmp_path, monkeypatch):
    m, path = image_manifest(tmp_path, monkeypatch)
    m["sessionId"] = None
    m["shots"][0]["model"] = "seedance-2.0-image"
    setup.rate = Decimal("0.014")
    quote = v.quote(setup, "seedance-2.0-image")
    assert quote["estimatedTokens"] == 172800
    assert quote["reserveCents"] == 304
    plan = v.prepare(m, setup)["planId"]
    with pytest.raises(click.ClickException, match="approv"):
        v.submit(plan, "scene-veo", 1, "", setup)
    assert not setup.posts
    assert (
        CliRunner()
        .invoke(
            main,
            ["video", "approve", plan, "--models-and-rights-approved", "--auto-topup-disabled"],
        )
        .exit_code
        == 0
    )
    original = path.read_bytes()
    path.write_bytes(b"changed")
    with pytest.raises(click.ClickException, match="changed"):
        v.submit(plan, "scene-veo", 1, "", setup)
    path.write_bytes(original)
    setup.rate = Decimal("0.02")
    with pytest.raises(click.ClickException, match="Pricing increased"):
        v.submit(plan, "scene-veo", 1, "", setup)
    setup.rate = Decimal("0.014")
    with v.database() as db:
        assert v.totals(db)["reservationCents"] == 0
    attempt = v.submit(plan, "scene-veo", 1, "", setup)
    assert attempt["reservedUsd"] == "3.04"
    assert v.submit(plan, "scene-veo", 1, "", setup) == attempt
    assert len(setup.posts) == 1
    assert setup.posts[0][0] == v.QUEUE + "/bytedance/seedance-2.0/image-to-video"
    assert setup.posts[0][1]["json"] == {
        "prompt": "A fictional harbor at dusk.",
        "duration": "8",
        "resolution": "720p",
        "aspect_ratio": "16:9",
        "generate_audio": True,
        "bitrate_mode": "standard",
        "image_url": "data:image/png;base64," + base64.b64encode(original).decode(),
    }
    v.poll(attempt["attemptId"], setup)
    with pytest.raises(click.ClickException, match="not allowed"):
        v.submit(plan, "scene-veo", 2, "No extra attempt authorized", setup)
    with v.database() as db:
        assert v.totals(db)["reservedLifetimeUsd"] == "3.04"
        assert "data:image" not in db.execute("SELECT content FROM attempts").fetchone()[0]


def test_seedance_token_quote_fixed_payload_and_durable_budget(setup):
    fal = setup
    fal.rate = Decimal("0.014")
    quote = v.quote(fal, "seedance-2.0")
    assert quote["estimatedTokens"] == 172800
    assert quote["conservativeEstimateUsd"] == "2.4272"
    assert quote["reserveCents"] == 304
    assert quote["unit"] == "1000 tokens"
    value = manifest()
    value["shots"][0].update(model="seedance-2.0", maxAttempts=1)
    plan = v.prepare(value, fal)["planId"]
    result = CliRunner().invoke(
        main, ["video", "approve", plan, "--models-and-rights-approved", "--auto-topup-disabled"]
    )
    assert result.exit_code == 0
    fal.rate = Decimal("0.02")
    with pytest.raises(click.ClickException, match="Pricing increased"):
        v.submit(plan, "scene-veo", 1, "", fal)
    assert not fal.posts
    fal.rate = Decimal("0.014")
    attempt = v.submit(plan, "scene-veo", 1, "", fal)
    assert v.submit(plan, "scene-veo", 1, "", fal) == attempt
    assert len(fal.posts) == 1
    assert fal.posts[0][0] == v.QUEUE + "/bytedance/seedance-2.0/text-to-video"
    assert fal.posts[0][1]["json"] == {
        "prompt": "A fictional harbor at dusk.",
        "duration": "8",
        "resolution": "720p",
        "aspect_ratio": "16:9",
        "generate_audio": True,
        "bitrate_mode": "standard",
    }
    v.poll(attempt["attemptId"], fal)
    with v.database() as db:
        assert v.totals(db)["reservedLifetimeUsd"] == "3.04"
    with pytest.raises(click.ClickException, match="not allowed"):
        v.submit(plan, "scene-veo", 2, "No retries authorized", fal)


def test_plan_integrity_and_adapter_settings_are_pinned(setup, monkeypatch):
    fal = setup
    plan = approved(fal)
    monkeypatch.setattr(v, "payload", lambda shot: {"duration": "600s"})
    with pytest.raises(click.ClickException, match="adapter changed"):
        v.submit(plan, "scene-veo", 1, "", fal)
    with v.database() as db:
        original = json.loads(
            db.execute("SELECT content FROM plans WHERE id=?", (plan,)).fetchone()[0]
        )
        original["manifest"]["shots"][0]["prompt"] = "Unexpected changed prompt"
        db.execute("UPDATE plans SET content=? WHERE id=?", (v.canonical(original), plan))
    with pytest.raises(click.ClickException, match="Pinned plan changed"):
        v.submit(plan, "scene-veo", 1, "", fal)
    assert not fal.posts


@pytest.mark.parametrize(
    "url",
    [
        "http://fal.media/a",
        "https://evil.invalid/a.mp4",
        "https://fal.media.evil.invalid/a",
        "https://user@fal.media/a",
        "https://storage.googleapis.com/private-other/a.mp4",
    ],
)
def test_media_delivery_host_allowlist(url):
    with pytest.raises(click.ClickException):
        v.media_url(url)


def test_download_preserves_original_and_writes_upload_metadata_without_credentials(
    setup, monkeypatch
):
    fal = setup
    plan = approved(fal)
    attempt = v.submit(plan, "scene-veo", 1, "", fal)
    v.poll(attempt["attemptId"], fal)
    calls = []

    class Response:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_content(self, size):
            yield b"\x00\x00\x00\x18ftypisomSynthetic"

    class Session(Response):
        def get(self, url, **kwargs):
            calls.append(kwargs)
            return Response()

    monkeypatch.setattr(v.requests, "Session", Session)
    result = v.download(attempt["attemptId"])
    assert result["downloadPath"].endswith(".mp4")
    metadata = json.loads(next((v.ROOT / "outputs").glob("*.metadata.json")).read_text())
    assert metadata["category"] == "creative-reimagining"
    assert metadata["extra"]["reviewStatus"] == "unreviewed"
    assert "schemaVersion" not in metadata  # Added by the server, not accepted in upload input.
    assert len(v.canonical(metadata).encode()) <= 1100
    assert "headers" not in calls[0] and not calls[0]["allow_redirects"]
    with pytest.raises(click.ClickException, match="already exists"):
        v.download(attempt["attemptId"])
