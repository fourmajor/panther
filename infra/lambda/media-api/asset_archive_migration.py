"""Authenticated all-game archive-v1 reference backfill; no source bytes are modified."""

import json
import scene_inputs
import os
import time
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from access_policy import authorized
import asset_archive as archive


def rows(table, partition):
    result = []
    cursor = None
    for _ in range(10):
        args = {
            "KeyConditionExpression": Key("pk").eq(partition),
            "ConsistentRead": True,
            "Limit": 100,
        }
        if cursor:
            args["ExclusiveStartKey"] = cursor
        page = table.query(**args)
        result.extend(page.get("Items", []))
        cursor = page.get("LastEvaluatedKey")
        if not cursor:
            return result
    raise RuntimeError("Archive migration inventory exceeds its bounded page envelope")


def inventory(game):
    table = archive.db()
    catalog = boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"])
    refs = []
    for character in rows(catalog, f"GAME#{game}"):
        if character.get("entityType") != "Character":
            continue
        cid = character["id"]
        if (
            character.get("schemaVersion") != 2
            or not character.get("detailsRevision")
            or not character.get("detailsJson")
        ):
            raise RuntimeError(
                "Character facts migration must be completed before archive inventory"
            )
        import character_appearances

        if not character_appearances.born_current(character) and not table.get_item(
            Key={"pk": f"character-looks-migration#{game}#{cid}", "sk": "complete"},
            ConsistentRead=True,
        ).get("Item"):
            raise RuntimeError(
                "Character appearance migration must be completed before archive inventory"
            )
        details = json.loads(character.get("detailsJson", "{}"))
        keys = [details.get("thumbnailAssetKey")] if details.get("thumbnailAssetKey") else []
        refs.append({"owner": f"character:{cid}", "keys": keys})
        pointer = {"pk": f"character-looks#activation#{cid}#{game}", "sk": "current"}
        activation = table.get_item(Key=pointer, ConsistentRead=True).get("Item")
        if activation:
            active = json.loads(activation["payload"])
            selection = table.get_item(
                Key={"pk": f"character-looks#selection#{cid}#{game}", "sk": active["selectionId"]},
                ConsistentRead=True,
            ).get("Item")
            if not selection:
                raise RuntimeError("Current appearance has no selected immutable revision")
            selected = json.loads(selection["payload"])
            keys = [
                selected.get(field)
                for field in ("portraitKey", "modelKey", "sourceKey", "provenanceKey")
                if selected.get(field)
            ]
            refs.append({"owner": f"appearance:{cid}", "keys": keys})
    for episode in rows(table, f"episode-scenes-v1#episode#{game}"):
        value = json.loads(episode["payload"])
        for scene in rows(table, f"episode-scenes-v1#scene#{value['id']}#{game}"):
            value_scene = json.loads(scene["payload"])
            refs.append(
                {
                    "owner": f"scene:{value['id']}:{value_scene['id']}",
                    "keys": [
                        value_scene[field]
                        for field in ("mapAssetKey", "selectedOutputKey")
                        if value_scene.get(field)
                    ] + scene_inputs.asset_keys(value_scene),
                }
            )
    editorial = boto3.resource("dynamodb").Table(os.environ["EDITORIAL_TABLE"])
    for job in rows(editorial, "RUNS"):
        if job.get("gameId") != game:
            continue
        sources = job.get("rawSources") or ([job["raw"]] if job.get("raw") else [])
        keys = [ref["key"] for ref in [*sources, *job.get("selectedContext", [])]]
        if job.get("selectedMap"):
            keys.append(job["selectedMap"]["key"])
        for character in job.get("selectedCharacters", []):
            keys.extend(ref["key"] for ref in character.get("appearanceAssets", []))
            if character.get("details", {}).get("thumbnailAssetKey"):
                keys.append(character["details"]["thumbnailAssetKey"])
        refs.append(
            {
                "owner": "editorial:" + job["jobId"],
                "keys": sorted(set(keys)),
                "active": {"table": editorial.name, "pk": "RUNS", "sk": job["jobId"]},
            }
        )
    import asset_job_references

    refs.extend(
        asset_job_references.snapshot(
            game,
            boto3.resource("dynamodb").Table(os.environ["MODEL_JOBS_TABLE"]),
            boto3.resource("dynamodb").Table(os.environ["ASSET_GENERATION_TABLE"]),
        )
    )
    if any(
        not isinstance(key, str) or not key.startswith(f"games/{game}/assets/")
        for ref in refs
        for key in ref["keys"]
    ):
        raise RuntimeError(
            "Current asset reference inventory contains an invalid or foreign source"
        )
    if len(refs) > 1000:
        raise RuntimeError("Too many current references for bounded archive verification")
    return sorted(refs, key=lambda ref: ref["owner"])


def migrate(body):
    import index as media

    table = archive.db()
    game = body.get("gameId")
    mode = body.get("mode")
    if mode == "activate":
        catalog = boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"])
        games = rows(catalog, "GAMES")
        if not games:
            raise RuntimeError("No games were verified")
        for item in games:
            game = item["id"]
            if not table.get_item(
                Key={"pk": "asset-archives-v1#verified", "sk": game}, ConsistentRead=True
            ).get("Item"):
                raise RuntimeError("Every game must be verified before archive activation")
        table.put_item(
            Item={
                "pk": "asset-archives-v1#catalog",
                "sk": "ready",
                "schemaVersion": 1,
                "verifiedAt": time.time_ns(),
            }
        )
        return {"schemaVersion": 1, "status": "active", "games": len(games)}
    if not media._valid_slug(game) or mode not in {"dry-run", "apply", "verify"}:
        raise ValueError("Choose game and dry-run, apply or verify")
    if mode == "apply":
        table.delete_item(Key={"pk": "asset-archives-v1#verified", "sk": game})
    before = (
        table.get_item(Key=archive.epoch_key(game), ConsistentRead=True)
        .get("Item", {})
        .get("revision", 0)
    )
    refs = inventory(game)
    after = (
        table.get_item(Key=archive.epoch_key(game), ConsistentRead=True)
        .get("Item", {})
        .get("revision", 0)
    )
    if before != after:
        raise RuntimeError("Current references changed during inventory; retry migration")
    if mode == "apply":
        revision = before
        for ref in refs:
            item = {
                "pk": f"asset-references-v1#{game}",
                "sk": ref["owner"],
                "keys": sorted(set(ref["keys"])),
                "schemaVersion": 1,
            }
            if ref.get("active"):
                item["active"] = ref["active"]
            update = {
                "TableName": table.name,
                "Key": archive.encode(archive.epoch_key(game)),
                "UpdateExpression": "SET revision = :next",
                "ConditionExpression": "revision = :old"
                if revision
                else "attribute_not_exists(revision)",
                "ExpressionAttributeValues": archive.encode(
                    {":next": revision + 1, **({":old": revision} if revision else {})}
                ),
            }
            boto3.client("dynamodb").transact_write_items(
                TransactItems=[
                    {"Update": update},
                    {"Put": {"TableName": table.name, "Item": archive.encode(item)}},
                ]
            )
            revision += 1
    elif mode == "verify":
        for ref in refs:
            row = table.get_item(
                Key={"pk": f"asset-references-v1#{game}", "sk": ref["owner"]}, ConsistentRead=True
            ).get("Item")
            if (
                not row
                or row.get("keys") != sorted(set(ref["keys"]))
                or row.get("active") != ref.get("active")
            ):
                raise RuntimeError("Reference projection differs from current application records")
        actual = rows(table, f"asset-references-v1#{game}")
        if {row["sk"] for row in actual} != {ref["owner"] for ref in refs}:
            raise RuntimeError("Reference projection contains unexpected owners")
        check = {
            "TableName": table.name,
            "Key": archive.encode(archive.epoch_key(game)),
            "ConditionExpression": "revision = :old" if after else "attribute_not_exists(revision)",
        }
        if after:
            check["ExpressionAttributeValues"] = archive.encode({":old": after})
        boto3.client("dynamodb").transact_write_items(
            TransactItems=[
                {"ConditionCheck": check},
                {
                    "Put": {
                        "TableName": table.name,
                        "Item": archive.encode(
                            {
                                "pk": "asset-archives-v1#verified",
                                "sk": game,
                                "schemaVersion": 1,
                                "verifiedAt": time.time_ns(),
                            }
                        ),
                    }
                },
            ]
        )
    return {
        "schemaVersion": 1,
        "gameId": game,
        "mode": mode,
        "references": len(refs),
        "status": "verified" if mode == "verify" else "prepared",
    }


def handler(event, _context):
    import index as media

    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "ASSET_MIGRATORS"):
        return media._response(403, {"error": "Archive maintenance access required"})
    try:
        return media._response(200, migrate(json.loads(event.get("body") or "{}")))
    except ValueError as error:
        return media._response(400, {"error": str(error)})
    except RuntimeError as error:
        return media._response(409, {"error": str(error)})
    except ClientError:
        return media._response(
            409, {"error": "Current references changed; rerun apply and verify before activation."}
        )
