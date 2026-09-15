"""Authorize a gallery once; media bytes travel directly from private S3 to the browser."""
import json
from concurrent.futures import ThreadPoolExecutor

from botocore.exceptions import ClientError
from access_policy import authorized
import storage_layout

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "avif", "gif", "svg"}


def handle(event, media):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not authorized(claims, "MODEL_PUBLISHERS"):
        return media._response(403, {"error": "Publisher sign-in required"})
    try:
        if len(event.get("body") or "") > 64000:
            raise ValueError()
        body = json.loads(event.get("body") or "{}")
        game, keys = body.get("gameId"), body.get("keys")
        if not media._valid_slug(game) or not isinstance(keys, list) or not 1 <= len(keys) <= 60:
            raise ValueError()
        for key in keys:
            if (not isinstance(key, str) or not storage_layout.REFERENCE.fullmatch(key)
                    or not key.startswith(f"games/{game}/assets/")
                    or key.rsplit(".", 1)[-1].lower() not in IMAGE_EXTENSIONS):
                raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return media._response(400, {"error": "Provide 1–60 same-game image asset references"})

    def sign(key):
        try:
            # One validated locator read per unique asset, no payload HEAD/GET and no
            # per-image Lambda invocation. The signer performs no network request.
            physical = media.s3.resolve(key)
            url = media.raw_s3.generate_presigned_url("get_object", Params={
                "Bucket": media.BUCKET_NAME, "Key": physical,
                "ResponseContentDisposition": "inline"}, ExpiresIn=media.SIGNED_URL_TTL_SECONDS)
            return key, {"url": url}
        except ClientError as error:
            missing = error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}
            return key, {"error": "Image reference not found" if missing else "Image link temporarily unavailable",
                         "retryable": not missing}
        except ValueError:
            return key, {"error": "Image location is invalid", "retryable": False}

    with ThreadPoolExecutor(max_workers=8) as pool:
        images = dict(pool.map(sign, dict.fromkeys(keys)))
    return media._response(200, {"images": images, "expiresIn": media.SIGNED_URL_TTL_SECONDS})
