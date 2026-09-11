import importlib.util
import io
import json
import sys
import types
import base64
import hashlib
import struct

import pytest
from pathlib import Path


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakePaginator:
    def __init__(self, client):
        self.client = client

    def paginate(self, **_kwargs):
        return [{"Contents": [{"Key": key} for key in sorted(self.client.objects)]}]


class FakeS3:
    def __init__(self):
        self.signed_requests = []
        profile = {
            "schemaVersion": 1,
            "gameId": "example-game",
            "id": "example-character",
            "name": "Example Character",
            "title": "Navigator",
            "summary": "An example character used only by the API test.",
            "model": {
                "webKey": "games/example-game/assets/example-model/derived/web/model.glb",
                "sourceKey": "games/example-game/assets/example-model/original/model.gltf",
                "posterKey": "games/example-game/assets/example-portrait/original/poster.png",
                "provenanceKey": "games/example-game/assets/example-model/metadata/provenance.json",
                "maxBytes": 5 * 1024 * 1024,
            },
        }
        self.objects = {
            "games/example-game/characters/example-character/profile.json": {
                "Body": json.dumps(profile).encode(),
                "ContentType": "application/json",
            },
            "games/example-game/assets/example-model/derived/web/model.glb": {
                "Body": b"glTF",
                "ContentType": "model/gltf-binary",
            },
            "games/example-game/assets/example-portrait/original/poster.png": {
                "Body": b"png",
                "ContentType": "image/png",
            },
        }

    def get_paginator(self, _name):
        return FakePaginator(self)

    def get_object(self, *, Key, **_kwargs):
        try:
            data = self.objects[Key]["Body"]
            return {"Body": io.BytesIO(data), "ETag": '"' + hashlib.md5(data).hexdigest() + '"'}
        except KeyError as error:
            raise FakeClientError("NoSuchKey") from error

    def put_object(self, *, Key, Body, ContentType, IfNoneMatch=None, IfMatch=None, **_kwargs):
        if IfNoneMatch == "*" and Key in self.objects:
            raise FakeClientError("PreconditionFailed")
        if IfMatch and self.get_object(Key=Key)["ETag"] != IfMatch:
            raise FakeClientError("PreconditionFailed")
        self.objects[Key] = {"Body": Body, "ContentType": ContentType}
        return {"ETag": self.get_object(Key=Key)["ETag"]}

    def head_object(self, *, Key, **_kwargs):
        try:
            item = self.objects[Key]
        except KeyError as error:
            raise FakeClientError("NotFound") from error
        return {
            "ContentLength": len(item["Body"]),
            "ContentType": item["ContentType"],
            "Metadata": item.get("Metadata", {}),
        }

    def generate_presigned_url(self, _operation, *, Params, ExpiresIn):
        self.signed_requests.append((_operation, Params, ExpiresIn))
        return f"https://private.example/{Params['Key']}?expires={ExpiresIn}"

    # Business-rule tests mock the storage facade. Its real indexed implementation is
    # exercised separately by test_asset_storage and the real_storage upload test.
    def resolve(self, key):
        return key

    def reference_for(self, key):
        return key

    def reserve(self, key, kind, metadata, *_args):
        from storage_layout import location
        return location(key, kind, metadata)


def load_media_api(monkeypatch, *, real_storage=False):
    monkeypatch.setenv("MODEL_PUBLISHERS", "example-operator,example-editor")
    monkeypatch.setenv("ASSET_MIGRATORS", "example-operator")
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "infra/lambda/media-api"))
    fake_s3 = FakeS3()
    boto3 = types.ModuleType("boto3")
    boto3.client = lambda _service, **_kwargs: fake_s3
    botocore = types.ModuleType("botocore")
    botocore_exceptions = types.ModuleType("botocore.exceptions")
    botocore_exceptions.ClientError = FakeClientError
    botocore_config = types.ModuleType("botocore.config")
    botocore_config.Config = lambda **_kwargs: None
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "botocore", botocore)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", botocore_exceptions)
    monkeypatch.setitem(sys.modules, "botocore.config", botocore_config)
    monkeypatch.setenv("ASSET_BUCKET_NAME", "private-test-bucket")
    monkeypatch.delitem(sys.modules, "asset_storage", raising=False)

    module_path = Path(__file__).parents[1] / "infra" / "lambda" / "media-api" / "index.py"
    spec = importlib.util.spec_from_file_location("panther_media_api_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not real_storage:
        module.s3 = fake_s3
    return module, fake_s3


def event(route, **query):
    return {"routeKey": f"GET {route}", "queryStringParameters": query}


def response_body(response):
    return json.loads(response["body"])


def test_lists_character_manifests_without_asset_urls(monkeypatch):
    module, _fake_s3 = load_media_api(monkeypatch)

    response = module.handler(event("/characters"), None)

    assert response["statusCode"] == 200
    assert response_body(response) == {
        "characters": [
            {
                "gameId": "example-game",
                "id": "example-character",
                "name": "Example Character",
                "title": "Navigator",
            }
        ]
    }


def test_portrait_only_character_can_be_viewed(monkeypatch):
    module, fake = load_media_api(monkeypatch)
    key = "games/example-game/characters/example-character/profile.json"
    profile = json.loads(fake.objects[key]["Body"])
    profile["model"] = {"posterKey": profile["model"]["posterKey"]}
    fake.objects[key]["Body"] = json.dumps(profile).encode()
    response = module.handler(event("/character", gameId="example-game", characterId="example-character"), None)
    assert response["statusCode"] == 200
    assert response_body(response)["model"] is None
    assert response_body(response)["poster"]["url"]


def test_character_model_uses_short_lived_urls_and_enforces_metadata(monkeypatch):
    module, _fake_s3 = load_media_api(monkeypatch)

    response = module.handler(
        event("/character", gameId="example-game", characterId="example-character"),
        None,
    )
    body = response_body(response)

    assert response["statusCode"] == 200
    assert body["character"]["name"] == "Example Character"
    assert body["model"]["contentType"] == "model/gltf-binary"
    assert body["model"]["expiresIn"] == 300
    assert body["model"]["url"].startswith("https://private.example/games/")
    assert body["model"]["sourceRetained"] is True
    assert body["model"]["provenanceRetained"] is True
    assert body["poster"]["contentType"] == "image/png"


def test_character_model_rejects_assets_over_five_megabytes(monkeypatch):
    module, fake_s3 = load_media_api(monkeypatch)
    fake_s3.objects["games/example-game/assets/example-model/derived/web/model.glb"]["Body"] = (
        b"x" * (5 * 1024 * 1024 + 1)
    )

    response = module.handler(
        event("/character", gameId="example-game", characterId="example-character"),
        None,
    )

    assert response["statusCode"] == 422
    assert response_body(response)["error"] == "Character assets are unavailable or exceed limits"


def upload_event(**updates):
    body = {
        "gameId": "example-game",
        "assetId": "example-map",
        "kind": "map",
        "filename": "map.png",
        "contentType": "image/png",
        "size": 3,
        "sha256": base64.b64encode(hashlib.sha256(b"png").digest()).decode(),
        "metadata": {"category": "reference", "tags": ["harbor"], "extra": {"creator": "DM"}},
    }
    body.update(updates)
    return {
        "routeKey": "POST /uploads",
        "body": json.dumps(body),
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "example-user"}}}},
    }


def test_upload_signs_size_checksum_metadata_and_no_overwrite(monkeypatch):
    module, client = load_media_api(monkeypatch)
    response = module.handler(upload_event(), None)
    assert response["statusCode"] == 200
    result = response_body(response)
    assert result["key"] == "games/example-game/assets/example-map/original/map.png"
    operation, params, expiry = client.signed_requests[-1]
    assert operation == "put_object"
    assert params["IfNoneMatch"] == result["headers"]["If-None-Match"] == "*"
    assert params["ContentLength"] == 3
    assert params["ChecksumSHA256"] == result["headers"]["x-amz-checksum-sha256"]
    assert params["Metadata"]["uploaded-by"] == "example-user"
    metadata = json.loads(base64.b64decode(params["Metadata"]["panther"]))
    assert metadata["category"] == "reference"
    assert metadata["extra"] == {"creator": "DM", "relationshipRole": "finished",
                                 "generation": {"schemaVersion": 1, "method": "unknown", "cost": {"status": "unknown"}}}
    assert expiry == 300


@pytest.mark.parametrize(
    "change",
    [
        {"gameId": "../other"},
        {"assetId": "a/../../characters"},
        {"kind": []},
        {"filename": "../profile.json"},
        {"filename": "foo\\bar"},
        {"filename": "bad\nfile"},
        {"filename": "."},
        {"size": True},
        {"size": -1},
        {"size": 1024**3 + 1},
        {"contentType": "text/plain\r\nBad: yes"},
        {"sha256": "nope"},
        {"metadata": []},
        {"metadata": {"category": []}},
        {"metadata": {"characterIds": ["../x"]}},
        {"metadata": {"sessionId": "x/y"}},
        {"metadata": {"tags": "not-a-list"}},
        {"metadata": {"extra": "not-an-object"}},
        {"metadata": {"unknown": 1}},
        {"metadata": {"sourceKeys": ["games/other/assets/x"]}},
        {"metadata": {"extra": {"long": "x" * 3000}}},
    ],
)
def test_rejects_invalid_uploads_without_signing(monkeypatch, change):
    module, client = load_media_api(monkeypatch)
    assert module.handler(upload_event(**change), None)["statusCode"] == 400
    assert not client.signed_requests


def test_upload_requires_identity_and_valid_json(monkeypatch):
    module, client = load_media_api(monkeypatch)
    request = upload_event()
    del request["requestContext"]
    assert module.handler(request, None)["statusCode"] == 401
    request = upload_event()
    request["body"] = "{"
    assert module.handler(request, None)["statusCode"] == 400
    assert not client.signed_requests


def test_info_returns_metadata_for_uploaded_and_legacy_assets(monkeypatch):
    module, client = load_media_api(monkeypatch)
    key = "games/example-game/assets/example-portrait/original/poster.png"
    request = event("/object-url", key=key)
    assert response_body(module.handler(request, None))["metadata"] == {}
    client.objects[key]["Metadata"] = {
        "kind": "portrait",
        "panther": base64.b64encode(b'{"title":"Example"}').decode(),
    }
    result = response_body(module.handler(request, None))
    assert result["kind"] == "portrait"
    assert result["metadata"]["title"] == "Example"


def test_real_signer_binds_length_checksum_and_conditional_write(monkeypatch):
    import boto3
    from botocore.config import Config
    from urllib.parse import parse_qs, urlparse

    signer = boto3.client(
        "s3",
        region_name="us-west-2",
        config=Config(signature_version="s3v4"),
        aws_access_key_id="TESTONLY",
        aws_secret_access_key="test-only-not-a-real-secret",
    )
    module, _ = load_media_api(monkeypatch)
    module.s3.generate_presigned_url = signer.generate_presigned_url
    result = response_body(module.handler(upload_event(), None))
    query = parse_qs(urlparse(result["url"]).query)
    signed = set(query["X-Amz-SignedHeaders"][0].split(";"))
    assert {
        "content-length",
        "content-type",
        "if-none-match",
        "x-amz-checksum-sha256",
        "x-amz-meta-panther",
        "x-amz-meta-kind",
        "x-amz-meta-uploaded-by",
    } <= signed


PROFILE_KEY = "games/example-game/characters/example-character/profile.json"
NEW_WEB = "games/example-game/assets/new-model/original/model.glb"
NEW_SOURCE = "games/example-game/assets/new-model/original/model.blend"


def publication(module, client, **updates):
    module.MODEL_PUBLISHERS = {"owner", "dm"}
    client.objects[NEW_WEB] = {
        "Body": struct.pack("<4sII", b"glTF", 2, 12),
        "ContentType": "model/gltf-binary",
    }
    client.objects[NEW_SOURCE] = {"Body": b"blend", "ContentType": "application/octet-stream"}
    body = {
        "gameId": "example-game",
        "characterId": "example-character",
        "webKey": NEW_WEB,
        "sourceKey": NEW_SOURCE,
        "expectedRevision": client.get_object(Key=PROFILE_KEY)["ETag"],
        "reason": "Replace prototype with tested model",
    }
    body.update(updates)
    return {
        "routeKey": "PUT /character-model",
        "body": json.dumps(body),
        "requestContext": {
            "authorizer": {"jwt": {"claims": {"sub": "user-id", "cognito:username": "owner"}}}
        },
    }


def test_profile_read_has_revision_and_no_signed_urls(monkeypatch):
    module, client = load_media_api(monkeypatch)
    response = module.handler(
        event("/character-profile", gameId="example-game", characterId="example-character"), None
    )
    assert response["statusCode"] == 200
    result = response_body(response)
    assert result["revision"] == client.get_object(Key=PROFILE_KEY)["ETag"]
    assert result["profile"]["name"] == "Example Character"
    assert not client.signed_requests


def test_publish_preserves_exact_profile_portrait_assets_and_audit(monkeypatch):
    module, client = load_media_api(monkeypatch)
    before = client.objects[PROFILE_KEY]["Body"]
    old_assets = dict(client.objects)
    request = publication(module, client)
    response = module.handler(request, None)
    assert response["statusCode"] == 200
    result = response_body(response)
    assert client.objects[result["previousProfileKey"]]["Body"] == before
    profile = result["profile"]
    assert profile["model"]["posterKey"] == json.loads(before)["model"]["posterKey"]
    assert profile["model"]["webKey"] == NEW_WEB
    assert profile["modelPublication"]["actor"] == "user-id"
    for key, value in old_assets.items():
        if key != PROFILE_KEY:
            assert client.objects[key] == value
    # A stale request can never roll the character back; re-inspection is required.
    assert module.handler(request, None)["statusCode"] == 409
    web_response = module.handler(
        event("/character", gameId="example-game", characterId="example-character"), None
    )
    assert NEW_WEB in response_body(web_response)["model"]["url"]


@pytest.mark.parametrize(
    "updates,status",
    [
        ({"gameId": "../other"}, 400),
        ({"characterId": []}, 400),
        ({"webKey": "games/other/assets/a/original/model.glb"}, 400),
        ({"sourceKey": PROFILE_KEY}, 400),
        ({"sourceKey": "games/example-game/assets/x/original/.."}, 400),
        ({"provenanceKey": "games/example-game/assets/x/original/missing.json"}, 422),
        ({"reason": ""}, 400),
        ({"expectedRevision": "stale"}, 409),
        ({"posterKey": "change-not-authorized"}, 400),
        ({"sourceKey": None}, 400),
    ],
)
def test_publish_rejects_bad_requests_without_profile_changes(monkeypatch, updates, status):
    module, client = load_media_api(monkeypatch)
    before = client.objects[PROFILE_KEY]["Body"]
    assert module.handler(publication(module, client, **updates), None)["statusCode"] == status
    assert client.objects[PROFILE_KEY]["Body"] == before
    assert not any("/history/" in k for k in client.objects)


@pytest.mark.parametrize("username", [None, "reader"])
def test_publish_requires_authorized_username(monkeypatch, username):
    module, client = load_media_api(monkeypatch)
    request = publication(module, client)
    request["requestContext"]["authorizer"]["jwt"]["claims"]["cognito:username"] = username
    assert module.handler(request, None)["statusCode"] == 403
    assert not any("/history/" in k for k in client.objects)


@pytest.mark.parametrize(
    "data", [b"not a model!", struct.pack("<4sII", b"glTF", 1, 12), b"x" * (5 * 1024 * 1024 + 1)]
)
def test_publish_rejects_invalid_or_oversized_glb(monkeypatch, data):
    module, client = load_media_api(monkeypatch)
    request = publication(module, client)
    client.objects[NEW_WEB]["Body"] = data
    assert module.handler(request, None)["statusCode"] == 422
    assert not any("/history/" in k for k in client.objects)


def test_publish_concurrent_change_retains_winner_and_snapshot(monkeypatch):
    module, client = load_media_api(monkeypatch)
    request = publication(module, client)
    put = client.put_object
    before = client.objects[PROFILE_KEY]["Body"]

    def racing_put(**kwargs):
        if kwargs["Key"] == PROFILE_KEY:
            client.objects[PROFILE_KEY]["Body"] = b'{"winner":true}'
        return put(**kwargs)

    client.put_object = racing_put
    assert module.handler(request, None)["statusCode"] == 409
    assert client.objects[PROFILE_KEY]["Body"] == b'{"winner":true}'
    assert any(v["Body"] == before for k, v in client.objects.items() if "/history/" in k)


def test_existing_history_is_safe_and_history_failure_prevents_switch(monkeypatch):
    module, client = load_media_api(monkeypatch)
    request = publication(module, client)
    before = client.objects[PROFILE_KEY]["Body"]
    history = PROFILE_KEY.replace(
        "profile.json", f"history/{hashlib.sha256(before).hexdigest()}.json"
    )
    client.objects[history] = {"Body": before, "ContentType": "application/json"}
    assert module.handler(request, None)["statusCode"] == 200
    assert client.objects[history]["Body"] == before
    request = publication(module, client)
    before = client.objects[PROFILE_KEY]["Body"]

    def fail(**_kwargs):
        raise FakeClientError("AccessDenied")

    client.put_object = fail
    assert module.handler(request, None)["statusCode"] == 502
    assert client.objects[PROFILE_KEY]["Body"] == before
