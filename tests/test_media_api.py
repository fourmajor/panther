import importlib.util
import io
import json
import sys
import types
import base64
import hashlib

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
            return {"Body": io.BytesIO(self.objects[Key]["Body"])}
        except KeyError as error:
            raise FakeClientError("NoSuchKey") from error

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


def load_media_api(monkeypatch):
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

    module_path = Path(__file__).parents[1] / "infra" / "lambda" / "media-api" / "index.py"
    spec = importlib.util.spec_from_file_location("panther_media_api_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
    assert metadata["extra"] == {"creator": "DM"}
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
        "s3", region_name="us-west-2", config=Config(signature_version="s3v4"),
        aws_access_key_id="TESTONLY", aws_secret_access_key="test-only-not-a-real-secret",
    )
    module, _ = load_media_api(monkeypatch)
    module.s3 = signer
    result = response_body(module.handler(upload_event(), None))
    query = parse_qs(urlparse(result["url"]).query)
    signed = set(query["X-Amz-SignedHeaders"][0].split(";"))
    assert {"content-length", "content-type", "if-none-match", "x-amz-checksum-sha256",
            "x-amz-meta-panther", "x-amz-meta-kind", "x-amz-meta-uploaded-by"} <= signed
