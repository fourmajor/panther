"""Structured group catalog. Players are people, not login accounts or characters."""

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError
import index as media

table = boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"])
serializer = TypeSerializer()
EDITORS = set(os.environ.get("CATALOG_EDITORS", "").split(","))


def clean(record):
    return {
        k: int(v) if isinstance(v, Decimal) else v
        for k, v in record.items()
        if k not in {"pk", "sk", "fingerprint"}
    }


def read(pk, sk):
    return table.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item")


def query(pk):
    args = {"KeyConditionExpression": Key("pk").eq(pk), "ConsistentRead": True}
    items = []
    while True:
        result = table.query(**args)
        items.extend(result.get("Items", []))
        if "LastEvaluatedKey" not in result:
            return items
        args["ExclusiveStartKey"] = result["LastEvaluatedKey"]


def identifier(value):
    if not media._valid_slug(value) or len(value) > 96:
        raise ValueError("Invalid identifier")
    return value


def name(value):
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= 120:
        raise ValueError("Names must contain 1–120 characters without surrounding whitespace")
    if any(ord(c) < 32 for c in value):
        raise ValueError("Invalid name")
    return value


def validate(body):
    if not isinstance(body, dict) or set(body) != {
        "id",
        "name",
        "purpose",
        "players",
        "characters",
        "memberships",
    }:
        raise ValueError("Expected id, name, purpose, players, characters, memberships")
    identifier(body["id"])
    name(body["name"])
    if body["purpose"] not in ("test", "campaign"):
        raise ValueError("Purpose must be test or campaign")
    for field in ("players", "characters", "memberships"):
        if not isinstance(body[field], list) or len(body[field]) > 20:
            raise ValueError("At most twenty entries per collection")
    players, characters = {}, {}
    for field, target in (("players", players), ("characters", characters)):
        for item in body[field]:
            if not isinstance(item, dict) or set(item) != {"id", "name"}:
                raise ValueError("Players and characters require id and name")
            identifier(item["id"])
            name(item["name"])
            if item["id"] in target:
                raise ValueError("Duplicate identifier")
            target[item["id"]] = item
    seen = set()
    for member in body["memberships"]:
        if not isinstance(member, dict) or set(member) != {"playerId", "role", "characterIds"}:
            raise ValueError("Membership requires playerId, role, characterIds")
        if (
            not isinstance(member["playerId"], str)
            or member["playerId"] not in players
            or member["playerId"] in seen
        ):
            raise ValueError("Membership must reference a distinct player")
        seen.add(member["playerId"])
        if member["role"] not in ("player", "dungeon-master"):
            raise ValueError("Invalid game role")
        ids = member["characterIds"]
        if (
            not isinstance(ids, list)
            or not all(isinstance(i, str) and i in characters for i in ids)
            or len(ids) != len(set(ids))
        ):
            raise ValueError("Membership references unknown or duplicate characters")
        if member["role"] == "dungeon-master" and ids:
            raise ValueError("Dungeon Master is a game role, not a character")
    if seen != set(players):
        raise ValueError("Every supplied player needs a membership")


def games():
    found = {r["id"]: clean(r) for r in query("GAMES")}
    # Discover pre-catalog games without moving assets or inventing roster records.
    pages = media.s3.get_paginator("list_objects_v2").paginate(
        Bucket=media.BUCKET_NAME, Prefix="games/", Delimiter="/"
    )
    for page in pages:
        for entry in page.get("CommonPrefixes", []):
            game_id = entry["Prefix"].split("/")[1]
            if media._valid_slug(game_id):
                found.setdefault(
                    game_id,
                    {
                        "entityType": "Game",
                        "id": game_id,
                        "name": game_id.replace("-", " ").title(),
                        "purpose": "campaign",
                        "legacy": True,
                    },
                )
    return sorted(found.values(), key=lambda g: (g["purpose"] == "test", g["name"].casefold()))


def detail(game_id):
    identifier(game_id)
    game = read("GAMES", game_id)
    if not game:
        game = next((g for g in games() if g["id"] == game_id), None)
    if not game:
        return media._response(404, {"error": "Game not found"})
    entries = query(f"GAME#{game_id}")
    members = [clean(r) for r in entries if r["entityType"] == "GameMembership"]
    players = [clean(read("PLAYERS", m["playerId"])) for m in members]
    return media._response(
        200,
        {
            "game": clean(game),
            "players": players,
            "memberships": members,
            "characters": [clean(r) for r in entries if r["entityType"] == "Character"],
        },
    )


def create(body, actor):
    validate(body)
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    existing = read("GAMES", body["id"])
    if existing:
        if existing["fingerprint"] != fingerprint:
            return media._response(409, {"error": "Game exists; creation never overwrites it"})
        return detail(body["id"])
    now = datetime.now(timezone.utc).isoformat()
    records = [
        {
            "pk": "GAMES",
            "sk": body["id"],
            "entityType": "Game",
            "schemaVersion": 1,
            **{k: body[k] for k in ("id", "name", "purpose")},
            "fingerprint": fingerprint,
            "createdAt": now,
            "createdBy": actor,
        }
    ]
    checks = []
    for player in body["players"]:
        old = read("PLAYERS", player["id"])
        if old:
            if old["name"] != player["name"]:
                return media._response(409, {"error": "Player ID already has a different name"})
            checks.append(
                {
                    "ConditionCheck": {
                        "TableName": table.name,
                        "Key": {"pk": {"S": "PLAYERS"}, "sk": {"S": player["id"]}},
                        "ConditionExpression": "#n = :n",
                        "ExpressionAttributeNames": {"#n": "name"},
                        "ExpressionAttributeValues": {":n": {"S": player["name"]}},
                    }
                }
            )
        else:
            records.append(
                {
                    "pk": "PLAYERS",
                    "sk": player["id"],
                    "entityType": "Player",
                    "schemaVersion": 1,
                    **player,
                }
            )
    for character in body["characters"]:
        records.append(
            {
                "pk": f"GAME#{body['id']}",
                "sk": f"CHARACTER#{character['id']}",
                "entityType": "Character",
                "schemaVersion": 1,
                "gameId": body["id"],
                **character,
            }
        )
    for member in body["memberships"]:
        records.append(
            {
                "pk": f"GAME#{body['id']}",
                "sk": f"MEMBER#{member['playerId']}",
                "entityType": "GameMembership",
                "schemaVersion": 1,
                "gameId": body["id"],
                **member,
            }
        )
    boto3.client("dynamodb").transact_write_items(
        TransactItems=checks
        + [
            {
                "Put": {
                    "TableName": table.name,
                    "Item": {k: serializer.serialize(v) for k, v in r.items()},
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            }
            for r in records
        ]
    )
    return detail(body["id"])


def handler(event, _context):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    # One trusted group today: every configured account can read every game. A selector is not an ACL.
    if not claims.get("sub") or claims.get("cognito:username") not in EDITORS:
        return media._response(403, {"error": "This account cannot access the game catalog"})
    try:
        route = event.get("routeKey")
        if route == "GET /games":
            return media._response(200, {"games": games()})
        if route == "GET /game":
            return detail(media._query(event, "gameId"))
        if route == "GET /players":
            return media._response(200, {"players": [clean(p) for p in query("PLAYERS")]})
        if route == "POST /games":
            raw = event.get("body") or ""
            if len(raw) > 24000:
                raise ValueError("Game setup is too large")
            if event.get("isBase64Encoded"):
                raw = base64.b64decode(raw, validate=True)
            return create(json.loads(raw), claims["sub"])
        return media._response(404, {"error": "Unknown catalog operation"})
    except (ValueError, TypeError, KeyError):
        return media._response(400, {"error": "Invalid structured game/roster; inspect the schema"})
    except ClientError:
        return media._response(
            409, {"error": "Catalog changed or storage unavailable; inspect before retrying"}
        )
