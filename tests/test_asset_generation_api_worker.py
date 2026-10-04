"""Installed hosted worker uses direct API inference without repeating uncertain calls."""
import base64
import json
import time
from types import SimpleNamespace

import pytest

from panther_journal import asset_generation as worker
from test_asset_generation import image_bytes


class Client:
    def __init__(self, fail_image=False, fail_title=False):
        self.image_calls, self.title_calls = [], []
        self.fail_image, self.fail_title = fail_image, fail_title
        self.images = SimpleNamespace(generate=self.image)
        self.responses = SimpleNamespace(create=self.title)

    def image(self, **kwargs):
        self.image_calls.append(kwargs)
        if self.fail_image:
            raise TimeoutError("private request data")
        return SimpleNamespace(model_dump=lambda **_: {"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}], "usage": {"total_tokens": 12}}, _request_id="fictional-image-request")

    def title(self, **kwargs):
        self.title_calls.append(kwargs)
        if self.fail_title:
            raise TimeoutError("private title data")
        return SimpleNamespace(model_dump=lambda **_: {"status": "completed", "model": "fictional-title-model", "usage": {"total_tokens": 6}}, output_text='{"title":"Harbor at Dawn"}', id="fictional-title-response")


def job(**extra):
    return {"schemaVersion": 2, "jobId": "a" * 64, "gameId": "fictional", "type": "map", "prompt": "A harbor map", "visualStyle": "watercolor", "model": "gpt-image-1", **extra}


@pytest.mark.parametrize("model", ["gpt-image-2", "gpt-image-1", "gpt-image-1.5", "gpt-image-1-mini"])
def test_selected_model_style_and_real_title_are_durable(tmp_path, model, monkeypatch):
    monkeypatch.setattr(worker.local, "run_process", lambda *a, **k: pytest.fail("No fresh Codex calls"))
    request = job(model=model)
    client = Client()
    result = worker.generate(request, tmp_path, lambda: None, client=client)
    assert request["name"] == "Harbor at Dawn"
    assert client.image_calls[0]["model"] == model
    assert "Visual style: watercolor" in client.image_calls[0]["prompt"]
    assert client.image_calls[0]["output_format"] == "png"
    assert request["titleGeneration"]["evidence"]["usage"]["total_tokens"] == 6
    result.unlink()
    recovered_job = job(model=model)
    assert worker.generate(recovered_job, tmp_path, lambda: None, client=client).read_bytes() == image_bytes()
    assert recovered_job["name"] == "Harbor at Dawn"
    assert len(client.title_calls) == len(client.image_calls) == 1


@pytest.mark.parametrize("failed", ["title", "image"])
def test_unknown_submission_has_no_automatic_retry(tmp_path, failed):
    client = Client(fail_image=failed == "image", fail_title=failed == "title")
    request = job()
    for _ in range(2):
        with pytest.raises(worker.local.Deferred):
            worker.generate(request, tmp_path, lambda: None, client=client)
    assert len(client.title_calls) == 1
    assert len(client.image_calls) == (1 if failed == "image" else 0)
    assert not (tmp_path / "image.png").exists()


def test_historical_subscription_result_recovers_without_new_inference(tmp_path, monkeypatch):
    root = tmp_path / "historical"
    generated = root / "generated_images"
    generated.mkdir(parents=True)
    original = generated / "image.png"
    original.write_bytes(image_bytes())
    monkeypatch.setenv("CODEX_HOME", str(root))
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "generation-started.json").write_text(json.dumps({"schemaVersion": 1, "startedAt": time.time() - 1}))
    (folder / "generation-result.json").write_text(json.dumps({"outputPath": str(original), "model": "historically-reported-model"}))
    client = Client()
    assert worker.generate(job(name="Historical map"), folder, lambda: None, client=client).read_bytes() == image_bytes()
    assert not client.image_calls and not client.title_calls


def test_symlinked_checkpoint_cannot_dispatch(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text('{}')
    (tmp_path / "image-request.json").symlink_to(outside)
    client = Client()
    with pytest.raises(ValueError, match="Symlinked"):
        worker.generate(job(), tmp_path, lambda: None, client=client)
    assert not client.image_calls and not client.title_calls


def test_api_publication_retains_actual_model_title_requests_and_usage(tmp_path, monkeypatch):
    import click
    request, client = job(model='gpt-image-1-mini'), Client()
    image = worker.generate(request, tmp_path, lambda: None, client=client)
    published = []
    def absent(*args, **kwargs):
        raise click.ClickException('Object not found')
    def upload(**kwargs):
        published.append((kwargs['kind'], json.loads(kwargs['metadata'].read_text())))
    monkeypatch.setattr(worker.cloud, 'api', absent)
    monkeypatch.setattr(worker.cloud.upload, 'callback', upload)
    key = worker.publish({}, request, tmp_path, image)
    assert key.endswith('/image.png')
    assert published[1][1]['title'] == 'Harbor at Dawn'
    generation = published[1][1]['extra']['generation']
    assert generation['tool'] == 'OpenAI Images API'
    assert generation['model'] == 'gpt-image-1-mini'
    assert generation['cost'] == {'status': 'unknown'}
    assert generation['evidence']['usage'] == {'total_tokens': 12}
    document = json.loads((tmp_path / 'generation.json').read_text())
    assert document['providerRequest']['model'] == 'gpt-image-1-mini'
    assert document['providerResponse']['requestId'] == 'fictional-image-request'
    assert document['titleResponse']['responseId'] == 'fictional-title-response'
