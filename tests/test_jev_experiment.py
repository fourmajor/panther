"""Protocol simulations only. These are not Jev inference results."""

import copy
import json

import pytest

from panther_journal import jev_experiment as experiment


def captures():
    result = []
    for case in experiment.CASES:
        levels = experiment.request(case)["questions"]["support"]["criteria"]
        result.append(
            {
                "caseId": case[0],
                "requestSha256": experiment.fingerprint(experiment.request(case)),
                "latencyMs": 12,
                "response": {
                    "model": "typesafe/jev-1.13-20260917",
                    "provider": "TypeSafe",
                    "usage": {"input_tokens": 100, "cost": 0.0000042},
                    "answers": {
                        "decision": {
                            "type": "choice",
                            "choice": case[3],
                            "confidence": 1,
                            "probabilities": {
                                label: int(label == case[3])
                                for label in experiment.CRITERIA[case[1]]
                            },
                        },
                        "ambiguity": {"type": "noul", "noul": int(case[3] == "uncertain")},
                        "support": {
                            "type": "score",
                            "score": 2,
                            "confidence": 1,
                            "probabilities": {"0": 0, "1": 0, "2": 1},
                            "legend": {str(i): text for i, text in enumerate(levels)},
                        },
                    },
                },
            }
        )
    return result


def test_prepare_is_synthetic_only_and_never_includes_gold_labels(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["jev_experiment", "prepare"])
    experiment.main()
    output = json.loads(capsys.readouterr().out)
    assert output["networkEnabled"] is False and len(output["requests"]) == 12
    for item in output["requests"]:
        assert set(item) == {"caseId", "requestSha256", "request"}
        assert item["request"]["provider"]["allow_fallbacks"] is False
        assert item["request"]["provider"]["only"] == ["typesafe"]
        assert set(item["request"]["questions"]) == {"decision", "support", "ambiguity"}
    # No credential or network module is imported by this standalone experiment.
    import inspect

    source = inspect.getsource(experiment)
    assert (
        "import requests" not in source
        and "import http" not in source
        and "import os" not in source
    )


def test_valid_simulations_score_per_task_and_do_not_claim_adoption():
    report = experiment.evaluate(captures())
    assert set(report["metrics"]) == set(experiment.CRITERIA)
    assert all(m["accuracy"] == 1 and m["multiclassBrier"] == 0 for m in report["metrics"].values())
    assert report["metrics"]["link"]["coverage"] == 0.5
    assert "defer" in report["recommendation"] and "synthetic" in report["scope"]


@pytest.mark.parametrize(
    "fault",
    [
        "model",
        "provider",
        "options",
        "probability",
        "confidence",
        "noul",
        "score",
        "legend",
        "fingerprint",
        "missing",
        "duplicate",
        "mixed-version",
        "cost",
    ],
)
def test_incompatible_or_unpinned_responses_fail_closed(fault):
    rows = captures()
    response = rows[0]["response"]
    choice = response["answers"]["decision"]
    if fault == "model":
        response["model"] = "~typesafe/jev-latest"
    if fault == "provider":
        response["provider"] = "AnotherProvider"
    if fault == "options":
        choice["probabilities"]["new-entity"] = 0
    if fault == "probability":
        choice["probabilities"][choice["choice"]] = 0.8
    if fault == "confidence":
        choice["confidence"] = True
    if fault == "noul":
        response["answers"]["ambiguity"]["noul"] = float("nan")
    if fault == "score":
        response["answers"]["support"]["score"] = 1
    if fault == "legend":
        response["answers"]["support"]["legend"]["2"] = "Changed scale"
    if fault == "fingerprint":
        rows[0]["requestSha256"] = "0" * 64
    if fault == "missing":
        rows.pop()
    if fault == "duplicate":
        rows[-1] = copy.deepcopy(rows[0])
    if fault == "mixed-version":
        rows[-1]["response"]["model"] = experiment.MODEL
    if fault == "cost":
        response["usage"]["cost"] = -1
    with pytest.raises(ValueError):
        experiment.evaluate(rows)


def test_low_confidence_abstains_and_missing_cost_stays_unknown():
    rows = captures()
    rows[0]["response"]["answers"]["decision"]["confidence"] = 0.4
    rows[0]["response"]["usage"].pop("cost")
    report = experiment.evaluate(rows)
    assert report["metrics"]["utterance"]["coverage"] == 0.5
    assert report["cost"]["status"] == "incomplete" and report["cost"]["missingResponses"] == 1


def test_score_cli_reads_captures_only_and_outputs_no_text(tmp_path, monkeypatch, capsys):
    path = tmp_path / "simulated.json"
    path.write_text(json.dumps(captures()))
    monkeypatch.setattr("sys.argv", ["jev_experiment", "score", str(path)])
    experiment.main()
    report = json.loads(capsys.readouterr().out)
    assert "requests" not in report and "answers" not in report
