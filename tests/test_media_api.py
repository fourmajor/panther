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
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    if not real_storage:
        module.s3 = fake_s3
    return module, fake_s3


def event(route, **query):
    return {"routeKey": f"GET {route}", "queryStringParameters": query}


def response_body(response):
    return json.loads(response["body"])


def test_old_character_storage_scan_route_is_retired(monkeypatch):
    module, _fake_s3 = load_media_api(monkeypatch)

    response = module.handler(event("/characters"), None)

    assert response["statusCode"] == 404


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
    assert metadata["extra"] == {
        "creator": "DM",
        "relationshipRole": "finished",
        "generation": {"schemaVersion": 1, "method": "unknown", "cost": {"status": "unknown"}},
        "version": {
            "schemaVersion": 1,
            "seriesId": hashlib.sha256(result["key"].encode()).hexdigest()[:24],
            "number": 1,
        },
    }
    assert expiry == 300


def test_upload_new_version_inherits_series_and_rejects_wrong_kind(monkeypatch):
    module, client = load_media_api(monkeypatch)
    previous_key = "games/example-game/assets/old-map/original/map.png"
    old = {
        "schemaVersion": 1,
        "title": "Earlier fictional map",
        "category": "reference",
        "characterIds": [],
        "tags": [],
        "sourceKeys": [],
        "extra": {"version": {"schemaVersion": 1, "seriesId": "fictional-map", "number": 1}},
    }
    client.objects[previous_key] = {
        "Body": b"old",
        "ContentType": "image/png",
        "Metadata": {"kind": "map", "panther": base64.b64encode(json.dumps(old).encode()).decode()},
    }
    body = json.loads(upload_event()["body"])
    body["metadata"]["extra"]["version"] = {"previousKey": previous_key}
    result = module.handler(upload_event(**body), None)
    assert result["statusCode"] == 200
    encoded = client.signed_requests[-1][1]["Metadata"]["panther"]
    newer = json.loads(base64.b64decode(encoded))["extra"]["version"]
    assert newer == {
        "schemaVersion": 1,
        "seriesId": "fictional-map",
        "number": 2,
        "previousKey": previous_key,
    }
    assert module.handler(upload_event(**{**body, "kind": "portrait"}), None)["statusCode"] == 400
    assert (
        module.handler(
            upload_event(
                **{
                    **body,
                    "metadata": {**body["metadata"], "extra": {"version": {"seriesId": "forged"}}},
                }
            ),
            None,
        )["statusCode"]
        == 400
    )


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


@pytest.mark.parametrize(
    "filename", ["poster.png", "movie.mp4", "model.blend", 'Café "portrait".png']
)
def test_download_signs_exact_revision_as_safe_attachment(monkeypatch, filename):
    module, client = load_media_api(monkeypatch)
    key = f"games/example-game/assets/revision-two/original/{filename}"
    client.objects[key] = {"Body": b"original bytes", "ContentType": "application/octet-stream"}
    result = response_body(module.handler(event("/object-url", key=key, download="true"), None))
    assert result["key"] == key and result["filename"] == filename
    operation, params, expiry = client.signed_requests[-1]
    assert operation == "get_object" and params["Key"] == key and expiry == 300
    disposition = params["ResponseContentDisposition"]
    assert disposition.startswith('attachment; filename="')
    assert "filename*=UTF-8''" in disposition
    assert "\r" not in disposition and "\n" not in disposition
    module.handler(event("/object-url", key=key), None)
    assert client.signed_requests[-1][1]["ResponseContentDisposition"] == "inline"


def test_download_missing_or_invalid_never_signs(monkeypatch):
    module, client = load_media_api(monkeypatch)
    assert (
        module.handler(
            event("/object-url", key="games/example-game/missing", download="true"), None
        )["statusCode"]
        == 404
    )
    assert (
        module.handler(
            event("/object-url", key="games/example-game/missing", download="false"), None
        )["statusCode"]
        == 400
    )
    assert not client.signed_requests


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


def test_character_routes_delegate_to_typed_appearance_service(monkeypatch):
    from unittest.mock import Mock

    module, fake = load_media_api(monkeypatch)
    service = types.SimpleNamespace(
        view=Mock(
            return_value={"selection": {"id": "retained-pair"}, "poster": None, "model": None}
        ),
        history=Mock(
            return_value={
                "schemaVersion": 2,
                "selections": [],
                "activations": [],
                "appearances": [],
            }
        ),
        profile=Mock(return_value=(None, b"{}", {"schemaVersion": 2}, "a" * 32)),
        publish=Mock(return_value={"statusCode": 200, "body": "{}"}),
    )
    monkeypatch.setitem(sys.modules, "character_appearances", service)
    result = module.handler(
        event(
            "/character",
            gameId="example-game",
            characterId="example-character",
            appearanceId="ordinary",
            selectionId="retained-pair",
        ),
        None,
    )
    assert result["statusCode"] == 200
    service.view.assert_called_once_with(
        module, "example-game", "example-character", "ordinary", "retained-pair"
    )
    assert (
        module.handler(
            event("/character-versions", gameId="example-game", characterId="example-character"),
            None,
        )["statusCode"]
        == 200
    )
    service.history.assert_called_once_with(module, "example-game", "example-character")
    profile = response_body(
        module.handler(
            event("/character-profile", gameId="example-game", characterId="example-character"),
            None,
        )
    )
    assert profile["revision"] == "a" * 32 and profile["profile"]["schemaVersion"] == 2
    for route, kind in [("PUT /character-model", "model"), ("PUT /character-portrait", "portrait")]:
        request = {"routeKey": route, "body": "{}"}
        assert module.handler(request, None)["statusCode"] == 200
        service.publish.assert_called_with(module, request, kind)
    assert not fake.signed_requests


@pytest.mark.parametrize("route", ["/character", "/character-versions", "/character-profile"])
@pytest.mark.parametrize(
    "failure,status",
    [(ValueError("missing exact selection"), 404), (RuntimeError("unverified migration"), 503)],
)
def test_character_routes_fail_closed_without_legacy_storage_fallback(
    monkeypatch, route, failure, status
):
    from unittest.mock import Mock

    module, fake = load_media_api(monkeypatch)
    service = types.SimpleNamespace(
        view=Mock(side_effect=failure),
        history=Mock(side_effect=failure),
        profile=Mock(side_effect=failure),
    )
    monkeypatch.setitem(sys.modules, "character_appearances", service)
    before = dict(fake.objects)
    result = module.handler(
        event(route, gameId="example-game", characterId="example-character"), None
    )
    assert result["statusCode"] == status
    assert fake.objects == before and not fake.signed_requests


def test_browser_pcm_upload_fits_signed_metadata_and_retains_integrity_headers(monkeypatch):
    from test_browser_recording import manifest, wav
    doc, raw = manifest(), wav()
    checksum = base64.b64encode(hashlib.sha256(raw).digest()).decode()
    part = {"recordingId": doc["id"], **doc["parts"][0]}
    module, client = load_media_api(monkeypatch)
    response = module.handler(upload_event(
        assetId=doc["id"], kind="recording", filename=part["file"],
        contentType="audio/wav", size=len(raw), sha256=checksum,
        metadata={"title": part["file"], "sessionId": doc["sessionId"],
                  "category": "canonical-source", "characterIds": [], "sourceKeys": [],
                  "extra": {"browserPart": part, "recordingId": doc["id"],
                            "chunkSetId": doc["id"], "sha256": checksum,
                            "generation": {"schemaVersion": 1, "method": "capture", "inference": "not-applicable",
                                           "execution": "local", "tool": "Browser Web Audio PCM capture",
                                           "cost": {"status": "not-applicable"}}}},
    ), None)
    assert response["statusCode"] == 200
    result = response_body(response)
    method, signed, _ = client.signed_requests[-1]
    assert method == "put_object"
    assert signed["ContentLength"] == len(raw)
    assert signed["ContentType"] == "audio/wav"
    assert result["headers"]["If-None-Match"] == "*"
    assert result["headers"]["x-amz-checksum-sha256"] == checksum
    metadata = json.loads(base64.b64decode(signed["Metadata"]["panther"]))
    assert metadata["extra"]["browserPart"] == part
    assert metadata["extra"]["sha256"] == checksum
