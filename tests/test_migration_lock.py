import importlib
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws
import pytest


@pytest.fixture
def lock(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "infra/lambda/media-api"))
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("MIGRATION_LOCK_TABLE", "migration-lock")
    monkeypatch.delitem(sys.modules, "migration_lock", raising=False)
    with mock_aws():
        table = boto3.resource("dynamodb").create_table(
            TableName="migration-lock", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}])
        yield importlib.import_module("migration_lock"), table


def test_contention_and_completed_release(lock):
    module, table = lock
    with module.exclusive() as state:
        with pytest.raises(ClientError, match="ConditionalCheckFailed"):
            with module.exclusive():
                pytest.fail("Concurrent owner acquired the lock")
        assert table.get_item(Key={"pk": "asset-migration"})["Item"]["owner"]
        state["complete"] = True
    assert "Item" not in table.get_item(Key={"pk": "asset-migration"})
    with module.exclusive() as state:
        state["complete"] = True


@pytest.mark.parametrize("crash", [False, True])
def test_uncertain_operation_retains_lock_without_expiration(lock, crash):
    module, table = lock
    try:
        with module.exclusive():
            if crash:
                raise RuntimeError("interrupted")
    except RuntimeError:
        pass
    item = table.get_item(Key={"pk": "asset-migration"})["Item"]
    assert set(item) == {"pk", "owner", "startedAt"}
    with pytest.raises(ClientError, match="ConditionalCheckFailed"):
        with module.exclusive():
            pytest.fail("An uncertain lock must not be stolen")


def test_release_cannot_remove_another_owner(lock):
    module, table = lock
    with pytest.raises(ClientError, match="ConditionalCheckFailed"):
        with module.exclusive() as state:
            table.put_item(Item={"pk": "asset-migration", "owner": "replacement"})
            state["complete"] = True
    assert table.get_item(Key={"pk": "asset-migration"})["Item"]["owner"] == "replacement"
