import copy

import click
import pytest

from panther_journal.asset_migrations import model_output_plan
from panther_journal.model_workflow import VIEWS


def inventory(status="FAILED"):
    prefix = "games/example-game/assets/"
    job = {
        "jobId": "a" * 64,
        "gameId": "example-game",
        "status": status,
        "views": {v: {"key": f"{prefix}refs/original/{v}.png"} for v in VIEWS},
    }
    refs = [{"key": x["key"], "metadata": {}} for x in job["views"].values()]
    output = {
        "key": f"{prefix}model-job-{'a' * 32}-2/original/model.glb",
        "versionId": "exact-version",
        "kind": "model-3d",
        "metadata": {
            "title": "Model",
            "sourceKeys": [refs[0]["key"]],
            "extra": {"jobId": job["jobId"], "version": {"number": 2}},
        },
    }
    input_key = f"{prefix}model-inputs-{'a' * 32}/original/inputs.json"
    return [
        *refs,
        {"key": input_key, "metadata": {"extra": {"modelInputManifest": True}}},
        output,
    ], job


@pytest.mark.parametrize(
    "status,role",
    [("FAILED", "intermediate"), ("RUNNING", "intermediate"), ("PUBLISHED", "finished")],
)
def test_model_backfill_uses_exact_job_inputs_and_publication_status(status, role):
    records, job = inventory(status)
    before = copy.deepcopy(records)
    input_key = records[-2]["key"]
    plan = model_output_plan(records, [job], {job["jobId"]: input_key})
    edit = plan["migrations"][0]
    assert edit["expectedVersionId"] == "exact-version"
    assert edit["metadata"]["sourceKeys"] == [job["views"]["front"]["key"], input_key]
    assert edit["metadata"]["extra"]["relationshipRole"] == role
    assert edit["metadata"]["extra"]["version"] == {"number": 2}
    assert records == before
    records[-1]["metadata"] = edit["metadata"]
    assert model_output_plan(records, [job], {job["jobId"]: input_key})["migrations"] == []


def test_model_backfill_blocks_unknown_identity_and_missing_reference():
    records, job = inventory()
    with pytest.raises(click.ClickException, match="recorded job"):
        model_output_plan(records, [], {})
    with pytest.raises(click.ClickException, match="incomplete or crosses"):
        model_output_plan(records[1:], [job], {})
    del records[-1]["metadata"]["extra"]["jobId"]
    with pytest.raises(click.ClickException, match="explicit job identity"):
        model_output_plan(records, [job], {})
