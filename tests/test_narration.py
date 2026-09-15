import json
from decimal import Decimal

import click
from click.testing import CliRunner
import pytest

from panther_journal import narration as n, video as v
from panther_journal.cli import main


class FakeFal:
    def __init__(self):
        self.rate = "0.10"
        self.account = "synthetic-account"
        self.balance = "50"
        self.posts = []
        self.uncertain = False
        self.unit = "1000 characters"

    def billing(self):
        return dict(account=self.account, balanceUsd=self.balance)

    def request(self, method, url, **kwargs):
        if url.endswith("/models/pricing"):
            return {
                "prices": [
                    dict(
                        endpoint_id=n.ENDPOINT, currency="USD", unit=self.unit, unit_price=self.rate
                    )
                ]
            }
        if method == "POST":
            self.posts.append(kwargs)
            if self.uncertain:
                raise click.ClickException("Unknown result")
            root = url + "/requests/fake-request"
            return dict(
                request_id="fake-request",
                status_url=root + "/status",
                response_url=root,
                cancel_url=root + "/cancel",
            )
        if url.endswith("/status"):
            return dict(status="COMPLETED", request_id="fake-request")
        return dict(audio={"url": "https://v3.fal.media/sample.mp3"})

    def price(self, model):
        return Decimal("0.15")


@pytest.fixture
def fal(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "ROOT", tmp_path / "private")
    with v.database(initialize=True):
        pass
    f = FakeFal()
    n.create_budget("test-film", "test-game", "15", "13.48", "Synthetic owner approval", f)
    return f


def manifest():
    return dict(
        schemaVersion=1,
        gameId="test-game",
        projectId="test-film",
        purpose="audition",
        text="[dramatic] Tonight, the sea comes to collect.",
        voice="Bill",
        direction="Resonant, ominous, restrained trailer performance.",
        sourceKeys=["games/test-game/assets/script/original/script.json"],
    )


def approved(fal, m=None):
    p = n.prepare(m or manifest(), fal)
    result = CliRunner().invoke(
        main,
        [
            "narration",
            "approve",
            p["planId"],
            "--text-voice-rights-approved",
            "--auto-topup-disabled",
        ],
    )
    assert result.exit_code == 0, result.output
    return p["planId"]


def test_premium_payload_quotes_and_idempotent_submission(fal):
    p = n.prepare(manifest(), fal)
    assert not fal.posts
    with pytest.raises(click.ClickException, match="Approve"):
        n.submit(p["planId"], fal)
    pid = approved(fal)
    first = n.submit(pid, fal)
    assert first["state"] == "SUBMITTED"
    assert n.submit(pid, fal) == first
    assert len(fal.posts) == 1
    assert fal.posts[0]["json"] == dict(
        text=manifest()["text"],
        voice="Bill",
        stability=0.5,
        timestamps=True,
        language_code="en",
        apply_text_normalization="auto",
    )
    assert fal.posts[0]["headers"]["X-Fal-No-Retry"] == "1"
    assert n.poll(first["attemptId"], fal)["state"] == "COMPLETED"
    with v.database() as db:
        assert v.totals(db)["reservationCents"] == 0  # Historical comparison allocation unchanged.
        assert n.budget_status(db, "test-film")["narrationReservedCents"] > 0


@pytest.mark.parametrize("change", ["units", "price", "account", "balance"])
def test_provider_changes_fail_before_post(fal, change):
    pid = approved(fal)
    if change == "units":
        fal.unit = "seconds"
    if change == "price":
        fal.rate = "9"
    if change == "account":
        fal.account = "different-account"
    if change == "balance":
        fal.balance = "18.48"
    with pytest.raises(click.ClickException):
        n.submit(pid, fal)
    assert not fal.posts


def test_uncertainty_blocks_all_generation_and_preserves_reservation(fal):
    pid = approved(fal)
    fal.uncertain = True
    with pytest.raises(click.ClickException, match="Uncertain"):
        n.submit(pid, fal)
    old = n.submit(pid, fal)
    assert old["state"] == "UNKNOWN"
    assert len(fal.posts) == 1
    with v.database() as db:
        assert v.has_unresolved(db)
        before = n.budget_status(db, "test-film")
    new = manifest()
    new["text"] += " A different take."
    other = approved(fal, new)
    with pytest.raises(click.ClickException, match="outstanding"):
        n.submit(other, fal)
    assert len(fal.posts) == 1
    with v.database() as db:
        assert n.budget_status(db, "test-film") == before


def test_budget_is_create_only_and_protects_other_media(fal):
    with v.database() as db:
        before = n.budget_status(db, "test-film")
    assert (
        n.create_budget("test-film", "test-game", "15", "13.48", "Synthetic owner approval", fal)
        == before
    )
    with pytest.raises(click.ClickException, match="already exists"):
        n.create_budget("test-film", "test-game", "16", "13.48", "Synthetic owner approval", fal)
    n.create_budget("tiny-project", "test-game", ".02", ".01", "Synthetic tiny allocation", fal)
    m = manifest()
    m["projectId"] = "tiny-project"
    m["text"] = "x" * 600
    with pytest.raises(click.ClickException, match="protected"):
        n.prepare(m, fal)
    assert not fal.posts


def test_full_narration_requires_matching_accepted_audition(fal):
    m = manifest()
    m.update(purpose="production", approvedAudition="a" * 64)
    with pytest.raises(click.ClickException, match="not been accepted"):
        n.prepare(m, fal)
    aid = n.submit(approved(fal), fal)["attemptId"]
    n.poll(aid, fal)
    n.update(aid, "COMPLETED", {"downloadPath": "/private/synthetic-audition.mp3"})
    result = CliRunner().invoke(main, ["narration", "accept-voice", aid, "--owner-approved"])
    assert result.exit_code == 0, result.output
    m["approvedAudition"] = aid
    assert n.prepare(m, fal)["approved"] is False
    m["voice"] = "George"
    with pytest.raises(click.ClickException, match="match"):
        n.prepare(m, fal)


@pytest.mark.parametrize(
    "change",
    [
        dict(voice="Chatterbox"),
        dict(voice="Daniel"),
        dict(voice="arbitrary-clone-id"),
        dict(text="x" * 601),
        dict(ref_audio="secret.wav"),
        dict(sourceKeys=["games/other-game/assets/a/original/a.json"]),
        dict(purpose="fallback"),
    ],
)
def test_reject_unapproved_voices_or_arguments(fal, change):
    with pytest.raises(click.ClickException):
        n.prepare({**manifest(), **change}, fal)
    assert not fal.posts


def test_plan_tampering(fal):
    pid = approved(fal)
    with v.database() as db:
        p, _ = n.read_plan(db, pid)
        p["input"]["voice"] = "George"
        db.execute("UPDATE narration_plans SET content=? WHERE id=?", (json.dumps(p), pid))
    with pytest.raises(click.ClickException, match="changed"):
        n.submit(pid, fal)
    assert not fal.posts


def test_video_and_narration_share_uncertain_request_lock(fal):
    from test_video import manifest as video_manifest

    vp = v.prepare(video_manifest(), fal)["planId"]
    with v.database() as db:
        db.execute("UPDATE plans SET approved=1 WHERE id=?", (vp,))
    aid = n.submit(approved(fal), fal)["attemptId"]
    with pytest.raises(click.ClickException, match="outstanding"):
        v.submit(vp, "scene-veo", 1, "", fal)
    assert len(fal.posts) == 1
    n.poll(aid, fal)
    v.submit(vp, "scene-veo", 1, "", fal)
    second = manifest()
    second["text"] += " Another line."
    with pytest.raises(click.ClickException, match="outstanding"):
        n.submit(approved(fal, second), fal)
    assert len(fal.posts) == 2


def test_download_is_unauthenticated_preserves_bytes_and_records_billing(fal, monkeypatch):
    aid = n.submit(approved(fal), fal)["attemptId"]
    n.poll(aid, fal)
    content = b"ID3" + bytes(300)

    class Response:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_content(self, size):
            yield content

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            assert url == "https://v3.fal.media/sample.mp3"
            assert kwargs["allow_redirects"] is False
            assert "headers" not in kwargs and not hasattr(self, "headers")
            return Response()

    monkeypatch.setattr(n.requests, "Session", Session)
    monkeypatch.setattr(
        fal,
        "billing_events",
        lambda ids: {"fake-request": {"endpoint": n.ENDPOINT, "amount": ".004"}},
        raising=False,
    )
    result = n.download(aid, fal)
    from pathlib import Path

    path = Path(result["downloadPath"])
    assert path.read_bytes() == content
    metadata = json.loads(path.with_suffix(".metadata.json").read_text())
    assert metadata["extra"]["generation"]["cost"]["status"] == "billed"
    assert metadata["extra"]["generation"]["inference"] == "remote"
    with pytest.raises(click.ClickException, match="Original exists"):
        n.download(aid, fal)


def test_voice_policy_is_shipped_and_model_metadata_is_exact():
    from importlib.resources import files
    from panther_journal.editorial_contract import BRIEFS

    instructions = files("panther_journal").joinpath("agent-instructions.md").read_text()
    assert "Never use Chatterbox" in instructions
    assert "Never propose Chatterbox" in BRIEFS["video-voice-casting"]
    assert n.ENDPOINT in {"fal-ai/elevenlabs/tts/eleven-v3"}
    assert n.generation.fal(n.ENDPOINT, "synthetic-request")["model"] == "ElevenLabs Eleven v3"
