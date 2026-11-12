import importlib
import json
import sys
import time
from pathlib import Path

import boto3
from moto import mock_aws


def _table(name):
    boto3.client("dynamodb").create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
    )


def test_watch_alerts_once_for_a_stalled_task_and_again_when_a_heartbeat_expires(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("WORKSHOP_TABLE", "test-workshop")
    monkeypatch.setenv("TOPIC_ARN", "arn:aws:sns:us-west-2:123456789012:alerts")
    monkeypatch.setenv("STALE_SECONDS", "1200")
    monkeypatch.setenv(
        "JOB_TABLES",
        json.dumps({"editorial": "test-editorial", "model": "test-model", "playback": "test-playback"}),
    )
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "infra/lambda/media-api"))
    with mock_aws():
        for name in ("test-workshop", "test-editorial", "test-model", "test-playback"):
            _table(name)
        monkeypatch.delitem(sys.modules, "pipeline_watch", raising=False)
        watch = importlib.import_module("pipeline_watch")
        published = []
        monkeypatch.setattr(watch, "publish", published.append)
        now = int(time.time())
        for name in ("editorial", "playback", "model"):
            watch.INDEX.put_item(Item={
                "pk": "SYSTEM", "sk": "worker#" + name, "worker": name, "seenAt": now, "status": "ready",
            })
        boto3.resource("dynamodb").Table("test-editorial").put_item(Item={
            "pk": "TASKS",
            "sk": "a" * 64 + ":corrected-transcript",
            "jobId": "a" * 64,
            "status": "QUEUED",
            "queuedAt": now - 1300,
        })
        assert watch.handler(None, None) == {"alerts": 1}
        assert "without an active worker" in published[0]
        assert "sign-in expired" not in published[0]
        assert watch.handler(None, None) == {"alerts": 1}
        assert len(published) == 1
        watch.INDEX.put_item(Item={
            "pk": "SYSTEM", "sk": "worker#editorial", "worker": "editorial",
            "seenAt": now - 1300, "status": "ready",
        })
        assert watch.handler(None, None)["alerts"] == 2
        assert "editorial worker offline" in published[-1]
        assert "sign-in expired" in published[-1]
        assert len(published) == 2
        # The offline notice is one-shot, so the next message is only the stalled task.
        assert watch.handler(None, None)["alerts"] == 1
        assert published[-1].startswith("editorial aaaaaaaaaaaaaaaa")
        assert len(published) == 3
        assert watch.handler(None, None)["alerts"] == 1
        assert len(published) == 3
