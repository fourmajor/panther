"""Named physical states, immutable artwork pairs and separate activation history."""

import hashlib
import json
import os
import struct
import base64

import boto3
from botocore.exceptions import ClientError

from access_policy import authorized
import asset_library
import browse_index
from novel_library import indexed, slug, text
import organization_records as records

PREFIX = "character-looks"
COMMON = {"gameId", "characterId", "id", "expectedRevision", "operationId", "reason"}


def parse_body(event):
    raw = event.get("body") or ""
    if not isinstance(raw, str) or len(raw) > 96 * 1024:
        raise ValueError("Appearance envelope exceeds its bounded size")
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw, validate=True)
    if len(raw) > 64 * 1024:
        raise ValueError("Appearance envelope exceeds its bounded size")
    return json.loads(raw)


def kind(name, character, appearance=None):
    return f"{name}#{character}" + (f"#{appearance}" if appearance else "")


def guard(db, key, item, field="revision"):
    return {
        "ConditionCheck": {
            "TableName": db.name,
            "Key": records.encode(key),
            "ConditionExpression": f"{field} = :r",
            "ExpressionAttributeValues": records.encode({":r": item[field]}),
        }
    }


def get(db, game, character, name, identity, appearance=None):
    key = records.pointer(PREFIX, game, kind(name, character, appearance), identity)
    item = db.get_item(Key=key, ConsistentRead=True).get("Item")
    if not item:
        raise ValueError("Appearance, association or selection not found")
    return key, item, records.decode(item)


def story(value):
    if not isinstance(value, dict) or set(value) != {"sessionId", "eventId", "date"}:
        raise ValueError("Story timing requires explicit nullable fields")
    for field, maximum in (("sessionId", 96), ("eventId", 160), ("date", 160)):
        if value[field] is not None:
            text(value[field], maximum)
    return value


def character(game, identity):
    db = boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"])
    key = {"pk": f"GAME#{game}", "sk": f"CHARACTER#{identity}"}
    item = db.get_item(Key=key, ConsistentRead=True).get("Item")
    if (
        not item
        or item.get("schemaVersion") != 2
        or not item.get("detailsRevision")
        or item.get("entityType") != "Character"
        or item.get("id") != identity
        or item.get("gameId") != game
        or not isinstance(item.get("name"), str)
        or not item["name"].strip()
    ):
        raise ValueError("A migrated registered character is required")
    return db, key, item


def born_current(registered):
    """Only the trusted creation producer declares a current-contract empty genesis."""
    try:
        value = json.loads(registered.get("appearanceContractJson", "null"))
    except (TypeError, ValueError):
        return False
    return (
        isinstance(value, dict)
        and set(value) == {"schemaVersion", "origin"}
        and type(value["schemaVersion"]) is int
        and value["schemaVersion"] == 1
        and value["origin"] == "created-current"
    )


def require_current(game, cid):
    _, _, registered = character(game, cid)
    if not born_current(registered) and not browse_index.table().get_item(
        Key={"pk": f"{PREFIX}-migration#{game}#{cid}", "sk": "complete"}, ConsistentRead=True
    ).get("Item"):
        raise RuntimeError(
            "Appearance migration is incomplete; no legacy or mixed selection is shown"
        )
    return registered


def association_id(key):
    return hashlib.sha256(key.encode()).hexdigest()


def save(media, body, claims, name, *, maintenance_guards=(), maintenance_fields=None):
    fields = {
        "appearance": {"name", "description", "state", "developedFrom", "story"},
        "association": {"appearanceId", "assetKey"},
        "selection": {"appearanceId", "portraitKey", "modelKey", "sourceKey", "provenanceKey"},
        "activation": {"appearanceId", "selectionId", "story"},
    }
    if not isinstance(body, dict) or set(body) != COMMON | fields[name]:
        raise ValueError("Use a complete guarded appearance envelope")
    game, cid, identity = (slug(media, body[f]) for f in ("gameId", "characterId", "id"))
    records.revision(body["expectedRevision"], optional=True)
    records.revision(body["operationId"])
    text(body["reason"], 500)
    catalog, character_key, character_item = character(game, cid)
    db = browse_index.table()
    seal_key = {"pk": f"{PREFIX}-migration#{game}#{cid}", "sk": "complete"}
    seal = db.get_item(Key=seal_key, ConsistentRead=True).get("Item")
    if not seal and not maintenance_fields and not born_current(character_item):
        raise ValueError(
            "Complete this character's appearance migration before editing its artwork"
        )
    aid = slug(media, body["appearanceId"]) if name != "appearance" else identity
    record_kind = kind(name, cid, aid if name == "association" else None)
    fingerprint, replay = records.replay(db, PREFIX, game, record_kind, identity, body, media)
    if replay:
        return replay
    if name in {"association", "selection"} and body["expectedRevision"] is not None:
        raise ValueError("Associations and artwork selections are immutable; create a new record")
    if name == "activation" and identity != "current":
        raise ValueError("Activation changes the character's current pointer")
    record = {
        "schemaVersion": 1,
        "entityType": {
            "appearance": "CharacterAppearance",
            "association": "AppearanceAsset",
            "selection": "AppearanceSelection",
            "activation": "AppearanceActivation",
        }[name],
        "gameId": game,
        "characterId": cid,
        "id": identity,
    }
    guards = [guard(catalog, character_key, character_item, "detailsRevision")]
    if seal:
        guards.append(guard(db, seal_key, seal, "inventoryHash"))
    if name == "appearance":
        if body["state"] not in {"permanent", "temporary", "alternate", "unknown"}:
            raise ValueError("Invalid physical-state classification")
        predecessor = body["developedFrom"]
        current = records.decode(
            db.get_item(
                Key=records.pointer(PREFIX, game, record_kind, identity), ConsistentRead=True
            ).get("Item")
        )
        if current and predecessor != current["developedFrom"]:
            raise ValueError("An appearance's development parent is immutable; create a new state")
        if predecessor is not None:
            predecessor = slug(media, predecessor)
            if predecessor == identity:
                raise ValueError("An appearance cannot develop from itself")
            key, item, _ = get(db, game, cid, "appearance", predecessor)
            guards.append(guard(db, key, item))
        record.update(
            name=text(body["name"], 160),
            description=text(body["description"], 3000, empty=True),
            state=body["state"],
            developedFrom=predecessor,
            story=story(body["story"]),
        )
    else:
        key, item, appearance = get(db, game, cid, "appearance", aid)
        guards.append(guard(db, key, item))
        record.update(appearanceId=aid, appearanceRevision=appearance["revision"])
        if name == "association":
            asset_key = body["assetKey"]
            if not asset_library.valid_key(media, game, asset_key) or identity != association_id(
                asset_key
            ):
                raise ValueError("Asset association identity is its exact key's SHA-256")
            sources = indexed(game, [asset_key])
            source = sources.get(asset_key)
            asset = records.decode(source)
            if (
                not asset
                or asset.get("key") != asset_key
                or cid not in asset.get("metadata", {}).get("characterIds", [])
            ):
                raise ValueError("Asset must explicitly depict the same character")
            declared = asset.get("metadata", {}).get("extra", {}).get("appearanceId")
            if declared is not None and declared != aid:
                raise ValueError("Asset declares a different appearance")
            guards.append(
                guard(
                    db,
                    {"pk": browse_index.partition(game, "all"), "sk": asset_key},
                    source,
                    "observed",
                )
            )
            record["assetKey"] = asset_key
        elif name == "selection":
            portrait = body["portraitKey"]
            model = body["modelKey"]
            keys = [
                k
                for k in [portrait, model, body["sourceKey"], body["provenanceKey"]]
                if k is not None
            ]
            if not isinstance(portrait, str) or not all(
                asset_library.valid_key(media, game, k) for k in keys
            ):
                raise ValueError(
                    "Select an exact portrait and optional immutable model/source assets"
                )
            if model is None and (
                body["sourceKey"] is not None or body["provenanceKey"] is not None
            ):
                raise ValueError("Portrait-only selections cannot claim retained model sources")
            sources = indexed(game, list(dict.fromkeys(keys)))
            for asset_key in dict.fromkeys(keys):
                source = sources.get(asset_key)
                asset = records.decode(source)
                if not asset or asset.get("key") != asset_key:
                    raise ValueError("Selection source unavailable")
                association_key, association, _ = get(
                    db, game, cid, "association", association_id(asset_key), aid
                )
                guards.extend(
                    [
                        guard(db, association_key, association),
                        guard(
                            db,
                            {"pk": browse_index.partition(game, "all"), "sk": asset_key},
                            source,
                            "observed",
                        ),
                    ]
                )
            p = records.decode(sources[portrait])
            if (
                p.get("contentType") not in {"image/png", "image/jpeg", "image/webp", "image/avif"}
                or not 0 < p["size"] <= media.MAX_POSTER_BYTES
            ):
                raise ValueError("Select a bounded browser portrait")
            if model is not None:
                m = records.decode(sources[model])
                if (
                    not model.endswith(".glb")
                    or m.get("contentType") not in {"model/gltf-binary", "application/octet-stream"}
                    or not 0 < m["size"] <= media.MAX_MODEL_BYTES
                ):
                    raise ValueError("Select a bounded browser GLB")
                header = media.s3.get_object(
                    Bucket=media.BUCKET_NAME, Key=model, Range="bytes=0-11"
                )["Body"].read(12)
                if len(header) != 12 or struct.unpack("<4sII", header) != (b"glTF", 2, m["size"]):
                    raise ValueError("Selected model has an invalid GLB header")
            record.update(
                {f: body[f] for f in ("portraitKey", "modelKey", "sourceKey", "provenanceKey")}
            )
        else:
            selection_id = slug(media, body["selectionId"])
            selection_key, selection_item, selection = get(db, game, cid, "selection", selection_id)
            if selection["appearanceId"] != aid:
                raise ValueError("Selection belongs to another appearance")
            guards.append(guard(db, selection_key, selection_item))
            keys = list(
                dict.fromkeys(
                    k
                    for k in [
                        selection["portraitKey"],
                        selection["modelKey"],
                        selection["sourceKey"],
                        selection["provenanceKey"],
                    ]
                    if k is not None
                )
            )
            sources = indexed(game, keys)
            if any(k not in sources or records.decode(sources[k]).get("key") != k for k in keys):
                raise ValueError("Cannot promote a selection with unavailable immutable sources")
            for asset_key, source in sources.items():
                metadata = records.decode(source).get("metadata", {})
                if (metadata.get("characterIds") and cid not in metadata["characterIds"]) or (
                    metadata.get("extra", {}).get("appearanceId") not in {None, aid}
                ):
                    raise ValueError("Selected source now conflicts with this character appearance")
                guards.append(
                    guard(
                        db,
                        {"pk": browse_index.partition(game, "all"), "sk": asset_key},
                        source,
                        "observed",
                    )
                )
            record.update(
                selectionId=selection_id,
                selectionRevision=selection["revision"],
                appearanceRevision=selection["appearanceRevision"],
                story=story(body["story"]),
            )
            previous_activation = records.decode(
                db.get_item(
                    Key=records.pointer(PREFIX, game, record_kind, "current"), ConsistentRead=True
                ).get("Item")
            )
            record["previousAppearanceId"] = (
                previous_activation["appearanceId"] if previous_activation else None
            )
            record["activationKind"] = (
                "artwork-selection"
                if previous_activation and previous_activation["appearanceId"] == aid
                else "appearance-selection"
            )
    guards.extend(maintenance_guards)
    if maintenance_fields:
        record.update(maintenance_fields)
    return records.commit(db, PREFIX, record_kind, record, body, claims, fingerprint, guards, media)


def handle(event, media):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if "/character-appearance-migration/" in event["routeKey"]:
        return migration_handle(event, media, claims)
    if not claims.get("sub") or (
        event["routeKey"].startswith("POST ") and not authorized(claims, "MODEL_PUBLISHERS")
    ):
        return media._response(
            403, {"error": "Character appearance sign-in or publication capability required"}
        )
    routes = {
        "/character-appearances": "appearance",
        "/character-appearance-assets": "association",
        "/character-selections": "selection",
        "/character-appearance-current": "activation",
    }
    try:
        if event["routeKey"] == "GET /character-appearance-view":
            q = event.get("queryStringParameters") or {}
            game, cid = slug(media, q.get("gameId")), slug(media, q.get("characterId"))
            aid = slug(media, q["appearanceId"]) if q.get("appearanceId") else None
            sid = slug(media, q["selectionId"]) if q.get("selectionId") else None
            return media._response(200, view(media, game, cid, aid, sid))
        name = routes[event["routeKey"].split(" ")[-1]]
        if event["routeKey"].startswith("POST "):
            return save(media, parse_body(event), claims, name)
        q = event.get("queryStringParameters") or {}
        game, cid = slug(media, q.get("gameId")), slug(media, q.get("characterId"))
        character(game, cid)
        aid = slug(media, q.get("appearanceId")) if name == "association" else None
        return records.read(browse_index.table(), PREFIX, game, kind(name, cid, aid), q, media)
    except (ValueError, TypeError, KeyError, AttributeError):
        return media._response(
            400, {"error": "Invalid appearance, association, selection or revision"}
        )
    except (RuntimeError, ClientError):
        return media._response(
            503, {"error": "Appearance service unavailable; retry the exact operation"}
        )


def handler(event, _context):
    import index as media

    return handle(event, media)


def migration_handle(event, media, claims):
    import appearance_migration as migration

    if not authorized(claims, "ASSET_MIGRATORS"):
        return media._response(403, {"error": "Appearance migration capability required"})
    try:
        operation = event["routeKey"].rsplit("/", 1)[-1]
        body = (
            event.get("queryStringParameters") or {}
            if operation in {"inventory", "game-inventory"}
            else parse_body(event)
        )
        if not isinstance(body, dict):
            raise ValueError("Invalid migration envelope")
        if operation == "game-inventory":
            if set(body) - {"gameId", "cursor"} or "gameId" not in body:
                raise ValueError("Invalid inventory scope")
            game = slug(media, body["gameId"])
            catalog = boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"])
            if not catalog.get_item(Key={"pk": "GAMES", "sk": game}, ConsistentRead=True).get(
                "Item"
            ):
                raise ValueError("Register the game before migrating appearances")
            return media._response(200, migration.game_inventory(media, game, body.get("cursor")))
        if operation in {"inventory", "prepare", "verify"}:
            expected = {"gameId", "characterId"} | (
                {"sourceKey"} if operation == "prepare" else set()
            )
            if set(body) != expected:
                raise ValueError("Invalid migration fields")
            game, cid = slug(media, body["gameId"]), slug(media, body["characterId"])
            character(game, cid)
            if operation == "inventory":
                return media._response(200, {"sourceKeys": migration.inventory(media, game, cid)})
            if operation == "prepare":
                return media._response(
                    200, {"plan": migration.prepare(media, game, cid, body["sourceKey"])[0]}
                )
            proof = migration.verification(media, game, cid)
            seal = (
                browse_index.table()
                .get_item(
                    Key={"pk": f"{PREFIX}-migration#{game}#{cid}", "sk": "complete"},
                    ConsistentRead=True,
                )
                .get("Item")
            )
            if seal and seal["inventoryHash"] != proof["inventoryHash"]:
                raise ValueError("Completed migration inventory changed")
            return media._response(200, {"verification": proof, "completed": bool(seal)})
        if operation == "apply" and set(body) == {"plan"}:
            return media._response(200, migration.apply(media, body["plan"], claims["sub"]))
        if operation == "finalize" and set(body) == {"verification", "operationId"}:
            return migration.finalize(media, body["verification"], body["operationId"], claims)
        raise ValueError("Unsupported migration operation")
    except (ValueError, TypeError, KeyError, AttributeError):
        return media._response(
            409,
            {
                "error": "Migration source, completeness proof or conflict guard failed; inspect private evidence before retrying"
            },
        )
    except (RuntimeError, ClientError):
        return media._response(
            503, {"error": "Migration temporarily unavailable; retain the exact request and retry"}
        )


def resolve(game, cid, appearance_id=None, selection_id=None):
    """Resolve an exact pair; never substitute a current portrait/model independently."""
    _, _, registered = character(game, cid)
    db = browse_index.table()
    activation = None
    if appearance_id is None and selection_id is None:
        _, _, activation = get(db, game, cid, "activation", "current")
        appearance_id, selection_id = activation["appearanceId"], activation["selectionId"]
    if appearance_id is None or selection_id is None:
        raise ValueError("Historical viewing pins both appearance and selection")
    _, _, selection = get(db, game, cid, "selection", selection_id)
    if selection["appearanceId"] != appearance_id:
        raise ValueError("Selection belongs to another physical state")
    appearance_key = {
        "pk": f"{PREFIX}-history#{kind('appearance', cid)}#{game}#{appearance_id}",
        "sk": selection["appearanceRevision"],
    }
    appearance = records.decode(db.get_item(Key=appearance_key, ConsistentRead=True).get("Item"))
    if not appearance:
        raise ValueError("Pinned appearance revision unavailable")
    return registered, appearance, selection, activation


def view(media, game, cid, appearance_id=None, selection_id=None):
    db = browse_index.table()
    require_current(game, cid)
    if (
        appearance_id is None
        and selection_id is None
        and not db.get_item(
            Key=records.pointer(PREFIX, game, kind("activation", cid), "current"),
            ConsistentRead=True,
        ).get("Item")
    ):
        _, _, registered = character(game, cid)
        details = json.loads(registered.get("detailsJson", "{}"))
        return {
            "character": {
                "gameId": game,
                "id": cid,
                "name": registered.get("name", cid),
                "title": details.get("subtitle") or "Character",
                "summary": details.get("overview") or "",
            },
            "appearance": None,
            "selection": None,
            "activation": None,
            "poster": None,
            "model": None,
            "warnings": [],
        }
    registered, appearance, selection, activation = resolve(game, cid, appearance_id, selection_id)
    keys = [selection["portraitKey"]] + ([selection["modelKey"]] if selection["modelKey"] else [])
    sources = indexed(game, keys)
    assets = {k: records.decode(v) for k, v in sources.items()}
    warnings = []

    def selected(key, maximum, types):
        asset = assets.get(key)
        if (
            not asset
            or asset.get("key") != key
            or asset.get("contentType") not in types
            or not 0 < asset.get("size", 0) <= maximum
        ):
            warnings.append(
                {"key": key, "reason": "Pinned selected asset unavailable; no replacement chosen"}
            )
            return None
        return {
            "key": key,
            "size": asset["size"],
            "contentType": asset["contentType"],
            "url": media._signed_asset(key),
            "expiresIn": media.SIGNED_URL_TTL_SECONDS,
        }

    poster = selected(
        selection["portraitKey"],
        media.MAX_POSTER_BYTES,
        {"image/png", "image/jpeg", "image/webp", "image/avif"},
    )
    model = (
        selected(
            selection["modelKey"],
            media.MAX_MODEL_BYTES,
            {"model/gltf-binary", "application/octet-stream"},
        )
        if selection["modelKey"]
        else None
    )
    if model:
        model.update(
            cameraOrbit="0deg 75deg auto",
            fieldOfView="30deg",
            sourceRetained=selection["sourceKey"] is not None,
            provenanceRetained=selection["provenanceKey"] is not None,
        )
    details = json.loads(registered.get("detailsJson", "{}"))
    return {
        "character": {
            "gameId": game,
            "id": cid,
            "name": registered.get("name", cid),
            "title": details.get("subtitle") or "Character",
            "summary": details.get("overview") or "",
        },
        "appearance": appearance,
        "selection": selection,
        "activation": activation,
        "poster": poster,
        "model": model if poster else None,
        "warnings": warnings,
    }


def profile(media, game, cid):
    """Small modern profile projection for CLI/job consumers, never an S3 source lookup."""
    db = browse_index.table()
    registered = require_current(game, cid)
    if not db.get_item(
        Key=records.pointer(PREFIX, game, kind("activation", cid), "current"), ConsistentRead=True
    ).get("Item"):
        details = json.loads(registered.get("detailsJson", "{}"))
        document = {
            "schemaVersion": 2,
            "gameId": game,
            "id": cid,
            "name": registered["name"],
            "title": details.get("subtitle") or "Character",
            "summary": details.get("overview") or "",
            "appearanceId": None,
            "appearanceRevision": None,
            "selectionId": None,
            "selectionRevision": None,
            "model": {},
        }
        return None, json.dumps(document).encode(), document, None
    registered, _, selection, activation = resolve(game, cid)
    details = json.loads(registered.get("detailsJson", "{}"))
    document = {
        "schemaVersion": 2,
        "gameId": game,
        "id": cid,
        "name": registered["name"],
        "title": details.get("subtitle") or "Character",
        "summary": details.get("overview") or "",
        "appearanceId": selection["appearanceId"],
        "appearanceRevision": selection["appearanceRevision"],
        "selectionId": selection["id"],
        "selectionRevision": selection["revision"],
        "model": {
            "posterKey": selection["portraitKey"],
            **({"webKey": selection["modelKey"]} if selection["modelKey"] else {}),
            **({"sourceKey": selection["sourceKey"]} if selection["sourceKey"] else {}),
            **({"provenanceKey": selection["provenanceKey"]} if selection["provenanceKey"] else {}),
        },
    }
    return None, json.dumps(document).encode(), document, activation["revision"]


def all_records(game, cid, name, maximum=500):
    from boto3.dynamodb.conditions import Key

    args = {
        "KeyConditionExpression": Key("pk").eq(f"{PREFIX}#{kind(name, cid)}#{game}"),
        "ConsistentRead": True,
        "Limit": 100,
    }
    output = []
    while True:
        result = browse_index.table().query(**args)
        output.extend(records.decode(item) for item in result.get("Items", []))
        if len(output) > maximum:
            raise RuntimeError("Appearance metadata exceeds the supported complete reader limit")
        cursor = result.get("LastEvaluatedKey")
        if not cursor:
            return output
        args["ExclusiveStartKey"] = cursor


def versions(media, game, cid):
    """Metadata-only projection for semantic-version maintenance, not independent pairing."""
    current = profile(media, game, cid)
    selections = all_records(game, cid, "selection")
    db = browse_index.table()
    from boto3.dynamodb.conditions import Key

    pk = f"{PREFIX}-history#{kind('activation', cid)}#{game}#current"
    args = {"KeyConditionExpression": Key("pk").eq(pk), "ConsistentRead": True, "Limit": 100}
    activations = []
    while True:
        page = db.query(**args)
        activations.extend(records.decode(item) for item in page.get("Items", []))
        if len(activations) > 500:
            raise RuntimeError("Activation history exceeds the complete reader limit")
        cursor = page.get("LastEvaluatedKey")
        if not cursor:
            break
        args["ExclusiveStartKey"] = cursor
    selected_ids = {a["selectionId"] for a in activations}
    selections = [s for s in selections if s["id"] in selected_ids or s.get("migrationSource")]
    selected_at = {
        s["id"]: min(
            (a["updatedAt"] for a in activations if a["selectionId"] == s["id"]), default=None
        )
        for s in selections
    }
    selections.sort(
        key=lambda s: (s.get("sourceCapturedAt") or selected_at[s["id"]] or s["updatedAt"], s["id"])
    )
    keys = list(
        dict.fromkeys(k for s in selections for k in (s["modelKey"], s["portraitKey"]) if k)
    )
    sources = {}
    for offset in range(0, len(keys), 100):
        sources.update(indexed(game, keys[offset : offset + 100]))
    assets = {k: records.decode(v) for k, v in sources.items()}
    output = {"models": [], "portraits": []}
    for field, plural in (("modelKey", "models"), ("portraitKey", "portraits")):
        seen = set()
        for selection in selections:
            key = selection[field]
            if not key or key in seen:
                continue
            seen.add(key)
            asset = assets.get(key)
            output[plural].append(
                {
                    "key": key,
                    "available": bool(asset and asset.get("key") == key),
                    "current": bool(
                        current
                        and key
                        == current[2]["model"].get("webKey" if field == "modelKey" else "posterKey")
                    ),
                    "selectedAt": selected_at[selection["id"]],
                    "reason": selection["reason"],
                    "appearanceId": selection["appearanceId"],
                    "selectionId": selection["id"],
                }
            )
        output[plural].reverse()
    return {"schemaVersion": 2, "gameId": game, "characterId": cid, **output}


def history(media, game, cid):
    """Bounded official metadata only; signed links belong to an exact selected view."""
    from boto3.dynamodb.conditions import Key

    current = profile(media, game, cid)
    db = browse_index.table()
    args = {
        "KeyConditionExpression": Key("pk").eq(
            f"{PREFIX}-history#{kind('activation', cid)}#{game}#current"
        ),
        "ConsistentRead": True,
        "Limit": 100,
    }
    activations = []
    while True:
        page = db.query(**args)
        activations.extend(records.decode(item) for item in page.get("Items", []))
        if len(activations) > 500:
            raise RuntimeError("Official appearance history exceeds the complete reader limit")
        if not page.get("LastEvaluatedKey"):
            break
        args["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    activations.sort(key=lambda record: (record["updatedAt"], record["revision"]), reverse=True)
    selected_ids = {a["selectionId"] for a in activations}
    selections = [
        s
        for s in all_records(game, cid, "selection")
        if s["id"] in selected_ids or s.get("migrationSource")
    ]
    appearances = [
        a
        for a in all_records(game, cid, "appearance")
        if a["id"] in {s["appearanceId"] for s in selections}
    ]
    return {
        "schemaVersion": 2,
        "gameId": game,
        "characterId": cid,
        "current": current[2]["selectionId"] if current else None,
        "activationRevision": current[3] if current else None,
        "appearances": appearances,
        "selections": selections,
        "activations": activations,
    }


def publish(media, event, asset_kind):
    """Existing publication commands now create a candidate pair and CAS its activation."""
    import binascii

    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "MODEL_PUBLISHERS"):
        return media._response(403, {"error": "Character artwork publication capability required"})
    try:
        body = parse_body(event)
        required = {"gameId", "characterId", "expectedRevision", "reason"} | (
            {"portraitKey"}
            if asset_kind == "portrait"
            else {"webKey", "sourceKey", "provenanceKey"}
        )
        if not isinstance(body, dict) or set(body) != required:
            raise ValueError("Use the complete guarded artwork publication envelope")
        game, cid = slug(media, body["gameId"]), slug(media, body["characterId"])
        records.revision(body["expectedRevision"])
        text(body["reason"], 500)
        fingerprint = hashlib.sha256(
            json.dumps(body, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        db = browse_index.table()
        receipt = db.get_item(
            Key={
                "pk": f"{PREFIX}-ops#{kind('activation', cid)}#{game}#current",
                "sk": fingerprint[32:],
            },
            ConsistentRead=True,
        ).get("Item")
        if receipt:
            current = profile(media, game, cid)
            return media._response(
                200,
                {
                    "profile": current[2],
                    "revision": current[3],
                    "operationRevision": receipt["revision"],
                    "operationSelectionId": "artwork-" + fingerprint[:32],
                    "replayed": True,
                },
            )
        registered, appearance, selected, activation = resolve(game, cid)
        if activation["revision"] != body["expectedRevision"]:
            return media._response(
                409, {"error": "Character appearance changed; inspect before publishing"}
            )
        fields = {
            field: selected[field]
            for field in ("portraitKey", "modelKey", "sourceKey", "provenanceKey")
        }
        if asset_kind == "portrait":
            fields["portraitKey"] = body["portraitKey"]
        else:
            fields.update(
                modelKey=body["webKey"],
                sourceKey=body["sourceKey"],
                provenanceKey=body["provenanceKey"],
            )
            if fields["sourceKey"] is None or not all(
                asset_library.valid_key(media, game, key)
                for key in [fields["modelKey"], fields["sourceKey"]]
                + ([fields["provenanceKey"]] if fields["provenanceKey"] else [])
            ):
                raise ValueError(
                    "New model publication requires retained same-game editable source"
                )
            if not isinstance(fields["modelKey"], str) or not fields["modelKey"].endswith(".glb"):
                raise ValueError("Browser model must be a GLB")
            sources = indexed(game, [fields["modelKey"]])
            item = sources.get(fields["modelKey"])
            if not item:
                raise ValueError("Indexed model unavailable")
            size = records.decode(item)["size"]
            header = media.s3.get_object(
                Bucket=media.BUCKET_NAME, Key=fields["modelKey"], Range="bytes=0-11"
            )["Body"].read(12)
            if len(header) != 12 or struct.unpack("<4sII", header) != (b"glTF", 2, size):
                raise ValueError("Invalid GLB header or declared size")
        base = {
            "gameId": game,
            "characterId": cid,
            "expectedRevision": None,
            "reason": body["reason"],
        }
        aid = selected["appearanceId"]
        db = browse_index.table()
        for key in dict.fromkeys(k for k in fields.values() if k is not None):
            ident = association_id(key)
            pointer = records.pointer(PREFIX, game, kind("association", cid, aid), ident)
            if not db.get_item(Key=pointer, ConsistentRead=True).get("Item"):
                association = {
                    **base,
                    "id": ident,
                    "appearanceId": aid,
                    "assetKey": key,
                    "operationId": hashlib.sha256((fingerprint + ident).encode()).hexdigest()[:32],
                }
                result = save(media, association, claims, "association")
                if result["statusCode"] != 200:
                    return result
        pair_id = "artwork-" + fingerprint[:32]
        pair = {
            **base,
            "id": pair_id,
            "appearanceId": aid,
            **fields,
            "operationId": fingerprint[:32],
        }
        result = save(media, pair, claims, "selection")
        if result["statusCode"] != 200:
            return result
        current = {
            **base,
            "id": "current",
            "appearanceId": aid,
            "selectionId": pair_id,
            "expectedRevision": body["expectedRevision"],
            "operationId": fingerprint[32:],
            "story": activation["story"],
        }
        result = save(media, current, claims, "activation")
        if result["statusCode"] != 200:
            return result
        updated = profile(media, game, cid)
        return media._response(
            200, {"profile": updated[2], "revision": updated[3], "selectionId": pair_id}
        )
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeDecodeError, binascii.Error):
        return media._response(
            422, {"error": "Invalid artwork, appearance association or publication revision"}
        )
    except (RuntimeError, ClientError):
        return media._response(
            503, {"error": "Artwork publication unavailable; retain and retry the exact request"}
        )


def initialize(media, body, actor):
    """Create-only first artwork; never bypass a character's legacy migration."""
    import appearance_migration as migration

    game, cid = slug(media, body["gameId"]), slug(media, body["characterId"])
    character(game, cid)
    portrait = body["portraitKey"]
    if not asset_library.valid_key(media, game, portrait):
        raise ValueError("Invalid initial portrait")
    source = indexed(game, [portrait]).get(portrait)
    asset = records.decode(source)
    if not asset or cid not in asset.get("metadata", {}).get("characterIds", []):
        raise ValueError("Initial portrait must explicitly identify this character")
    fingerprint = hashlib.sha256(
        json.dumps(body, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    aid = slug(media, asset.get("metadata", {}).get("extra", {}).get("appearanceId") or "initial")
    db = browse_index.table()
    claims = {"sub": actor}
    final_operation = fingerprint[32:]
    receipt = db.get_item(
        Key={"pk": f"{PREFIX}-ops#{kind('activation', cid)}#{game}#current", "sk": final_operation},
        ConsistentRead=True,
    ).get("Item")
    if receipt:
        return {
            "profile": profile(media, game, cid),
            "operationRevision": receipt["revision"],
            "replayed": True,
            "operationSelectionId": "initial-" + fingerprint[:32],
        }
    if db.get_item(
        Key=records.pointer(PREFIX, game, kind("activation", cid), "current"), ConsistentRead=True
    ).get("Item"):
        raise ValueError(
            "Artwork is already selected; use a guarded revision or explicit appearance activation"
        )
    seal_key = {"pk": f"{PREFIX}-migration#{game}#{cid}", "sk": "complete"}
    if not born_current(character(game, cid)[2]) and not db.get_item(
        Key=seal_key, ConsistentRead=True
    ).get("Item"):
        if migration.inventory(media, game, cid):
            raise ValueError("Retained legacy artwork requires the all-game appearance migration")
        proof = migration.verification(media, game, cid)
        result = migration.finalize(
            media,
            proof,
            hashlib.sha256((fingerprint + "empty-history").encode()).hexdigest()[:32],
            claims,
        )
        if result["statusCode"] != 200:
            raise RuntimeError("Could not complete empty artwork history")
    base = {
        "gameId": game,
        "characterId": cid,
        "expectedRevision": None,
        "reason": "Initialize explicitly selected portrait; story state unknown",
    }
    operations = [
        (
            "appearance",
            {
                **base,
                "id": aid,
                "name": "Initial selected artwork",
                "description": "Physical state and story timing were not provided.",
                "state": "unknown",
                "developedFrom": None,
                "story": {"sessionId": None, "eventId": None, "date": None},
                "operationId": hashlib.sha256((fingerprint + "appearance").encode()).hexdigest()[
                    :32
                ],
            },
        ),
        (
            "association",
            {
                **base,
                "id": association_id(portrait),
                "appearanceId": aid,
                "assetKey": portrait,
                "operationId": hashlib.sha256((fingerprint + "association").encode()).hexdigest()[
                    :32
                ],
            },
        ),
        (
            "selection",
            {
                **base,
                "id": "initial-" + fingerprint[:32],
                "appearanceId": aid,
                "portraitKey": portrait,
                "modelKey": None,
                "sourceKey": None,
                "provenanceKey": None,
                "operationId": fingerprint[:32],
            },
        ),
        (
            "activation",
            {
                **base,
                "id": "current",
                "appearanceId": aid,
                "selectionId": "initial-" + fingerprint[:32],
                "story": {"sessionId": None, "eventId": None, "date": None},
                "operationId": final_operation,
            },
        ),
    ]
    for name, envelope in operations:
        result = save(media, envelope, claims, name)
        if result["statusCode"] != 200:
            raise ValueError("Initial artwork changed concurrently; inspect before retrying")
    return {
        "profile": profile(media, game, cid),
        "replayed": False,
        "operationSelectionId": "initial-" + fingerprint[:32],
    }
