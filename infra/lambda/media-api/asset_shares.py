"""Explicit, revocable bearer links. Public requests can resolve exactly one pinned object."""

import base64
import hashlib
import html
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError
import index as media
from access_policy import authorized

TOKEN = re.compile(r"[a-f0-9]{64}")
KEY = re.compile(r"games/[a-z0-9-]+/assets/[a-z0-9-]+/original/[^/]+")


def table():
    return boto3.resource("dynamodb").Table(os.environ["ASSET_SHARES_TABLE"])


def token_hash(value):
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise ValueError("Invalid share token")
    return hashlib.sha256(value.encode()).hexdigest()


def pinned_preview(key, item):
    if (
        not isinstance(key, str)
        or not KEY.fullmatch(key)
        or key.split("/")[1] != item["key"].split("/")[1]
    ):
        raise ValueError("Same-game preview required")
    storage = media.s3.resolve(key)
    head = media.raw_s3.head_object(Bucket=media.BUCKET_NAME, Key=storage)
    metadata = json.loads(base64.b64decode(head.get("Metadata", {}).get("panther", "e30=")))
    if (
        head.get("ContentType") not in ("image/jpeg", "image/png", "image/webp")
        or head.get("ContentLength", 0) > 8 * 1024 * 1024
        or not head.get("VersionId")
        or head["VersionId"] == "null"
        or item["key"] not in metadata.get("sourceKeys", [])
        or metadata.get("extra", {}).get("sourceVersionId") != item["versionId"]
    ):
        raise ValueError("Preview must derive from the exact shared video version")
    return dict(
        key=key, storageKey=storage, versionId=head["VersionId"], contentType=head["ContentType"]
    )


def response(status, body="", content_type="text/html; charset=utf-8", **headers):
    return {
        "statusCode": status,
        "headers": {
            "content-type": content_type,
            "cache-control": "no-store, private",
            "referrer-policy": "no-referrer",
            "x-robots-tag": "noindex, nofollow, noarchive",
            "x-content-type-options": "nosniff",
            **headers,
        },
        "body": body,
    }


def manage(event, _context):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "MODEL_PUBLISHERS"):
        return media._response(403, {"error": "Publisher sign-in required"})
    try:
        if len(event.get("body") or "") > 4000:
            raise ValueError()
        data = json.loads(event.get("body") or "{}")
        if not isinstance(data, dict):
            raise ValueError()
        token = data.get("token")
        digest = token_hash(token)
        route = event.get("routeKey")
        if route == "POST /asset-shares/preview":
            item = table().get_item(Key={"pk": digest}, ConsistentRead=True).get("Item")
            if not item or "revokedAt" in item or item.get("contentType") != "video/mp4":
                return media._response(409, {"error": "Active video share required"})
            preview = pinned_preview(data.get("previewKey"), item)
            # Immutable attachment: retries are safe; changing an existing poster needs a new share.
            table().update_item(
                Key={"pk": digest},
                UpdateExpression="SET preview = :preview, previewAddedBy = if_not_exists(previewAddedBy, :actor), previewAddedAt = if_not_exists(previewAddedAt, :now)",
                ConditionExpression="attribute_exists(pk) AND attribute_not_exists(revokedAt) AND (attribute_not_exists(preview) OR preview = :preview)",
                ExpressionAttributeValues={
                    ":preview": preview,
                    ":actor": claims["sub"],
                    ":now": int(time.time()),
                },
            )
            return media._response(200, {"previewAttached": True})
        if route == "POST /asset-shares/revoke":
            # A tombstone is permanent; creating with this token can never reactivate it.
            table().update_item(
                Key={"pk": digest},
                UpdateExpression="SET revokedAt = :now, revokedBy = :actor",
                ConditionExpression="attribute_exists(pk)",
                ExpressionAttributeValues={":now": int(time.time()), ":actor": claims["sub"]},
            )
            return media._response(200, {"revoked": True, "existingDownloadGraceSeconds": 300})
        if route != "POST /asset-shares":
            return media._response(404, {"error": "Unknown operation"})
        prior = table().get_item(Key={"pk": digest}, ConsistentRead=True).get("Item", {})
        if "revokedAt" in prior:
            return media._response(409, {"error": "Share token already used"})
        key = data.get("key")
        if (
            data.get("confirmPublic") is not True
            or not isinstance(key, str)
            or not KEY.fullmatch(key)
            or not media._valid_key(key)
        ):
            raise ValueError()
        storage = media.s3.resolve(key)
        head = media.raw_s3.head_object(Bucket=media.BUCKET_NAME, Key=storage)
        version = head.get("VersionId")
        if not version or version == "null":
            raise ValueError("Versioned asset required")
        metadata = json.loads(base64.b64decode(head.get("Metadata", {}).get("panther", "e30=")))
        title = str(metadata.get("title") or "Shared asset")[:500]
        item = dict(
            pk=digest,
            key=key,
            storageKey=storage,
            versionId=version,
            contentType=head.get("ContentType", "application/octet-stream"),
            title=title,
            filename=key.rsplit("/", 1)[-1],
            createdAt=int(time.time()),
            createdBy=claims["sub"],
        )
        if item["contentType"] == "video/mp4":
            item["preview"] = pinned_preview(data.get("previewKey"), item)
        try:
            table().put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            prior = table().get_item(Key={"pk": digest}, ConsistentRead=True).get("Item", {})
            if (
                prior.get("key") != key
                or prior.get("createdBy") != claims["sub"]
                or "revokedAt" in prior
            ):
                return media._response(409, {"error": "Share token already used"})
        url = os.environ["SITE_ORIGIN"] + "/s/" + token
        return media._response(
            200,
            {
                "url": url,
                "directUrl": url + "/watch",
                "downloadUrl": url + "/download",
                "expiresAt": None,
                "access": "anyone-with-link",
            },
        )
    except (ValueError, TypeError, KeyError):
        return media._response(400, {"error": "Invalid share request"})
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        return media._response(
            404 if code in ("404", "NoSuchKey", "ConditionalCheckFailedException") else 503,
            {"error": "Asset or share unavailable"},
        )


def public(event, _context):
    try:
        route = event.get("routeKey")
        if route not in (
            "GET /s/{token}",
            "GET /s/{token}/watch",
            "GET /s/{token}/download",
            "GET /s/{token}/preview",
        ):
            raise ValueError()
        token = (event.get("pathParameters") or {}).get("token")
        item = table().get_item(Key={"pk": token_hash(token)}, ConsistentRead=True).get("Item")
        if not item or "revokedAt" in item:
            return response(410, "This sharing link is unavailable or has been revoked.")
        if item["contentType"] == "video/mp4" and not item.get("preview"):
            return response(503, "Video preview needs preparation.")
        if route.endswith("/preview"):
            preview = item.get("preview")
            if not preview:
                return response(410, "Preview unavailable.")
            url = media.raw_s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": media.BUCKET_NAME,
                    "Key": preview["storageKey"],
                    "VersionId": preview["versionId"],
                    "ResponseContentType": preview["contentType"],
                    "ResponseContentDisposition": "inline",
                },
                ExpiresIn=300,
            )
            return response(302, location=url)
        if route.endswith("/watch") or route.endswith("/download"):
            # HTML/SVG and other active formats are always attachments, never same-origin content.
            safe_inline = item["contentType"] in (
                "video/mp4",
                "audio/mpeg",
                "audio/wav",
                "image/png",
                "image/jpeg",
                "image/webp",
            )
            mode = "inline" if route.endswith("/watch") and safe_inline else "attachment"
            disposition = mode + "; filename*=UTF-8''" + quote(item["filename"], safe="")
            url = media.raw_s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": media.BUCKET_NAME,
                    "Key": item["storageKey"],
                    "VersionId": item["versionId"],
                    "ResponseContentDisposition": disposition,
                    "ResponseContentType": item["contentType"]
                    if safe_inline
                    else "application/octet-stream",
                },
                ExpiresIn=300,
            )
            return response(302, location=url)
        src = "/s/" + token + "/watch"
        mime = item["contentType"]
        if mime == "video/mp4":
            poster = f' poster="/s/{token}/preview"'
            player = f'<video controls playsinline preload="metadata" src="{src}"{poster} aria-label="Shared video"></video>'
        elif mime in ("audio/mpeg", "audio/wav"):
            player = (
                f'<audio controls preload="metadata" src="{src}" aria-label="Shared audio"></audio>'
            )
        elif mime in ("image/png", "image/jpeg", "image/webp"):
            player = f'<img src="{src}" alt="Shared image">'
        else:
            player = "<p>This file is available to download.</p>"
        url = os.environ["SITE_ORIGIN"] + "/s/" + token
        tags = {
            "og:title": item["title"],
            "og:type": "video.other" if mime == "video/mp4" else "website",
            "og:url": url,
            "og:site_name": "Panther",
            "og:description": "Watch or download this shared file. No Panther account needed.",
            "og:image": url + "/watch"
            if mime in ("image/png", "image/jpeg", "image/webp")
            else os.environ["SITE_ORIGIN"] + "/share-preview.png",
            "og:image:alt": "Shared image"
            if mime.startswith("image/")
            else "Panther — shared media",
        }
        if mime == "video/mp4":
            # Video previews always use a frame pinned to this shared version.
            tags.pop("og:image")
            tags.pop("og:image:alt")
            tags.update(
                {
                    "og:image": url + "/preview",
                    "og:image:type": item["preview"]["contentType"],
                    "og:image:alt": "Frame from " + item["title"],
                }
            )
            tags.update(
                {
                    "og:video": url + "/watch",
                    "og:video:secure_url": url + "/watch",
                    "og:video:type": "video/mp4",
                }
            )
        social = "".join(
            f'<meta property="{name}" content="{html.escape(value, quote=True)}">'
            for name, value in tags.items()
        )
        values = {
            "title": html.escape(item["title"]),
            "player": player,
            "token": token,
            "social": social,
        }
        # Substitute only template-owned placeholders, never text inside an asset title.
        page = re.sub(
            r"\{\{(title|player|token|social)\}\}",
            lambda match: values[match[1]],
            Path(__file__).with_name("share.html").read_text(),
        )
        return response(200, page)
    except ValueError:
        return response(410, "This sharing link is unavailable or has been revoked.")
    except (ClientError, KeyError, TypeError):
        return response(503, "Temporarily unavailable. Please try again.")
