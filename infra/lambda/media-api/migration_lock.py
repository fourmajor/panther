"""Fail-closed migration mutex: uncertain executions never expire or steal a lock."""

from contextlib import contextmanager
from datetime import datetime, timezone
import os
import uuid

import boto3


@contextmanager
def exclusive():
    table = boto3.resource("dynamodb").Table(os.environ["MIGRATION_LOCK_TABLE"])
    owner = uuid.uuid4().hex
    table.put_item(Item={"pk": "asset-migration", "owner": owner,
                         "startedAt": datetime.now(timezone.utc).isoformat()},
                   ConditionExpression="attribute_not_exists(pk)")
    state = {"complete": False}
    try:
        yield state
    finally:
        # Timeouts, unexpected errors and ambiguous upstream failures retain the lock.
        # There is deliberately no TTL or automatic recovery/lease stealing.
        if state["complete"]:
            table.delete_item(Key={"pk": "asset-migration"},
                              ConditionExpression="#owner = :owner",
                              ExpressionAttributeNames={"#owner": "owner"},
                              ExpressionAttributeValues={":owner": owner})
