"""Catalog range reads use one DynamoDB condition per key."""

import json
import os
import sys
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).parents[1] / "infra/lambda/media-api"))

import browse_index  # noqa: E402

GAME = "curse-of-the-crimson-throne"


def test_a_range_has_one_condition_per_key():
    condition = browse_index.range_condition("partition", "games/example/assets/a")
    assert browse_index.comparison_counts(condition) == {"pk": 1, "sk": 1}
    two_bounds = Key("pk").eq("partition") & Key("sk").gte("a") & Key("sk").lt("b")
    assert browse_index.comparison_counts(two_bounds) == {"pk": 1, "sk": 2}


@mock_aws
def test_gather_reads_every_range_and_keeps_a_partial_failure(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("ASSET_BROWSE_TABLE", "panther-browse")
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    table = boto3.resource("dynamodb", region_name="us-west-2").create_table(
        TableName="panther-browse",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    pk = browse_index.partition(GAME, "all")
    table.put_item(Item={"pk": f"v{browse_index.VERSION}#catalog", "sk": "ready"})
    keys = [
        f"games/{GAME}/assets/audio-copy/original/listen.mp3",
        f"games/{GAME}/assets/preview-still/original/still.jpg",
        f"games/{GAME}/assets/zebra-note/original/note.json",
    ]
    for key in keys:
        table.put_item(Item={"pk": pk, "sk": key, "payload": json.dumps({"key": key, "kind": "video-preview"})})
    assets, complete = browse_index.gather(GAME, "all", consistent=False)
    assert complete is True
    assert {item["key"] for item in assets} == set(keys)

    real_query = table.query

    def fail_one(**args):
        start = args["KeyConditionExpression"].get_expression()["values"][1].get_expression()["values"][1]
        if str(start).endswith("/assets/p"):
            raise ClientError({"Error": {"Code": "InternalServerError", "Message": "busy"}}, "Query")
        return real_query(**args)

    monkeypatch.setattr(browse_index, "table", lambda: table)
    monkeypatch.setattr(table, "query", fail_one)
    partial, done = browse_index.gather(GAME, "all", consistent=False)
    assert done is False
    assert partial
    assert {item["key"] for item in partial} < set(keys)
