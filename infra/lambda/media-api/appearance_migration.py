"""Bounded maintenance-only legacy source inspection; no browsing fallback."""

import hashlib
import base64
import json
import re
import struct
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.exceptions import ClientError

import asset_library
from novel_library import indexed

VERSION = 1
MAX_SOURCE_BYTES = 64 * 1024
MAX_SNAPSHOTS = 500
MAX_RETAINED_VERSIONS = 1002


def retained_versions(media, game, cid, represented_hashes):
    """Never silently exclude source versions retained only by S3 versioning."""
    prefix = f"games/{game}/characters/{cid}/"
    pattern = re.compile(re.escape(prefix) + r"(?:profile\.json|history/[a-f0-9]{64}\.json)$")
    versions = []
    for page in media.raw_s3.get_paginator("list_object_versions").paginate(
        Bucket=media.BUCKET_NAME, Prefix=prefix
    ):
        for version in page.get("Versions", []):
            key = version["Key"]
            if not pattern.fullmatch(key):
                if key.startswith(prefix + "history/") and key.endswith(".json"):
                    raise ValueError("Unresolvable retained source version filename")
                continue
            if not 0 < version["Size"] <= MAX_SOURCE_BYTES:
                raise ValueError("Retained source version exceeds its bounded size")
            versions.append({"key": key, "versionId": version["VersionId"]})
            if len(versions) > MAX_RETAINED_VERSIONS:
                raise ValueError("Retained versions exceed the complete verification limit")

    def inspect(version):
        source = media.raw_s3.get_object(
            Bucket=media.BUCKET_NAME, Key=version["key"], VersionId=version["versionId"]
        )
        raw = source["Body"].read(MAX_SOURCE_BYTES + 1)
        digest = hashlib.sha256(raw).hexdigest()
        if not 0 < len(raw) <= MAX_SOURCE_BYTES or digest not in represented_hashes:
            raise ValueError(
                "Retained S3 source version lacks an imported byte-preserving snapshot"
            )
        return {**version, "sha256": digest}

    with ThreadPoolExecutor(max_workers=4) as executor:
        evidence = list(executor.map(inspect, versions))
    evidence.sort(key=lambda item: (item["key"], item["versionId"]))
    if len(json.dumps(evidence).encode()) > 192 * 1024:
        raise ValueError("Retained source evidence exceeds its bounded verification envelope")
    return evidence


def inventory(media, game, cid):
    prefix = f"games/{game}/characters/{cid}/"
    keys = []
    paginator = media.raw_s3.get_paginator("list_objects_v2")
    pattern = re.compile(re.escape(prefix) + r"(?:profile\.json|history/[a-f0-9]{64}\.json)$")
    for page in paginator.paginate(Bucket=media.BUCKET_NAME, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if not pattern.fullmatch(key):
                if key.startswith(prefix + "history/") and key.endswith(".json"):
                    raise ValueError("Unresolvable retained profile history filename")
                continue
            if not 0 < item["Size"] <= MAX_SOURCE_BYTES:
                raise ValueError("Legacy appearance source is empty or exceeds its bounded size")
            keys.append(key)
            if len(keys) > MAX_SNAPSHOTS + 1:
                raise ValueError("Appearance history exceeds the migration inventory limit")
    current = prefix + "profile.json"
    if keys and current not in keys:
        raise ValueError("Historical artwork has no current source profile")
    return sorted(keys)


def prepare(media, game, cid, source_key):
    prefix = f"games/{game}/characters/{cid}/"
    if not re.fullmatch(
        re.escape(prefix) + r"(?:profile\.json|history/[a-f0-9]{64}\.json)", source_key
    ):
        raise ValueError("Migration source must be this character's exact legacy profile")
    source = media.raw_s3.get_object(Bucket=media.BUCKET_NAME, Key=source_key)
    raw = source["Body"].read(MAX_SOURCE_BYTES + 1)
    if not 0 < len(raw) <= MAX_SOURCE_BYTES:
        raise ValueError("Legacy source exceeds its bounded size")
    profile = json.loads(raw)
    if not media._character_summary(profile, game_id=game, character_id=cid):
        raise ValueError("Legacy source does not identify this registered character")
    model = profile.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("posterKey"), str):
        raise ValueError("Legacy profile lacks an explicit portrait selection")
    fields = {
        "portraitKey": model["posterKey"],
        "modelKey": model.get("webKey"),
        "sourceKey": model.get("sourceKey"),
        "provenanceKey": model.get("provenanceKey"),
    }
    if fields["modelKey"] is None and (
        fields["sourceKey"] is not None or fields["provenanceKey"] is not None
    ):
        raise ValueError("Legacy source claims model files without a selected model")
    keys = list(dict.fromkeys(k for k in fields.values() if k is not None))
    if not all(asset_library.valid_key(media, game, key) for key in keys):
        raise ValueError("Legacy selected sources must be immutable same-game assets")
    sources = indexed(game, keys)
    if any(
        key not in sources or json.loads(sources[key]["payload"]).get("key") != key for key in keys
    ):
        raise ValueError("Legacy selection has unavailable indexed assets")
    assets = {key: json.loads(item["payload"]) for key, item in sources.items()}
    if any(
        asset.get("metadata", {}).get("characterIds")
        and cid not in asset["metadata"]["characterIds"]
        for asset in assets.values()
    ):
        raise ValueError("Legacy selection conflicts with explicit asset character identity")
    portrait = assets[fields["portraitKey"]]
    if (
        portrait.get("contentType") not in {"image/png", "image/jpeg", "image/webp", "image/avif"}
        or not 0 < portrait["size"] <= media.MAX_POSTER_BYTES
    ):
        raise ValueError("Legacy selected portrait cannot be displayed")
    if fields["modelKey"]:
        selected = assets[fields["modelKey"]]
        if (
            not fields["modelKey"].endswith(".glb")
            or selected.get("contentType") not in {"model/gltf-binary", "application/octet-stream"}
            or not 0 < selected["size"] <= media.MAX_MODEL_BYTES
        ):
            raise ValueError("Legacy selected model cannot be displayed")
        header = media.s3.get_object(
            Bucket=media.BUCKET_NAME, Key=fields["modelKey"], Range="bytes=0-11"
        )["Body"].read(12)
        if len(header) != 12 or struct.unpack("<4sII", header) != (b"glTF", 2, selected["size"]):
            raise ValueError("Legacy selected model has an invalid GLB header")
    declared = {
        asset.get("metadata", {}).get("extra", {}).get("appearanceId") for asset in assets.values()
    }
    declared.discard(None)
    if profile.get("appearanceId") is not None:
        declared.add(profile["appearanceId"])
    if len(declared) > 1 or any(not media._valid_slug(aid) or len(aid) > 96 for aid in declared):
        raise ValueError("Legacy appearance identities conflict; resolve the evidence privately")
    digest = hashlib.sha256(raw).hexdigest()
    appearance_id = next(iter(declared)) if declared else "imported-" + digest[:24]
    # The selected profile substantiates its character association, but never an invented
    # transformation, fictional date or physical-state classification.
    plan = {
        "schemaVersion": VERSION,
        "gameId": game,
        "characterId": cid,
        "sourceKey": source_key,
        "sourceSha256": digest,
        "sourceETag": source["ETag"],
        "sourceVersionId": source.get("VersionId"),
        "sourceCapturedAt": source["LastModified"].isoformat(),
        "isCurrent": source_key == prefix + "profile.json",
        "appearanceId": appearance_id,
        "selectionId": digest,
        "selection": fields,
        "observedAssets": {key: str(item["observed"]) for key, item in sources.items()},
    }
    return plan, raw, profile


def game_inventory(media, game, cursor=None):
    prefix = f"games/{game}/characters/"
    args = {"Bucket": media.BUCKET_NAME, "Prefix": prefix, "Delimiter": "/", "MaxKeys": 250}
    if cursor:
        args["ContinuationToken"] = cursor
    result = media.raw_s3.list_objects_v2(**args)
    identities = []
    for item in result.get("CommonPrefixes", []):
        identity = item["Prefix"].removeprefix(prefix).removesuffix("/")
        if not media._valid_slug(identity) or len(identity) > 96:
            raise ValueError("Unresolvable legacy character prefix")
        identities.append(identity)
    return {"characters": identities, "cursor": result.get("NextContinuationToken")}


def apply(media, plan, actor):
    """Import one exact source atomically. Activation is a separate completeness gate."""
    import character_appearances as looks
    import organization_records as records

    if not isinstance(plan, dict) or plan.get("schemaVersion") != VERSION:
        raise ValueError("Unsupported appearance migration plan")
    game, cid = plan["gameId"], plan["characterId"]
    if not media._valid_slug(game) or not media._valid_slug(cid):
        raise ValueError("Invalid migration identity")
    current, raw, _ = prepare(media, game, cid, plan["sourceKey"])
    if current != plan:
        raise ValueError("Migration source or indexed assets changed; prepare a new plan")
    db = looks.browse_index.table()
    receipt_key = {
        "pk": f"{looks.PREFIX}-migration#{game}#{cid}",
        "sk": hashlib.sha256(
            (plan["sourceKey"] + "\0" + plan["sourceSha256"]).encode()
        ).hexdigest(),
    }
    receipt = db.get_item(Key=receipt_key, ConsistentRead=True).get("Item")
    if receipt:
        previous_plan = json.loads(receipt["sourcePlan"])
        if {k: v for k, v in previous_plan.items() if k != "observedAssets"} != {
            k: v for k, v in plan.items() if k != "observedAssets"
        }:
            raise ValueError("Migration receipt does not match this exact source")
        return {"status": "already-imported", "selectionId": plan["selectionId"]}
    catalog, char_key, registered = looks.character(game, cid)
    revision = plan["sourceSha256"][:32]
    now = datetime.now(timezone.utc).isoformat()
    base = {
        "schemaVersion": 1,
        "gameId": game,
        "characterId": cid,
        "revision": revision,
        "previousRevision": None,
        "updatedAt": now,
        "updatedBy": actor,
        "reason": "Import exact retained artwork selection; story timing unknown",
        "migrationSource": {"key": plan["sourceKey"], "sha256": plan["sourceSha256"]},
    }
    aid = plan["appearanceId"]
    appearance = {
        **base,
        "entityType": "CharacterAppearance",
        "id": aid,
        "name": "Imported appearance · " + aid,
        "description": "Physical state and story timing were not recorded in the source selection.",
        "state": "unknown",
        "developedFrom": None,
        "story": {"sessionId": None, "eventId": None, "date": None},
    }
    selection = {
        **base,
        "entityType": "AppearanceSelection",
        "id": plan["selectionId"],
        "appearanceId": aid,
        "appearanceRevision": revision,
        "sourceCapturedAt": plan["sourceCapturedAt"],
        **plan["selection"],
    }
    writes = []

    def put(item):
        writes.append(
            {
                "Put": {
                    "TableName": db.name,
                    "Item": records.encode(item),
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            }
        )

    def payload(record):
        return json.dumps(record, separators=(",", ":"), allow_nan=False)

    def historical(name, record):
        item = {
            "pk": f"{looks.PREFIX}-history#{looks.kind(name, cid)}#{game}#{record['id']}",
            "sk": record["revision"],
            "payload": payload(record),
        }
        previous = db.get_item(Key={"pk": item["pk"], "sk": item["sk"]}, ConsistentRead=True).get(
            "Item"
        )
        if previous:
            if (
                records.decode(previous).get("migrationSource", {}).get("sha256")
                != plan["sourceSha256"]
            ):
                raise ValueError("Imported revision identity conflict")
            return
        put(item)

    def pointer(name, record):
        put(
            {
                **records.pointer(looks.PREFIX, game, looks.kind(name, cid), record["id"]),
                "revision": record["revision"],
                "payload": payload(record),
            }
        )

    appearance_key = records.pointer(looks.PREFIX, game, looks.kind("appearance", cid), aid)
    existing = db.get_item(Key=appearance_key, ConsistentRead=True).get("Item")
    if not existing:
        pointer("appearance", appearance)
    else:
        writes.append(looks.guard(db, appearance_key, existing))
    historical("appearance", appearance)
    selection_key = records.pointer(
        looks.PREFIX, game, looks.kind("selection", cid), selection["id"]
    )
    previous_selection = db.get_item(Key=selection_key, ConsistentRead=True).get("Item")
    if previous_selection:
        saved = records.decode(previous_selection)
        if (
            saved.get("appearanceId") != aid
            or any(saved.get(k) != v for k, v in plan["selection"].items())
            or saved.get("migrationSource", {}).get("sha256") != plan["sourceSha256"]
        ):
            raise ValueError("Imported selection identity conflict")
        writes.append(looks.guard(db, selection_key, previous_selection))
    else:
        pointer("selection", selection)
    historical("selection", selection)
    sources = indexed(
        game, list(dict.fromkeys(k for k in plan["selection"].values() if k is not None))
    )
    for key, source in sources.items():
        asset = json.loads(source["payload"])
        declared = asset.get("metadata", {}).get("characterIds", [])
        if declared and cid not in declared:
            raise ValueError("Legacy selection conflicts with explicit asset character identity")
        assoc_id = looks.association_id(key)
        assoc_key = records.pointer(
            looks.PREFIX, game, looks.kind("association", cid, aid), assoc_id
        )
        previous = db.get_item(Key=assoc_key, ConsistentRead=True).get("Item")
        if previous:
            if records.decode(previous)["assetKey"] != key:
                raise ValueError("Existing association identity conflict")
            writes.append(looks.guard(db, assoc_key, previous))
        else:
            association = {
                **base,
                "entityType": "AppearanceAsset",
                "id": assoc_id,
                "appearanceId": aid,
                "appearanceRevision": revision,
                "assetKey": key,
            }
            put({**assoc_key, "revision": revision, "payload": payload(association)})
        writes.append(
            looks.guard(
                db, {"pk": looks.browse_index.partition(game, "all"), "sk": key}, source, "observed"
            )
        )
    put(
        {
            **receipt_key,
            "sourcePlan": json.dumps(plan, sort_keys=True),
            "sourceRawBase64": base64.b64encode(raw).decode(),
            "recordedAt": now,
            "actor": actor,
        }
    )
    writes.append(looks.guard(catalog, char_key, registered, "detailsRevision"))
    try:
        boto3.client("dynamodb").transact_write_items(TransactItems=writes)
    except ClientError as error:
        if error.response["Error"]["Code"] == "TransactionCanceledException":
            raise ValueError(
                "Migration conflict; inspect current sources before retrying"
            ) from error
        raise
    return {"status": "imported", "selectionId": plan["selectionId"]}


def verification(media, game, cid):
    """Every retained source has a byte-preserving receipt; legacy writers must be frozen."""
    import character_appearances as looks
    from boto3.dynamodb.conditions import Key

    keys = inventory(media, game, cid)
    db = looks.browse_index.table()
    receipts = []
    args = {
        "KeyConditionExpression": Key("pk").eq(f"{looks.PREFIX}-migration#{game}#{cid}"),
        "ConsistentRead": True,
        "Limit": 100,
    }
    while True:
        page = db.query(**args)
        receipts.extend(i for i in page.get("Items", []) if i["sk"] != "complete")
        if len(receipts) > MAX_SNAPSHOTS + 1:
            raise ValueError("Migration receipts exceed the supported inventory limit")
        cursor = page.get("LastEvaluatedKey")
        if not cursor:
            break
        args["ExclusiveStartKey"] = cursor
    by_key = {}
    for receipt in receipts:
        plan = json.loads(receipt["sourcePlan"])
        raw = base64.b64decode(receipt["sourceRawBase64"], validate=True)
        if plan["sourceKey"] in by_key or hashlib.sha256(raw).hexdigest() != plan["sourceSha256"]:
            raise ValueError("Duplicate or corrupted migration receipt")
        by_key[plan["sourceKey"]] = plan
        _, _, selection, _ = looks.resolve(game, cid, plan["appearanceId"], plan["selectionId"])
        if any(selection.get(k) != v for k, v in plan["selection"].items()):
            raise ValueError("Imported selection does not preserve exact source keys")
    if set(by_key) != set(keys):
        raise ValueError("Every retained source must be imported before activation")

    def observed(key):
        head = media.raw_s3.head_object(Bucket=media.BUCKET_NAME, Key=key)
        plan = by_key[key]
        if head["ETag"] != plan["sourceETag"] or head.get("VersionId") != plan["sourceVersionId"]:
            raise ValueError(
                "Legacy source changed after import; resolve privately before activation"
            )
        return {
            "key": key,
            "sha256": plan["sourceSha256"],
            "etag": head["ETag"],
            "versionId": head.get("VersionId"),
        }

    with ThreadPoolExecutor(max_workers=4) as executor:
        evidence = list(executor.map(observed, keys))
    if inventory(media, game, cid) != keys:
        raise ValueError("Retained source inventory changed during verification")
    versions = retained_versions(media, game, cid, {p["sourceSha256"] for p in by_key.values()})
    digest = hashlib.sha256(
        json.dumps(
            {"sources": evidence, "versions": versions}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    current = by_key.get(f"games/{game}/characters/{cid}/profile.json")
    return {
        "schemaVersion": VERSION,
        "gameId": game,
        "characterId": cid,
        "inventoryHash": digest,
        "sourceCount": len(keys),
        "retainedVersions": versions,
        "currentSelection": current,
    }


def finalize(media, expected, operation, claims):
    import character_appearances as looks
    import organization_records as records

    records.revision(operation)
    if not isinstance(expected, dict) or expected.get("schemaVersion") != VERSION:
        raise ValueError("Use a complete verified appearance migration inventory")
    game, cid = expected["gameId"], expected["characterId"]
    actual = verification(media, game, cid)
    if actual != expected:
        raise ValueError("Verified inventory changed; reverify before activation")
    db = looks.browse_index.table()
    key = {"pk": f"{looks.PREFIX}-migration#{game}#{cid}", "sk": "complete"}
    complete = db.get_item(Key=key, ConsistentRead=True).get("Item")
    if complete:
        if complete["inventoryHash"] != actual["inventoryHash"]:
            raise ValueError("Completed migration differs from retained sources")
        return media._response(200, {"status": "already-complete", "verification": actual})
    current = actual["currentSelection"]
    seal = {
        **key,
        "inventoryHash": actual["inventoryHash"],
        "sourceCount": actual["sourceCount"],
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "actor": claims["sub"],
        "operationId": operation,
        "verificationJson": json.dumps(actual, separators=(",", ":")),
    }
    put = {
        "Put": {
            "TableName": db.name,
            "Item": records.encode(seal),
            "ConditionExpression": "attribute_not_exists(pk)",
        }
    }
    if current is None:
        # A registered roster-only character has no appearance to invent or activate.
        catalog, char_key, registered = looks.character(game, cid)
        boto3.client("dynamodb").transact_write_items(
            TransactItems=[put, looks.guard(catalog, char_key, registered, "detailsRevision")]
        )
        return media._response(200, {"status": "complete-without-artwork", "verification": actual})
    body = {
        "gameId": game,
        "characterId": cid,
        "id": "current",
        "expectedRevision": None,
        "operationId": operation,
        "reason": "Activate verified imported current artwork · " + actual["inventoryHash"],
        "appearanceId": current["appearanceId"],
        "selectionId": current["selectionId"],
        "story": {"sessionId": None, "eventId": None, "date": None},
    }
    return looks.save(
        media,
        body,
        claims,
        "activation",
        maintenance_guards=[put],
        maintenance_fields={"migrationInventoryHash": actual["inventoryHash"]},
    )
