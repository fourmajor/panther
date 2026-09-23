"""Version-1 materialized browsing catalog. S3 remains authoritative; never scan on reads."""

import base64
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

SECTIONS = ("all", "audio", "transcripts", "videos")


class IndexNotReady(RuntimeError):
    pass


def table():
    return boto3.resource("dynamodb").Table(os.environ["ASSET_BROWSE_TABLE"])


def partition(game, section):
    return f"v1#{game}#{section}"


def sections(asset):
    result = {"all"}
    mime, name, kind = asset["contentType"], asset["name"].lower(), asset["kind"]
    source_chunk = kind == "recording" and re.fullmatch(r"part-\d{4}\.flac", name)
    listening_derivative = kind in {"recording-playback", "recording-playback-manifest"}
    if asset.get("recording") or (not source_chunk and not listening_derivative and (
            mime.startswith("audio/") or name.endswith((".flac", ".wav", ".mp3", ".m4a", ".ogg")))):
        result.add("audio")
    if kind in {"transcript", "raw-transcript", "corrected-transcript", "edited-transcript"}:
        result.add("transcripts")
    if mime.startswith("video/") or name.endswith((".mp4", ".webm", ".mov", ".m4v", ".ogv")) or kind == "movie-review-plan":
        result.add("videos")
    return result


def refresh(media, reference, *, write=True):
    """Read current bytes, not an old event version. CAS prevents older workers replacing newer reads."""
    import asset_library
    import storage_layout
    observed = time.time_ns()
    game = storage_layout.parts(reference)["game"]
    db = table() if write else None
    # Capture the CAS revision BEFORE reading S3. Even with clock skew, a worker
    # whose source read overlaps a newer commit cannot replace that commit.
    previous = db.get_item(Key={"pk": partition(game, "all"), "sk": reference}, ConsistentRead=True).get("Item") if write else None
    asset = asset_library.describe(media, game, reference)
    payload = json.dumps(asset, separators=(",", ":"), allow_nan=False)
    if len(payload.encode()) > 350_000:
        raise ValueError("Catalog record exceeds index limit; no provenance was discarded")
    if not write:
        return asset
    # A per-asset revision gate and all section memberships change atomically.
    from boto3.dynamodb.types import TypeSerializer
    serializer = TypeSerializer()
    def encode(item):
        return {k: serializer.serialize(v) for k, v in item.items()}
    selected = sections(asset)
    operations = []
    for section in SECTIONS:
        key = {"pk": partition(game, section), "sk": reference}
        if section in selected:
            put = {"TableName": db.name, "Item": encode({**key, "payload": payload, "observed": observed})}
            if section == "all":
                put["ConditionExpression"] = "observed = :previous" if previous else "attribute_not_exists(pk)"
                if previous:
                    put["ExpressionAttributeValues"] = encode({":previous": previous["observed"]})
            operations.append({"Put": put})
        else:
            operations.append({"Delete": {"TableName": db.name, "Key": encode(key)}})
    try:
        # Use a low-level client: resource clients apply an additional serializer.
        boto3.client("dynamodb").transact_write_items(TransactItems=operations)
    except ClientError as error:
        if error.response["Error"]["Code"] == "TransactionCanceledException":
            raise RuntimeError("Concurrent index update; retry by rereading current source") from error
        raise
    return asset


def page(game, section, cursor=None):
    if section not in SECTIONS:
        raise ValueError("Invalid asset section")
    if not table().get_item(Key={"pk": "v1#catalog", "sk": "ready"}, ConsistentRead=True).get("Item"):
        raise IndexNotReady("The catalog upgrade is being prepared. No assets have been removed; please retry shortly.")
    pk = partition(game, section)
    args = {"KeyConditionExpression": Key("pk").eq(pk), "Limit": 100, "ConsistentRead": True}
    if cursor:
        try:
            key = json.loads(base64.urlsafe_b64decode(cursor))
            if set(key) != {"pk", "sk"} or key["pk"] != pk or not isinstance(key["sk"], str):
                raise ValueError()
            args["ExclusiveStartKey"] = key
        except (ValueError, TypeError):
            raise ValueError("Invalid or foreign asset cursor") from None
    result = table().query(**args)
    next_key = result.get("LastEvaluatedKey")
    assets = [json.loads(item["payload"]) for item in result.get("Items", [])]
    if section == "transcripts":
        def unpaired(asset):
            if not asset["key"].endswith(".md"):
                return True
            counterpart = table().get_item(Key={"pk": partition(game, "all"),
                "sk": asset["key"][:-3] + ".json"}, ConsistentRead=True).get("Item")
            return not counterpart or json.loads(counterpart["payload"])["kind"] != asset["kind"]
        assets = [asset for asset in assets if unpaired(asset)]
    return {"assets": assets,
            "cursor": base64.urlsafe_b64encode(json.dumps(next_key).encode()).decode() if next_key else None,
            "catalogVersion": 1}


def event_handler(event, _context):
    import index as media
    detail = event.get("detail", {})
    key = detail.get("object", {}).get("key", "")
    if detail.get("bucket", {}).get("name") != media.BUCKET_NAME or "/content/" not in key:
        return
    reference = media.s3.reference_for(key)
    refresh(media, reference)


def rebuild_handler(event, _context):
    """Bounded, authenticated dry-run/apply/verify, also used for reconciliation."""
    import index as media
    import storage_layout
    from access_policy import authorized
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "ASSET_MIGRATORS"):
        return media._response(403, {"error": "Owner sign-in required for index maintenance"})
    try:
        body = json.loads(event.get("body") or "{}")
        if not isinstance(body, dict):
            raise ValueError("Invalid index maintenance request")
        game, mode = body.get("gameId"), body.get("mode", "dry-run")
        if mode == "activate":
            # Discover physical game prefixes, not a caller-selected subset. Empty games need no backfill.
            pages = media.raw_s3.get_paginator("list_objects_v2").paginate(
                Bucket=media.BUCKET_NAME, Prefix="games/", Delimiter="/")
            for result in pages:
                for item in result.get("CommonPrefixes", []):
                    found = item["Prefix"].split("/")[1]
                    if not table().get_item(Key={"pk": "v1#verified", "sk": found}, ConsistentRead=True).get("Item"):
                        raise ValueError("All games must complete index verification before activation")
            table().put_item(Item={"pk": "v1#catalog", "sk": "ready", "activatedAt": time.time_ns()})
            return media._response(200, {"schemaVersion": 1, "status": "active"})
        if not media._valid_slug(game) or len(game) > 96 or mode not in {"dry-run", "apply", "verify"}:
            raise ValueError("Invalid index maintenance request")
        args = {"Bucket": media.BUCKET_NAME, "Prefix": f"games/{game}/catalog/assets/", "MaxKeys": 20}
        mismatches = 0
        if mode == "verify" and not body.get("cursor"):
            table().delete_item(Key={"pk": "v1#verified", "sk": game})
        if body.get("cursor"):
            token = json.loads(base64.urlsafe_b64decode(body["cursor"]))
            if token["gameId"] != game or token["mode"] != mode:
                raise ValueError("Wrong maintenance cursor scope")
            args["ContinuationToken"] = token["token"]
            mismatches = token.get("mismatches", 0)
        result = media.raw_s3.list_objects_v2(**args)

        def inspect(obj):
            ref = obj["Key"][:-5].replace("/catalog/assets/", "/assets/", 1)
            storage_layout.parts(ref)
            try:
                asset = refresh(media, ref, write=mode == "apply")
            except ClientError as error:
                from asset_storage import missing
                if missing(error):
                    return {"key": ref, "status": "unpublished-reservation"}
                raise
            if mode == "verify":
                import asset_metadata
                try:
                    asset_metadata.validate_version(asset.get("metadata", {}).get("extra", {}).get("version"), ref)
                except ValueError:
                    return {"key": ref, "status": "mismatch", "reason": "Missing or invalid semantic asset version"}
                for section in SECTIONS:
                    item = table().get_item(Key={"pk": partition(game, section), "sk": ref}, ConsistentRead=True).get("Item")
                    if (section in sections(asset)) != bool(item) or item and json.loads(item["payload"]) != asset:
                        return {"key": ref, "status": "mismatch"}
            return {"key": ref, "status": "verified" if mode == "verify" else "indexed" if mode == "apply" else "ready"}

        with ThreadPoolExecutor(max_workers=8) as pool:
            records = list(pool.map(inspect, result.get("Contents", [])))
        token = result.get("NextContinuationToken")
        mismatches += sum(r["status"] == "mismatch" for r in records)
        cursor = base64.urlsafe_b64encode(json.dumps({"gameId": game, "mode": mode, "token": token,
            "mismatches": mismatches}).encode()).decode() if token else None
        if mode == "verify" and not token and not mismatches:
            table().put_item(Item={"pk": "v1#verified", "sk": game, "verifiedAt": time.time_ns()})
        return media._response(200, {"schemaVersion": 1, "gameId": game, "mode": mode, "records": records, "cursor": cursor})
    except (ValueError, KeyError, TypeError) as error:
        return media._response(400, {"error": str(error)})
