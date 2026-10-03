"""Explicit private series/seasons/episodes; no inference or source-media writes."""

import json
import os

import boto3
from botocore.exceptions import ClientError

from access_policy import authorized
import asset_library
import asset_metadata
import browse_index
from novel_library import indexed, slug, text
import organization_records as records
from video_collections import is_video

PREFIX = "tv-library"
COMMON = {"gameId", "id", "title", "synopsis", "expectedRevision", "operationId", "reason"}


def positive(value, maximum=10000):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("Invalid season or episode number")
    return value


def finished(asset):
    return (
        not asset.get("lineageWarning")
        and not asset_metadata.internal(asset.get("kind", ""))
        and (asset.get("metadata", {}).get("extra", {}).get("relationshipRole") == "finished")
    )


def save(media, body, claims, kind):
    extra = (
        {"seasons"}
        if kind == "series"
        else {
            "seriesId",
            "seasonId",
            "number",
            "status",
            "cuts",
            "selectedCutId",
            "posterAssetKey",
            "captionAssetKeys",
            "credits",
            "sourceAssetKeys",
            "relatedAssetKeys",
            "preparationAssetKeys",
        }
    )
    if not isinstance(body, dict) or set(body) != COMMON | extra:
        raise ValueError("Expected a complete guarded TV organization envelope")
    game, identity = slug(media, body["gameId"]), slug(media, body["id"])
    if (
        not boto3.resource("dynamodb")
        .Table(os.environ["CATALOG_TABLE"])
        .get_item(Key={"pk": "GAMES", "sk": game}, ConsistentRead=True)
        .get("Item")
    ):
        raise ValueError("Register the game first")
    records.revision(body["expectedRevision"], optional=True)
    records.revision(body["operationId"])
    reason = text(body["reason"], 500)
    record = {
        "schemaVersion": 1,
        "entityType": "TVSeries" if kind == "series" else "TVEpisode",
        "gameId": game,
        "id": identity,
        "title": text(body["title"], 160),
        "synopsis": text(body["synopsis"], 3000, empty=True),
    }
    db = browse_index.table()
    fingerprint, replay = records.replay(db, PREFIX, game, kind, identity, body, media)
    if replay:
        return replay
    guards = []
    if kind == "series":
        seasons = body["seasons"]
        if not isinstance(seasons, list) or not 1 <= len(seasons) <= 30:
            raise ValueError("Choose 1–30 explicit seasons")
        ids, numbers, normalized = set(), set(), []
        for season in seasons:
            if not isinstance(season, dict) or set(season) != {"id", "number", "title", "synopsis"}:
                raise ValueError("Invalid season")
            sid, number = slug(media, season["id"]), positive(season["number"])
            if sid in ids or number in numbers:
                raise ValueError("Duplicate season identity or number")
            ids.add(sid)
            numbers.add(number)
            normalized.append(
                {
                    "id": sid,
                    "number": number,
                    "title": text(season["title"], 160),
                    "synopsis": text(season["synopsis"], 1000, empty=True),
                }
            )
        record["seasons"] = sorted(normalized, key=lambda s: s["number"])
        current = records.decode(
            db.get_item(Key=records.pointer(PREFIX, game, kind, identity), ConsistentRead=True).get(
                "Item"
            )
        )
        if current and any(s["id"] not in ids for s in current["seasons"]):
            raise ValueError(
                "Preserve existing seasons; deleting their organization requires a separate migration"
            )
    else:
        series_id, season_id = slug(media, body["seriesId"]), slug(media, body["seasonId"])
        series_key = records.pointer(PREFIX, game, "series", series_id)
        series = db.get_item(Key=series_key, ConsistentRead=True).get("Item")
        if not series or not any(s["id"] == season_id for s in records.decode(series)["seasons"]):
            raise ValueError("Choose an existing same-game series and season")
        if body["status"] not in {"draft", "approved"}:
            raise ValueError("Approval is private, not public publication")
        cuts = body["cuts"]
        if not isinstance(cuts, list) or not 1 <= len(cuts) <= 10:
            raise ValueError("Choose 1–10 explicitly labeled immutable cuts")
        ids, cut_keys, normalized = set(), [], []
        for cut in cuts:
            if not isinstance(cut, dict) or set(cut) != {
                "id",
                "title",
                "assetKey",
                "durationSeconds",
                "durationEvidence",
            }:
                raise ValueError("Invalid cut")
            cid = slug(media, cut["id"])
            if cid in ids:
                raise ValueError("Duplicate cut identity")
            ids.add(cid)
            cut_keys.append(cut["assetKey"])
            duration, evidence = cut["durationSeconds"], cut["durationEvidence"]
            if duration is not None:
                if type(duration) not in (int, float) or not 0 < duration <= 24 * 3600:
                    raise ValueError("Invalid observed runtime")
                evidence = text(evidence, 500)
            elif evidence is not None:
                raise ValueError("Unknown duration has no measured evidence")
            normalized.append(
                {
                    "id": cid,
                    "title": text(cut["title"], 120),
                    "assetKey": cut["assetKey"],
                    "durationSeconds": duration,
                    "durationEvidence": evidence,
                }
            )
        if len(set(cut_keys)) != len(cut_keys) or body["selectedCutId"] not in ids:
            raise ValueError("Choose a declared cut without duplicate media")
        keys = list(cut_keys)
        for field, maximum in (
            ("captionAssetKeys", 10),
            ("sourceAssetKeys", 20),
            ("relatedAssetKeys", 10),
            ("preparationAssetKeys", 10),
        ):
            values = body[field]
            if (
                not isinstance(values, list)
                or len(values) > maximum
                or not all(isinstance(v, str) for v in values)
                or len(set(values)) != len(values)
            ):
                raise ValueError("Invalid bounded representation references")
            keys.extend(values)
        poster = body["posterAssetKey"]
        if poster is not None:
            keys.append(poster)
        if not all(isinstance(k, str) and asset_library.valid_key(media, game, k) for k in keys):
            raise ValueError("Use exact same-game immutable asset keys")
        sources = indexed(game, list(dict.fromkeys(keys)))
        assets = {key: records.decode(item) for key, item in sources.items()}
        if any(key not in assets or assets[key].get("key") != key for key in keys):
            raise ValueError("Every reference must exist in the current catalog")
        if any(not is_video(assets[k]) or not finished(assets[k]) for k in cut_keys):
            raise ValueError("Cuts must be finished indexed videos")
        if any(not finished(assets[k]) for k in body["sourceAssetKeys"] + body["relatedAssetKeys"]):
            raise ValueError("Source references and related media must be finished assets")
        if any(
            assets[k].get("kind") != "video-captions"
            or not k.endswith(".vtt")
            or not 0 < assets[k]["size"] <= 512 * 1024
            for k in body["captionAssetKeys"]
        ):
            raise ValueError("Captions must be explicitly selected bounded WebVTT exports")
        if poster is not None and (
            assets[poster]["contentType"]
            not in {"image/png", "image/jpeg", "image/webp", "image/avif"}
            or not 0 < assets[poster]["size"] <= 8 * 1024**2
        ):
            raise ValueError("Choose a browser-compatible indexed poster")
        credits = body["credits"]
        if (
            not isinstance(credits, list)
            or len(credits) > 30
            or any(not isinstance(c, dict) or set(c) != {"role", "name"} for c in credits)
        ):
            raise ValueError("Invalid explicit credits")
        record.update(
            seriesId=series_id,
            seasonId=season_id,
            number=positive(body["number"]),
            status=body["status"],
            cuts=normalized,
            selectedCutId=body["selectedCutId"],
            posterAssetKey=poster,
            captionAssetKeys=body["captionAssetKeys"],
            sourceAssetKeys=body["sourceAssetKeys"],
            relatedAssetKeys=body["relatedAssetKeys"],
            preparationAssetKeys=body["preparationAssetKeys"],
            credits=[{"role": text(c["role"], 80), "name": text(c["name"], 160)} for c in credits],
        )
        order_key = {
            "pk": f"{PREFIX}-order#{game}#{series_id}#{season_id}",
            "sk": f"{record['number']:05}",
        }
        guards.append(
            {
                "Put": {
                    "TableName": db.name,
                    "Item": records.encode({**order_key, "episodeId": identity}),
                    "ConditionExpression": "attribute_not_exists(pk) OR episodeId = :id",
                    "ExpressionAttributeValues": records.encode({":id": identity}),
                }
            }
        )
        previous = records.decode(
            db.get_item(Key=records.pointer(PREFIX, game, kind, identity), ConsistentRead=True).get(
                "Item"
            )
        )
        if previous:
            old_key = {
                "pk": f"{PREFIX}-order#{game}#{previous['seriesId']}#{previous['seasonId']}",
                "sk": f"{previous['number']:05}",
            }
            if old_key != order_key:
                guards.append(
                    {
                        "Delete": {
                            "TableName": db.name,
                            "Key": records.encode(old_key),
                            "ConditionExpression": "episodeId = :id",
                            "ExpressionAttributeValues": records.encode({":id": identity}),
                        }
                    }
                )
        guards.append(
            {
                "ConditionCheck": {
                    "TableName": db.name,
                    "Key": records.encode(series_key),
                    "ConditionExpression": "revision = :r",
                    "ExpressionAttributeValues": records.encode({":r": series["revision"]}),
                }
            }
        )
        for key, item in sources.items():
            guards.append(
                {
                    "ConditionCheck": {
                        "TableName": db.name,
                        "Key": records.encode(
                            {"pk": browse_index.partition(game, "all"), "sk": key}
                        ),
                        "ConditionExpression": "observed = :o",
                        "ExpressionAttributeValues": records.encode({":o": item["observed"]}),
                    }
                }
            )
    return records.commit(
        db, PREFIX, kind, record, {**body, "reason": reason}, claims, fingerprint, guards, media
    )


def handler(event, _context):
    import index as media

    return handle(event, media)


def handle(event, media):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "MODEL_PUBLISHERS"):
        return media._response(403, {"error": "TV library sign-in required"})
    if event.get("routeKey", "").startswith("POST "):
        return media._response(410, {"error": "Create episodes and scenes in the Videos workspace"})
    kind = "series" if event["routeKey"].endswith("/tv-series") else "episode"
    try:
        q = event.get("queryStringParameters") or {}
        game = slug(media, q.get("gameId"))
        result = records.read(browse_index.table(), PREFIX, game, kind, q, media)
        if kind == "episode" and q.get("id") and result["statusCode"] == 200:
            body = json.loads(result["body"])
            episode = body["record"]
            keys = list(
                dict.fromkeys(
                    [c["assetKey"] for c in episode["cuts"]]
                    + episode["captionAssetKeys"]
                    + episode["sourceAssetKeys"]
                    + episode["relatedAssetKeys"]
                    + episode["preparationAssetKeys"]
                    + ([episode["posterAssetKey"]] if episode["posterAssetKey"] else [])
                )
            )
            sources = indexed(game, keys)
            assets = {key: records.decode(item) for key, item in sources.items()}
            available = {
                key: asset
                for key, asset in assets.items()
                if asset.get("key") == key and asset_library.valid_key(media, game, key)
            }
            body["assets"] = [available[k] for k in keys if k in available]
            body["warnings"] = [
                {"key": k, "reason": "Pinned asset unavailable; no replacement selected"}
                for k in keys
                if k not in available
            ]
            return media._response(200, body)
        return result
    except RuntimeError as error:
        return media._response(503, {"error": str(error)})
    except (ValueError, TypeError, KeyError, AttributeError):
        return media._response(
            400, {"error": "Invalid TV organization, source references or expected revision"}
        )
    except ClientError:
        return media._response(
            503, {"error": "TV library is temporarily unavailable; retry the exact operation"}
        )
