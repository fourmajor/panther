import importlib
import json
from pathlib import Path
import struct
import uuid
import zlib

import boto3
import pytest

from panther_journal import asset_generation as worker
from test_novel_library import library, novel, editorial, broker  # noqa: F401


@pytest.fixture
def generation(library, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ASSET_GENERATION_TABLE", "test-asset-generation")
    monkeypatch.setenv("MODEL_WORKERS", "example-worker")
    boto3.resource("dynamodb").create_table(
        TableName="test-asset-generation",
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": name, "AttributeType": kind}
            for name, kind in (
                ("pk", "S"),
                ("sk", "S"),
                ("status", "S"),
                ("createdAt", "N"),
                ("gameId", "S"),
            )
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GameIndex",
                "KeySchema": [
                    {"AttributeName": "gameId", "KeyType": "HASH"},
                    {"AttributeName": "createdAt", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "StatusIndex",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "createdAt", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )
    return importlib.import_module("asset_generation")


def call(module, route="POST /asset-generation", body=None, username="example-operator", **query):
    return module.handler(
        {
            "routeKey": route,
            "body": json.dumps(body or {}),
            "queryStringParameters": query,
            "requestContext": {
                "authorizer": {"jwt": {"claims": {"sub": username, "cognito:username": username}}}
            },
        },
        None,
    )


def request(**changes):
    return {
        "gameId": "test-game",
        "type": "map",
        "name": "Harbor road",
        "prompt": "A map from harbor to hills",
        "operationId": uuid.uuid4().hex,
        **changes,
    }


def unpack(reply):
    assert reply["statusCode"] == 200, reply
    return json.loads(reply["body"])


def test_generation_submission_idempotency_and_authorization(generation):
    body = request()
    job = unpack(call(generation, body=body))
    assert job["status"] == "QUEUED" and job["assetKey"] is None
    assert unpack(call(generation, body=body))["jobId"] == job["jobId"]
    assert call(generation, body=body, username="outsider")["statusCode"] == 403
    assert call(generation, body=request(gameId="other-game"))["statusCode"] == 400
    assert call(generation, body=request(type="unknown"))["statusCode"] == 400
    assert call(generation, body=request(prompt=""))["statusCode"] == 400
    assert (
        call(generation, "GET /asset-generation", gameId="other-game", jobId=job["jobId"])[
            "statusCode"
        ]
        == 404
    )
    assert (
        unpack(call(generation, "GET /asset-generation", gameId="test-game", jobId=job["jobId"]))
        == job
    )


def test_generation_lease_does_not_automatically_retry(generation):
    job = unpack(call(generation, body=request()))
    claimed = unpack(call(generation, "POST /asset-generation/claim", username="example-worker"))
    assert claimed["job"]["jobId"] == job["jobId"]
    assert claimed["job"]["status"] == "GENERATING"
    assert "actor" not in claimed["job"] and "lease" not in claimed["job"]
    assert (
        unpack(call(generation, "POST /asset-generation/claim", username="example-worker"))["job"]
        is None
    )
    heartbeat = {"jobId": job["jobId"], "lease": claimed["lease"]}
    assert call(generation, "POST /asset-generation/heartbeat", body=heartbeat)["statusCode"] == 403
    assert (
        call(
            generation,
            "POST /asset-generation/complete",
            body={**heartbeat, "assetKey": "missing"},
            username="example-worker",
        )["statusCode"]
        == 400
    )
    stopped = unpack(
        call(
            generation,
            "POST /asset-generation/defer",
            body={**heartbeat, "message": "Check saved image output"},
            username="example-worker",
        )
    )
    assert stopped["status"] == "ATTENTION"
    assert (
        unpack(call(generation, "POST /asset-generation/claim", username="example-worker"))["job"]
        is None
    )


def image_bytes():
    def chunk(kind, data):
        return (
            len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0\xff\0\0"))
        + chunk(b"IEND", b"")
    )


def test_api_image_checkpoint_never_regenerates(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import base64
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(model_dump=lambda **_: {"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]}, _request_id="fictional-request")
    client = SimpleNamespace(images=SimpleNamespace(generate=generate))
    monkeypatch.setattr(worker.local, "run_process", lambda *a, **k: pytest.fail("Fresh image inference cannot use Codex"))
    job = {"jobId": "a" * 64, "type": "map", "name": "Harbor", "prompt": "A map", "model": "gpt-image-1"}
    image = worker.generate(job, tmp_path, lambda: None, client=client)
    assert image.read_bytes() == image_bytes()
    assert worker.generate(job, tmp_path, lambda: None, client=client) == image
    assert len(calls) == 1
    image.unlink()
    assert worker.generate(job, tmp_path, lambda: None, client=client).read_bytes() == image_bytes()
    assert len(calls) == 1


def test_uncertain_generation_and_malformed_images_are_not_retried(tmp_path, monkeypatch):
    (tmp_path / "generation-started.json").write_text(json.dumps({"startedAt": 1}))
    monkeypatch.setattr(
        worker.local, "run_process", lambda *a, **k: pytest.fail("Must not regenerate")
    )
    with pytest.raises(worker.local.Deferred):
        worker.generate({"jobId": "a" * 64}, tmp_path, lambda: None)
    image = tmp_path / "bad.png"
    image.write_bytes(image_bytes()[:-2])
    with pytest.raises(ValueError):
        worker.png(image)


def test_jobs_are_bounded_game_scoped_and_operation_reuse_rejects_edits(generation):
    first = request()
    unpack(call(generation, body=first))
    assert call(generation, body={**first, "prompt": "Changed after submit"})["statusCode"] == 400
    for n in range(27):
        unpack(call(generation, body=request(name=f"Fictional map {n}")))
    page = unpack(call(generation, "GET /asset-generation", gameId="test-game"))
    assert len(page["jobs"]) == 25 and page["cursor"]
    second = unpack(
        call(generation, "GET /asset-generation", gameId="test-game", cursor=page["cursor"])
    )
    assert len(second["jobs"]) == 3
    assert not set(j["jobId"] for j in page["jobs"]) & set(j["jobId"] for j in second["jobs"])
    assert (
        call(generation, "GET /asset-generation", gameId="other-game", cursor=page["cursor"])[
            "statusCode"
        ]
        == 400
    )


def test_publication_verifies_uploaded_image_and_worker_only_resume(generation):
    import base64
    import hashlib

    job = unpack(call(generation, body=request()))
    claimed = unpack(call(generation, "POST /asset-generation/claim", username="example-worker"))
    body = {"jobId": job["jobId"], "lease": claimed["lease"]}
    unpack(
        call(
            generation,
            "POST /asset-generation/defer",
            body={**body, "message": "Upload failed"},
            username="example-worker",
        )
    )
    resumed = unpack(
        call(
            generation,
            "POST /asset-generation/resume",
            body={"jobId": job["jobId"]},
            username="example-worker",
        )
    )
    assert resumed["lease"] != claimed["lease"]
    key = f"games/test-game/assets/generated-{job['jobId'][:40]}/original/image.png"
    checksum = base64.b64encode(hashlib.sha256(image_bytes()).digest()).decode()
    metadata = {
        "title": "Harbor road",
        "extra": {
            "assetGenerationJobId": job["jobId"],
            "assetType": "map",
            "sha256": checksum,
            "relationshipRole": "finished",
            "generation": {
                "method": "ai",
                "provider": "OpenAI",
                "model": job["model"],
                "cost": {"status": "unknown"},
            },
        }
    }
    generation.media.s3.put_object(
        Bucket=generation.media.BUCKET_NAME,
        Key=key,
        Body=image_bytes(),
        ContentType="image/png",
        ChecksumSHA256=checksum,
        ChecksumAlgorithm="SHA256",
        Metadata={"panther": base64.b64encode(json.dumps(metadata).encode()).decode()},
    )
    # Publication succeeds before the asynchronous materialized catalog event arrives.
    complete = {"jobId": job["jobId"], "lease": resumed["lease"], "assetKey": key}
    published = unpack(
        call(
            generation, "POST /asset-generation/complete", body=complete, username="example-worker"
        )
    )
    assert published["status"] == "PUBLISHED" and published["assetKey"] == key
    assert (
        unpack(
            call(
                generation,
                "POST /asset-generation/complete",
                body=complete,
                username="example-worker",
            )
        )["status"]
        == "PUBLISHED"
    )
    assert (
        call(
            generation,
            "POST /asset-generation/resume",
            body={"jobId": job["jobId"]},
            username="example-worker",
        )["statusCode"]
        == 400
    )


@pytest.mark.parametrize("asset_type", ["map", "portrait"])
@pytest.mark.parametrize("reported_model", [None, "Synthetic Tool Image v1"])
def test_publication_uses_supported_upload_and_hidden_request_lineage(
    tmp_path, monkeypatch, reported_model, asset_type
):
    import click

    file = tmp_path / "image.png"
    file.write_bytes(image_bytes())
    (tmp_path / "generation-result.json").write_text(
        json.dumps({"outputPath": "not-disclosed", "model": reported_model})
    )
    records = []
    monkeypatch.setattr(
        worker.cloud,
        "api",
        lambda *a, **k: (_ for _ in ()).throw(click.ClickException("Object not found")),
    )

    def upload(**kwargs):
        records.append({**kwargs, "metadata": json.loads(kwargs["metadata"].read_text())})

    monkeypatch.setattr(worker.cloud.upload, "callback", upload)
    job = {
        "jobId": "a" * 64,
        "gameId": "test-game",
        "type": "map",
        "name": "Harbor",
        "prompt": "A map",
    }
    if asset_type == "portrait":
        job.update(
            type="portrait",
            characterId="hero",
            characterReference={
                "characterId": "hero",
                "name": "River Scout",
                "revision": "a" * 32,
                "details": {"backstory": "Fictional scout"},
            },
        )
    key = worker.publish({}, job, tmp_path, file)
    assert len(records) == 2
    spec, image = records
    assert image["metadata"]["characterIds"] == (["hero"] if asset_type == "portrait" else [])
    if asset_type == "portrait":
        assert (
            json.loads((tmp_path / "generation.json").read_text())["characterReference"]
            == job["characterReference"]
        )
    assert spec["kind"] == "generation-provenance"
    assert spec["metadata"]["extra"]["relationshipRole"] == "intermediate"
    assert image["metadata"]["sourceKeys"] == [key.replace("image.png", "generation.json")]
    assert image["metadata"]["extra"]["generation"]["provider"] == "OpenAI"
    assert image["metadata"]["extra"]["generation"]["cost"]["status"] == "subscription"
    if reported_model is None:
        assert "model" not in image["metadata"]["extra"]["generation"]
    else:
        assert image["metadata"]["extra"]["generation"]["model"] == reported_model
    assert "prompt" not in image["metadata"]["extra"]
    assert json.loads((tmp_path / "generation.json").read_text())["request"]["prompt"] == "A map"


def test_expired_generation_explicit_resume_and_malformed_cursor(generation):
    job = unpack(call(generation, body=request()))
    claimed = unpack(call(generation, "POST /asset-generation/claim", username="example-worker"))
    generation.table().update_item(
        Key={"pk": "JOBS", "sk": job["jobId"]},
        UpdateExpression="SET leaseUntil=:past",
        ExpressionAttributeValues={":past": 1},
    )
    view = unpack(call(generation, "GET /asset-generation", gameId="test-game", jobId=job["jobId"]))
    assert view["status"] == "ATTENTION"
    resumed = unpack(
        call(
            generation,
            "POST /asset-generation/resume",
            body={"jobId": job["jobId"]},
            username="example-worker",
        )
    )
    assert resumed["job"]["status"] == "GENERATING" and resumed["lease"] != claimed["lease"]
    assert (
        call(generation, "GET /asset-generation", gameId="test-game", cursor="**bad**")[
            "statusCode"
        ]
        == 400
    )


def test_worker_process_uses_lock_and_reports_verified_publication(tmp_path, monkeypatch):
    file = tmp_path / "image.png"
    file.write_bytes(image_bytes())
    calls = []
    monkeypatch.setattr(worker, "generate", lambda job, folder, heartbeat: file)
    monkeypatch.setattr(
        worker,
        "publish",
        lambda config, job, folder, output: "games/test-game/assets/output/original/image.png",
    )
    monkeypatch.setattr(worker.cloud, "api", lambda *a, **k: calls.append((a, k)))
    worker.process({}, tmp_path, {"job": {"jobId": "a" * 64}, "lease": "fictional-lease"})
    assert calls[-1][0][2] == "/asset-generation/complete"
    assert calls[-1][1]["json"]["assetKey"].endswith("image.png")


def test_portrait_request_pins_registered_character_and_rejects_other_game(generation):
    catalog = boto3.resource("dynamodb").Table("narrative-games")
    details = {"backstory": "A fictional river scout", "statistics": []}
    catalog.put_item(
        Item={
            "pk": "GAME#test-game",
            "sk": "CHARACTER#hero",
            "gameId": "test-game",
            "id": "hero",
            "name": "River Scout",
            "detailsRevision": "a" * 32,
            "detailsJson": json.dumps(details),
        }
    )
    body = request(type="portrait", characterId="hero", prompt="A river scout portrait")
    job = unpack(call(generation, body=body))
    assert job["characterReference"] == {
        "characterId": "hero",
        "name": "River Scout",
        "revision": "a" * 32,
        "details": details,
    }
    catalog.update_item(
        Key={"pk": "GAME#test-game", "sk": "CHARACTER#hero"},
        UpdateExpression="SET detailsRevision=:r",
        ExpressionAttributeValues={":r": "b" * 32},
    )
    assert unpack(call(generation, body=body))["characterReference"] == job["characterReference"]
    assert (
        call(generation, body=request(type="portrait", characterId="missing"))["statusCode"] == 400
    )
    assert call(generation, body=request(characterId="hero"))["statusCode"] == 200
    assert call(generation, body=request(characterId="hero", selectAsPortrait=True))["statusCode"] == 400


def test_asset_worker_rejects_git_and_home_before_authentication(tmp_path, monkeypatch):
    import click

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").write_text("gitdir: elsewhere")
    monkeypatch.setattr(
        worker.cloud, "configuration", lambda: pytest.fail("Must reject before authentication")
    )
    for root in [checkout / "private-jobs", Path.home(), Path("/")]:
        with pytest.raises(click.ClickException, match="outside a Git checkout"):
            worker.run_worker(root, True)
    assert not (checkout / "private-jobs").exists()


def test_generation_submission_registers_active_source_guard(generation):
    job = unpack(call(generation, body=request()))
    import asset_archive
    row = asset_archive.db().get_item(Key={'pk': 'asset-references-v1#test-game', 'sk': 'asset-generation:' + job['jobId']})['Item']
    assert row['keys'] == []
    assert row['active'] == {'table': generation.table().name, 'pk': 'JOBS', 'sk': job['jobId']}


def test_generation_options_and_prompt_only_contract(generation):
    options = unpack(call(generation, "GET /asset-generation", gameId="test-game", view="options"))
    kinds = {item["id"]: item for item in options["generationTypes"]}
    assert set(kinds) == {"image", "map", "blueprint", "location", "portrait"}
    assert {model["id"] for model in kinds["image"]["models"]} == {"gpt-image-2"}
    assert {style["id"] for style in kinds["image"]["styles"]} == generation.STYLES
    body = request(type="image", model="gpt-image-1-mini", style="watercolor")
    del body["name"]
    job = unpack(call(generation, body=body))
    assert "name" not in job and job["schemaVersion"] == 2
    assert job["model"] == "gpt-image-1-mini" and job["visualStyle"] == "watercolor"
    assert unpack(call(generation, body=body))["jobId"] == job["jobId"]
    assert call(generation, body={**body, "model":"gpt-image-1"})["statusCode"] == 400
    assert call(generation, body={**body, "model":"made-up-model"})["statusCode"] == 400
    assert call(generation, body={**body, "type":"video"})["statusCode"] == 400
    assert call(generation, "GET /asset-generation", gameId="missing-game", view="options")["statusCode"] == 400


def test_historical_operation_receipt_is_reused_without_resubmission(generation):
    body = request()
    job = unpack(call(generation, body=body))
    generation.table().update_item(Key={"pk":"JOBS","sk":job["jobId"]}, UpdateExpression="SET schemaVersion=:old", ExpressionAttributeValues={":old":1})
    reused = unpack(call(generation, body=body))
    assert reused["jobId"] == job["jobId"] and reused["schemaVersion"] == 1
    assert call(generation, body={**body,"prompt":"Changed"})["statusCode"] == 400
