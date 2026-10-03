"""Versioned character facts in the catalog, separate from artwork selections."""

import base64
import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError


def empty_details():
    return {
        "schemaVersion": 1,
        "aliases": [],
        "pronouns": None,
        "role": None,
        "status": None,
        "overview": None,
        "subtitle": None,
        "backstory": None,
        "notes": None,
        "statistics": [],
        "relationships": [],
        "thumbnailAssetKey": None,
    }


def initial_fields():
    return {
        "schemaVersion": 2,
        "appearanceContractJson": json.dumps({"schemaVersion": 1, "origin": "created-current"}),
        "detailsJson": json.dumps(empty_details()),
        "detailsRevision": uuid.uuid4().hex,
    }


def text(value, maximum, nullable=False):
    if nullable and value is None:
        return
    if (
        not isinstance(value, str)
        or not 1 <= len(value.strip()) <= maximum
        or any(ord(c) < 32 and c not in "\n\t" for c in value)
    ):
        raise ValueError("Invalid character text")


def validate(details, catalog, game, character, resolve=True):
    import index as media

    if (
        not isinstance(details, dict)
        or set(details) != set(empty_details())
        or type(details["schemaVersion"]) is not int
        or details["schemaVersion"] != 1
    ):
        raise ValueError("Invalid character details schema")
    for field, maximum in [
        ("pronouns", 80),
        ("role", 120),
        ("status", 120),
        ("overview", 1000),
        ("subtitle", 160),
        ("backstory", 8000),
        ("notes", 4000),
    ]:
        text(details[field], maximum, True)
    aliases = details["aliases"]
    if (
        not isinstance(aliases, list)
        or len(aliases) > 20
        or not all(isinstance(a, str) for a in aliases)
        or len(set(aliases)) != len(aliases)
    ):
        raise ValueError("Invalid character aliases")
    for alias in aliases:
        text(alias, 120)
    stats = details["statistics"]
    if not isinstance(stats, list) or len(stats) > 100:
        raise ValueError("Invalid statistics")
    identities = set()
    for stat in stats:
        if not isinstance(stat, dict) or set(stat) != {"group", "name", "value"}:
            raise ValueError("Statistics require group, name and typed value")
        text(stat["group"], 80, True)
        text(stat["name"], 120)
        identity = (stat["group"], stat["name"])
        if identity in identities:
            raise ValueError("Duplicate statistic")
        identities.add(identity)
        value = stat["value"]
        if value is not None and type(value) not in (str, int, float, bool):
            raise ValueError("Statistics use text, number, boolean or null")
        if isinstance(value, str):
            text(value, 500)
        if type(value) in (int, float) and (abs(value) > 1e15 or not math.isfinite(value)):
            raise ValueError("Invalid statistic number")
    relationships = details["relationships"]
    if not isinstance(relationships, list) or len(relationships) > 40:
        raise ValueError("Invalid relationships")
    identities = set()
    for ref in relationships:
        if not isinstance(ref, dict) or set(ref) != {"entityType", "id", "relation"}:
            raise ValueError("Relationships require entityType, id and relation")
        text(ref["relation"], 120)
        if ref["entityType"] == "Character":
            if not media._valid_slug(ref["id"]):
                raise ValueError("Invalid character relationship identity")
            exists = catalog.read(f"GAME#{game}", f"CHARACTER#{ref['id']}") if resolve else True
        elif ref["entityType"] == "Player":
            if not media._valid_slug(ref["id"]):
                raise ValueError("Invalid player relationship identity")
            exists = catalog.read(f"GAME#{game}", f"MEMBER#{ref['id']}") if resolve else True
        elif ref["entityType"] == "Asset":
            import asset_library

            if not asset_library.valid_key(media, game, ref["id"]):
                raise ValueError("Relationships must stay in the same game")
            exists = (
                media.s3.head_object(Bucket=media.BUCKET_NAME, Key=ref["id"]) if resolve else True
            )
        else:
            raise ValueError("Unsupported relationship type")
        identity = (ref["entityType"], ref["id"], ref["relation"])
        if not exists or identity in identities:
            raise ValueError("Missing or duplicate relationship")
        identities.add(identity)
    if len(json.dumps(details, allow_nan=False).encode()) > 20000:
        raise ValueError("Character details exceed 20 KiB")
    key = details["thumbnailAssetKey"]
    if key is not None:
        import asset_library

        if not asset_library.valid_key(media, game, key):
            raise ValueError("Invalid thumbnail identity")
        if not resolve:
            return
        head = catalog.media.s3.head_object(Bucket=catalog.media.BUCKET_NAME, Key=key)
        metadata = json.loads(
            base64.b64decode(head.get("Metadata", {}).get("panther", "e30="), validate=True)
        )
        if (
            character not in metadata.get("characterIds", [])
            or head.get("ContentType")
            not in {"image/png", "image/jpeg", "image/webp", "image/avif"}
            or not 0 < head["ContentLength"] <= catalog.media.MAX_POSTER_BYTES
        ):
            raise ValueError("Thumbnail must explicitly depict this character")


def decode(record):
    if not record or record.get("schemaVersion") != 2 or not record.get("detailsRevision"):
        raise ValueError("Character details require the version-2 migration")
    details = json.loads(record["detailsJson"])
    validate(details, None, record["gameId"], record["id"], resolve=False)
    return {
        "characterId": record["id"],
        "gameId": record["gameId"],
        "name": record["name"],
        "revision": record["detailsRevision"],
        "details": details,
    }


def legacy_projection(catalog, old):
    """Copy only explicitly recorded facts; preserve the complete original record."""
    details = empty_details()
    source = None
    for field in set(details) - {"schemaVersion"}:
        if field in old:
            details[field] = old[field]
    profile = catalog.media._legacy_profile_record(old["gameId"], old["id"])
    if profile is None:
        # The artwork reader deliberately returns None for malformed/oversized
        # files as well as missing files. Migration must not silently drop those.
        key = f"games/{old['gameId']}/characters/{old['id']}/profile.json"
        try:
            catalog.media.s3.head_object(Bucket=catalog.media.BUCKET_NAME, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
                raise
        else:
            raise ValueError(
                "Existing artwork profile is invalid or oversized; reconcile before migration"
            )
    if profile:
        key, raw, value, revision = profile
        head = catalog.media.s3.head_object(
            Bucket=catalog.media.BUCKET_NAME, Key=key, IfMatch=revision
        )
        source = {
            "key": key,
            "etag": revision,
            "versionId": head.get("VersionId"),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        if "stats" in value and "statistics" not in value:
            raise ValueError("Legacy statistics require an explicit mapping before migration")
        for field in set(details) - {"schemaVersion", "thumbnailAssetKey"}:
            if field in value:
                if field in old and old[field] != value[field]:
                    raise ValueError(
                        "Conflicting legacy character facts require explicit reconciliation"
                    )
                details[field] = value[field]
        for field, recorded in {
            "overview": value.get("summary") or None,
            "subtitle": value.get("title") or None,
            "thumbnailAssetKey": value.get("model", {}).get("posterKey"),
        }.items():
            if recorded is not None:
                if details[field] is not None and details[field] != recorded:
                    raise ValueError(
                        "Conflicting legacy character facts require explicit reconciliation"
                    )
                details[field] = recorded
    encoded = TypeSerializer().serialize(old)
    source_hash = hashlib.sha256(
        json.dumps({"record": encoded, "profile": source}, sort_keys=True).encode()
    ).hexdigest()
    validate(details, catalog, old["gameId"], old["id"])
    return details, source, source_hash


def save(catalog, body, actor, migration_admin, source_evidence=None):
    fields = {
        "gameId",
        "characterId",
        "mode",
        "details",
        "expectedRevision",
        "expectedSourceHash",
        "operationId",
        "reason",
        "dryRun",
    }
    if (
        not isinstance(body, dict)
        or set(body) not in (fields, fields | {"name"})
        or body["mode"] not in ("edit", "migrate")
        or type(body["dryRun"]) is not bool
    ):
        raise ValueError("Invalid character edit envelope")
    if "name" in body and body["mode"] != "edit":
        raise ValueError("Migration cannot rename a character")
    if "name" in body:
        catalog.name(body["name"])
    game, character = catalog.identifier(body["gameId"]), catalog.identifier(body["characterId"])
    text(body["reason"], 500)
    operation = body["operationId"]
    expected = body["expectedRevision"]
    if (
        not isinstance(operation, str)
        or not re.fullmatch(r"[a-f0-9]{32}", operation)
        or (
            expected is not None
            and (not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{32}", expected))
        )
    ):
        raise ValueError("Invalid operation or revision")
    old = catalog.read(f"GAME#{game}", f"CHARACTER#{character}")
    if not old:
        return catalog.media._response(404, {"error": "Character not found"})
    opkey = {"pk": f"CHARACTER_DETAILS_OP#{game}#{character}", "sk": operation}
    fingerprint = hashlib.sha256(
        json.dumps(body, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    previous = catalog.table.get_item(Key=opkey, ConsistentRead=True).get("Item")
    if previous:
        if previous["fingerprint"] != fingerprint:
            return catalog.media._response(
                409, {"error": "Operation identity reused with different arguments"}
            )
        return catalog.media._response(
            200,
            {"character": decode(old), "operationRevision": previous["revision"], "replayed": True},
        )
    source = source_evidence
    if body["mode"] == "migrate":
        if not migration_admin:
            return catalog.media._response(
                403, {"error": "Character migration permission required"}
            )
        if old.get("schemaVersion") == 2:
            return catalog.media._response(
                200, {"character": decode(old), "status": "already-current"}
            )
        if old.get("schemaVersion") != 1 or expected is not None:
            raise ValueError("Unsupported legacy character state")
        details, source, source_hash = legacy_projection(catalog, old)
        if body["dryRun"]:
            return catalog.media._response(
                200,
                {
                    "status": "ready",
                    "plan": {
                        **body,
                        "details": details,
                        "expectedSourceHash": source_hash,
                        "dryRun": False,
                    },
                    "sourceProfile": source,
                },
            )
        if body["expectedSourceHash"] != source_hash or body["details"] != details:
            return catalog.media._response(
                409, {"error": "Source facts changed; prepare a new migration plan"}
            )
    else:
        decode(old)
        if body["expectedSourceHash"] is not None:
            raise ValueError("Regular edits cannot supply migration evidence")
        if expected != old["detailsRevision"]:
            return catalog.media._response(
                409, {"error": "Character changed; reload before editing"}
            )
        details = body["details"]
        validate(details, catalog, game, character)
        if body["dryRun"]:
            return catalog.media._response(200, {"status": "ready"})
    revision = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    updated = {
        **old,
        "schemaVersion": 2,
        "name": body.get("name", old["name"]),
        "detailsRevision": revision,
        "detailsJson": json.dumps(details, allow_nan=False, separators=(",", ":")),
        "detailsSubtitle": details["subtitle"],
        "detailsThumbnailKey": details["thumbnailAssetKey"],
    }
    history = {
        "pk": f"CHARACTER_DETAILS_HISTORY#{game}#{character}",
        "sk": revision,
        "revision": revision,
        "name": updated["name"],
        "previousName": old["name"],
        "detailsJson": updated["detailsJson"],
        "recordedAt": now,
        "actor": actor,
        "reason": body["reason"],
        "previousRevision": old.get("detailsRevision"),
        "sourceProfile": source,
    }
    if body["mode"] == "migrate":
        history["legacyRecord"] = old
        updated["detailsMigrationRevision"] = revision
    elif old.get("detailsRevision"):
        history["previousDetailsJson"] = old["detailsJson"]

    def encode(value):
        return {k: catalog.serializer.serialize(v) for k, v in value.items()}

    put = {
        "TableName": catalog.table.name,
        "Item": encode(updated),
        "ConditionExpression": "detailsRevision = :expected"
        if expected
        else "attribute_not_exists(detailsRevision) AND schemaVersion = :one",
        "ExpressionAttributeValues": encode({":expected": expected} if expected else {":one": 1}),
    }
    if body["mode"] == "migrate":
        # Legacy records have no revision token. Pin every observed attribute and
        # absence of the known fact fields so concurrent roster edits cannot be lost.
        names, values = {}, put["ExpressionAttributeValues"]
        checks = [put["ConditionExpression"]]
        for i, key in enumerate(set(old) | (set(empty_details()) - {"schemaVersion"})):
            if key in {"pk", "sk", "schemaVersion"}:
                continue
            alias = f"#old{i}"
            names[alias] = key
            if key in old:
                token = f":old{i}"
                values[token] = catalog.serializer.serialize(old[key])
                checks.append(f"{alias} = {token}")
            else:
                checks.append(f"attribute_not_exists({alias})")
        put["ExpressionAttributeNames"] = names
        put["ConditionExpression"] = " AND ".join(checks)
    writes = [{"Put": put}]
    for item in (history, {**opkey, "fingerprint": fingerprint, "revision": revision}):
        writes.append(
            {
                "Put": {
                    "TableName": catalog.table.name,
                    "Item": encode(item),
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            }
        )
    import asset_archive

    writes.extend(
        asset_archive.reference_writes(
            game,
            f"character:{character}",
            [details["thumbnailAssetKey"]] if details["thumbnailAssetKey"] else [],
        )
    )
    try:
        boto3.client("dynamodb").transact_write_items(TransactItems=writes)
    except ClientError:
        return catalog.media._response(
            409,
            {
                "error": "Character changed or write failed; inspect before retrying the same operation"
            },
        )
    return catalog.media._response(
        200, {"character": decode(updated), "operationRevision": revision}
    )


def read_history(catalog, event, record):
    """Follow the actual predecessor chain; random revision IDs do not order time."""
    game, character = record["gameId"], record["id"]
    revision = catalog.media._query(event, "cursor") or record.get("detailsRevision")
    if revision and (not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{32}", revision)):
        raise ValueError("Invalid character history cursor")
    entries, seen = [], set()
    while revision and len(entries) < 25:
        if revision in seen:
            raise ValueError("Invalid character revision chain")
        seen.add(revision)
        item = catalog.read(f"CHARACTER_DETAILS_HISTORY#{game}#{character}", revision)
        if not item:
            # The creation revision predates history tracking. Do not invent a snapshot.
            revision = None
            break
        entry = {
            key: item.get(key)
            for key in (
                "revision",
                "previousRevision",
                "recordedAt",
                "reason",
                "name",
                "previousName",
            )
        }
        entry["details"] = json.loads(item["detailsJson"])
        entry["previousDetails"] = (
            json.loads(item["previousDetailsJson"]) if item.get("previousDetailsJson") else None
        )
        entries.append(entry)
        revision = item.get("previousRevision")
    return catalog.media._response(200, {"history": entries, "cursor": revision})


def handle(catalog, event, claims):
    if event["routeKey"] in {"POST /character-details", "POST /character-details/migrate"}:
        raw = event.get("body") or "{}"
        if len(raw) > 32000:
            raise ValueError("Character edit is too large")
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw, validate=True)
        body = json.loads(raw)
        expected_mode = "migrate" if event["routeKey"].endswith("/migrate") else "edit"
        if not isinstance(body, dict) or body.get("mode") != expected_mode:
            raise ValueError("Use the matching character operation endpoint")
        return save(catalog, body, claims["sub"], expected_mode == "migrate")
    game = catalog.identifier(catalog.media._query(event, "gameId"))
    character = catalog.identifier(catalog.media._query(event, "characterId"))
    record = catalog.read(f"GAME#{game}", f"CHARACTER#{character}")
    if not record:
        return catalog.media._response(404, {"error": "Character not found"})
    if event["routeKey"] == "GET /character-details/history":
        return read_history(catalog, event, record)
    if event["routeKey"] == "GET /character-details/verify":
        value = decode(record)
        validate(value["details"], catalog, game, character)
        migration_revision = record.get("detailsMigrationRevision")
        if migration_revision:
            history = catalog.read(
                f"CHARACTER_DETAILS_HISTORY#{game}#{character}", migration_revision
            )
            if not history or history.get("legacyRecord", {}).get("schemaVersion") != 1:
                raise ValueError("Character migration history is missing")
        return catalog.media._response(200, {"character": value, "verified": True})
    return catalog.media._response(200, {"character": decode(record)})
