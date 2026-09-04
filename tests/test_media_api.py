import importlib.util
import io
import json
import sys
import types
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
        }

    def generate_presigned_url(self, _operation, *, Params, ExpiresIn):
        return f"https://private.example/{Params['Key']}?expires={ExpiresIn}"


def load_media_api(monkeypatch):
    fake_s3 = FakeS3()
    boto3 = types.ModuleType("boto3")
    boto3.client = lambda _service: fake_s3
    botocore = types.ModuleType("botocore")
    botocore_exceptions = types.ModuleType("botocore.exceptions")
    botocore_exceptions.ClientError = FakeClientError
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "botocore", botocore)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", botocore_exceptions)
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
