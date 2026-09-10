import copy
import importlib.util
from pathlib import Path

import pytest

from panther_journal import generation_metadata as g
from panther_journal.asset_migrations import generation_plan

spec = importlib.util.spec_from_file_location("generation_validator", Path(__file__).parents[1] / "infra/lambda/media-api/asset_metadata.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


@pytest.mark.parametrize("value", [g.unknown(), g.subscription(), g.subscription("Codex CLI + Blender"),
    g.local("FFmpeg"), g.local("whisper.cpp", method="ai"), g.fal("fal-ai/veo3.1/fast", "request", "1.20")])
def test_producers_match_server_contract(value):
    assert validator.validate_generation(value) == value


@pytest.mark.parametrize("cost", [
    {"status": "billed", "amount": "NaN", "currency": "USD"},
    {"status": "estimated", "amount": "-1", "currency": "USD"},
    {"status": "billed", "amount": 1.2, "currency": "USD"},
    {"status": "billed", "amount": "1.2", "currency": "usd"},
    {"status": "unknown", "amount": "0", "currency": "USD"},
    {"status": "subscription", "amount": "0", "currency": "USD"},
    {"status": "reserved", "amount": "2.10", "currency": "USD"},
])
def test_never_confuse_unknown_subscription_or_reservation_with_charge(cost):
    with pytest.raises(ValueError):
        validator.validate_generation({**g.unknown(), "cost": cost})


def test_billed_zero_is_supported_only_with_evidence():
    value = g.fal("fal-ai/veo3.1/fast", "failed-request", "0")
    validator.validate_generation(value)
    del value["evidence"]
    with pytest.raises(ValueError):
        validator.validate_generation(value)


@pytest.mark.parametrize("patch", [{"method": []}, {"inference": {}}, {"execution": []},
    {"cost": {"status": []}}, {"schemaVersion": True}])
def test_malformed_generation_is_rejected_as_validation_error(patch):
    with pytest.raises(ValueError):
        validator.validate_generation({**g.unknown(), **patch})


def test_all_kinds_receive_explicit_unknown_without_guessing():
    for kind in ("portrait", "video-comparison", "new-kind", "raw-transcript"):
        metadata = validator.defaults(kind, {"extra": {"provider": "something"}}, "asset.png", "image/png")
        assert metadata["extra"]["generation"] == g.unknown()


def test_repeatable_backfill_preserves_known_facts_lineage_and_does_not_mutate_inputs():
    records = [{"key": "games/test/assets/one/original/x.png", "kind": "portrait", "versionId": "pin",
                "metadata": {"title": "X", "sourceKeys": ["source"], "extra": {"generator": "original"}}}]
    before = copy.deepcopy(records)
    plan = generation_plan(records, {})
    assert records == before
    entry = plan["migrations"][0]
    assert entry["expectedVersionId"] == "pin"
    assert entry["metadata"]["sourceKeys"] == ["source"]
    assert entry["metadata"]["extra"]["generator"] == "original"
    records[0]["metadata"] = entry["metadata"]
    assert not generation_plan(records, {})["migrations"]
    known = g.subscription()
    assert generation_plan(records, {records[0]["key"]: known})["migrations"][0]["metadata"]["extra"]["generation"] == known
