"""S3-backed asset location catalog; no database or idle compute.

Every file uses the same immutable locator. References in manuscripts, manifests and job
checksum pins remain stable even when physical organization changes. Never fall back to an
old payload path when an indexed asset is missing: that is a broken catalog, not another format.
"""

from datetime import datetime
import json

from botocore.exceptions import ClientError
import storage_layout


def missing(error):
    return error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}


class Storage:
    def __init__(self, client, bucket):
        self.raw = client
        self.bucket = bucket

    def locator(self, key):
        reply = self.raw.get_object(Bucket=self.bucket, Key=storage_layout.index_key(key))
        with reply["Body"] as stream:
            body = stream.read(8193)
        if len(body) > 8192:
            raise ValueError("Asset locator exceeds limit")
        entry = json.loads(body)
        game = storage_layout.parts(key)["game"]
        if (entry.get("schemaVersion") != 1 or entry.get("layoutVersion") != 2
                or entry.get("assetRef") != key
                or not isinstance(entry.get("storageKey"), str)
                or not entry["storageKey"].startswith(f"games/{game}/content/")
                or any(p in {".", "..", ""} for p in entry["storageKey"].split("/"))
                or "\\" in entry["storageKey"]):
            raise ValueError("Invalid asset location catalog entry")
        return entry

    def resolve(self, key):
        if storage_layout.REFERENCE.fullmatch(key):
            return self.locator(key)["storageKey"]
        # Structured game/character records and physical browsing are not asset references.
        return key

    def reference_for(self, key):
        """Resolve physical file-browser selections back to their stable catalog identity."""
        fields = key.split("/")
        if len(fields) < 6 or fields[0] != "games" or fields[2] != "content":
            return key
        candidates = [(fields[-2], "original")]
        if fields[-2] == "metadata":
            candidates.append((fields[-3], "metadata"))
        if fields[-3] == "derived":
            candidates.append((fields[-4], "/".join(fields[-3:-1])))
        for asset, representation in candidates:
            ref = f"games/{fields[1]}/assets/{asset}/{representation}/{fields[-1]}"
            if not storage_layout.REFERENCE.fullmatch(ref):
                continue
            try:
                if self.locator(ref)["storageKey"] == key:
                    return ref
            except ClientError as error:
                if not missing(error):
                    raise
        raise ValueError("Physical asset has no matching catalog identity")

    def _args(self, args):
        if args.get("Bucket") != self.bucket:
            raise ValueError("Wrong asset bucket")
        return {**args, "Key": self.resolve(args["Key"])}

    def head_object(self, **args):
        return self.raw.head_object(**self._args(args))

    def get_object(self, **args):
        return self.raw.get_object(**self._args(args))

    def put_object(self, **args):
        # Profile/history writers are separate from create-only asset uploads.
        if storage_layout.REFERENCE.fullmatch(args["Key"]):
            raise ValueError("Use the indexed upload operation")
        return self.raw.put_object(**args)

    def copy_object(self, **args):
        source = args["CopySource"]
        if not isinstance(source, dict) or source["Bucket"] != self.bucket:
            raise ValueError("Copy source must be a same-bucket version-pinned reference")
        return self.raw.copy_object(**{**self._args(args), "CopySource": {
            **source, "Key": self.resolve(source["Key"]),
        }})

    def generate_presigned_url(self, operation, *, Params, **args):
        return self.raw.generate_presigned_url(operation, Params=self._args(Params), **args)

    def reserve(self, reference, kind, metadata, checksum, size, created_at):
        key = storage_layout.location(reference, kind, metadata)
        entry = {"schemaVersion": 1, "layoutVersion": 2, "assetRef": reference,
                 "storageKey": key, "sha256": checksum, "size": size, "createdAt": created_at}
        try:
            self.raw.put_object(Bucket=self.bucket, Key=storage_layout.index_key(reference),
                                Body=json.dumps(entry).encode(), ContentType="application/json",
                                IfNoneMatch="*")
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in {"PreconditionFailed", "ConditionalRequestConflict"}:
                raise
            old = self.locator(reference)
            if any(old.get(field) != entry[field] for field in ("storageKey", "sha256", "size")):
                raise ValueError("Asset identity is already reserved for different content or organization")
        return key

    def list_objects_v2(self, **args):
        prefix = args.get("Prefix", "")
        segments = prefix.split("/")
        if len(segments) < 4 or segments[0] != "games" or segments[2] != "assets":
            return self.raw.list_objects_v2(**args)
        catalog_prefix = prefix.replace("/assets/", "/catalog/assets/", 1)
        page = self.raw.list_objects_v2(**{**args, "Prefix": catalog_prefix})
        result = {k: v for k, v in page.items() if k not in {"Contents", "CommonPrefixes"}}
        result["Contents"] = []
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith(".json"):
                raise ValueError("Unexpected asset catalog object")
            reference = obj["Key"][:-5].replace("/catalog/assets/", "/assets/", 1)
            entry = self.locator(reference)
            try:
                head = self.raw.head_object(Bucket=self.bucket, Key=entry["storageKey"])
            except ClientError as error:
                if missing(error):
                    # An interrupted presigned upload has a reservation, not a published asset.
                    continue
                raise
            if head["ContentLength"] != entry["size"]:
                raise ValueError("Asset size differs from its immutable reservation")
            result["Contents"].append({**obj, "Key": reference, "Size": entry["size"],
                                       "LastModified": datetime.fromisoformat(entry["createdAt"])})
        result["CommonPrefixes"] = [{"Prefix": p["Prefix"].replace("/catalog/assets/", "/assets/", 1)}
                                    for p in page.get("CommonPrefixes", [])]
        return result

    def get_paginator(self, operation):
        if operation != "list_objects_v2":
            raise ValueError("Unsupported asset pagination")
        storage = self

        class Pages:
            def paginate(self, **args):
                while True:
                    page = storage.list_objects_v2(**args)
                    yield page
                    token = page.get("NextContinuationToken")
                    if not token:
                        break
                    args["ContinuationToken"] = token
        return Pages()
