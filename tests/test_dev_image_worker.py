"""Direct API image publication preserves checkpoints and character edit conflicts."""
import base64
import importlib.util
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

spec = importlib.util.spec_from_file_location('dev_image_worker', Path(__file__).parents[1] / 'tools/dev_image_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class Images:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def generate(self, **request):
        self.calls.append(request)
        if self.error:
            raise self.error
        buffer = BytesIO()
        Image.new('RGB', (8, 8), 'blue').save(buffer, format='PNG')
        data = {'data': [{'b64_json': base64.b64encode(buffer.getvalue()).decode()}], 'created': 1, 'usage': {'total_tokens': 10}}
        return SimpleNamespace(_request_id='req-fictional', model_dump=lambda **kw: data)


def queued(tmp_path, kind='map'):
    store = worker.Store(tmp_path / 'private.sqlite')
    store.put('game', 'fictional', {'id': 'fictional', 'name': 'Imaginary game', 'description': '', 'visualStyle': 'watercolor'})
    if kind == 'portrait':
        store.create_character({'gameId': 'fictional', 'id': 'guide', 'name': 'Guide'})
    body = {'gameId': 'fictional', 'type': kind, 'name': 'Imaginary ' + kind, 'prompt': 'A fictional river journey', 'operationId': 'a' * 32}
    if kind == 'portrait':
        body['characterId'] = 'guide'
        body['selectAsPortrait'] = True
    submitted = store.submit_asset_generation(body)
    return store, submitted['jobId']


@pytest.mark.parametrize('kind', ['map', 'blueprint', 'location', 'portrait'])
def test_real_png_published_with_preserved_response_lineage(tmp_path, kind):
    store, identity = queued(tmp_path, kind)
    images = Images()
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), SimpleNamespace(images=images), 'gpt-image-1')
    job = store.get('asset-generation', identity)
    assert job['status'] == 'PUBLISHED'
    meta, png = store.object(job['assetKey'])
    assert png.startswith(b'\x89PNG')
    assert meta['kind'] == kind and meta['extra']['generation']['model'] == 'gpt-image-1'
    assert meta['extra']['generation']['cost'] == {'status': 'unknown'}
    worker.asset_metadata.validate_generation(meta['extra']['generation'])
    worker.asset_metadata.validate_version(meta['extra']['version'], job['assetKey'])
    assert len(meta['sourceKeys']) == 2
    response_meta, response = store.object(meta['sourceKeys'][1])
    assert json.loads(response)['_request_id'] == 'req-fictional'
    assert response_meta['extra']['relationshipRole'] == 'intermediate'
    assert 'watercolor' in images.calls[0]['prompt']
    if kind == 'portrait':
        assert job['portraitAssigned'] is True
        assert store.get('character', 'fictional:guide')['details']['thumbnailAssetKey'] == job['assetKey']
        assert len(store.list('history', 'fictional:guide')) == 2
    assert not worker.process(store, identity, tmp_path / 'work', SimpleNamespace(images=images), 'gpt-image-1')
    assert len(images.calls) == 1


def test_unknown_request_never_repeats_and_hides_provider_error_body(tmp_path):
    store, identity = queued(tmp_path)
    images = Images(error=TimeoutError('secret provider body'))
    assert not worker.process(store, identity, worker.private_root(tmp_path / 'work'), SimpleNamespace(images=images), 'gpt-image-1')
    job = store.get('asset-generation', identity)
    assert job['status'] == 'ATTENTION' and job['outcomeUnknown'] is True
    assert job['message'] == 'Image generation could not be confirmed.'
    assert 'secret' not in job['message']
    assert 'secret provider body' not in str(store.asset_generation_view(job))
    assert not worker.process(store, identity, tmp_path / 'work', SimpleNamespace(images=images), 'gpt-image-1')
    assert len(images.calls) == 1
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM objects').fetchone()[0] == 0


def test_retained_response_publishes_without_second_provider_request(tmp_path, monkeypatch):
    store, identity = queued(tmp_path)
    images = Images()
    original = worker.publish
    monkeypatch.setattr(worker, 'publish', lambda *a: (_ for _ in ()).throw(RuntimeError('interrupted publication')))
    assert not worker.process(store, identity, worker.private_root(tmp_path / 'work'), SimpleNamespace(images=images), 'gpt-image-1')
    assert store.get('asset-generation', identity)['publicationRecoveryAvailable']
    monkeypatch.setattr(worker, 'publish', original)
    worker.run(store.path, tmp_path / 'work', client=SimpleNamespace(images=images), model='different-requested-model', once=True)
    assert store.get('asset-generation', identity)['status'] == 'PUBLISHED'
    assert len(images.calls) == 1
    assert store.get('asset-generation', identity)['model'] == 'gpt-image-1'


def test_profile_edited_during_generation_is_never_overwritten(tmp_path):
    store, identity = queued(tmp_path, 'portrait')
    before = store.get('character', 'fictional:guide')
    changed = {**before, 'name': 'Changed guide', 'revision': 'changed-revision'}
    store.put('character', 'fictional:guide', changed, 'fictional')
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), SimpleNamespace(images=Images()), 'gpt-image-1')
    assert store.get('character', 'fictional:guide') == changed
    assert store.get('asset-generation', identity)['portraitAssigned'] is False


def test_legacy_unconfigured_queue_has_audited_one_time_upgrade(tmp_path):
    store, identity = queued(tmp_path)
    old = store.get('asset-generation', identity)
    old.update(status='ATTENTION', message=worker.LEGACY_MESSAGE)
    store.put('asset-generation', identity, old, 'fictional')
    worker.migrate_legacy(store)
    assert store.get('asset-generation', identity)['status'] == 'QUEUED'
    assert store.get('development-migration', 'images-api-v1:' + identity)['previousRecord'] == old
    worker.migrate_legacy(store)
    assert len([x for x in store.list('development-migration') if x.get('previousRecord')]) == 1


def test_queue_projects_actual_worker_health(tmp_path):
    store, identity = queued(tmp_path)
    assert store.asset_generation_view(store.get('asset-generation', identity))['status'] == 'ATTENTION'
    import time
    store.put('service', 'images', {'status': 'RUNNING', 'updatedAt': time.time()})
    assert store.asset_generation_view(store.get('asset-generation', identity))['status'] == 'QUEUED'
    store.put('service', 'images', {'status': 'RUNNING', 'updatedAt': time.time() - 121})
    assert store.asset_generation_view(store.get('asset-generation', identity))['status'] == 'ATTENTION'

def test_generation_view_hides_legacy_provider_and_filesystem_diagnostics(tmp_path):
    store, identity = queued(tmp_path)
    job = store.get('asset-generation', identity)
    job.update(status='ATTENTION', message='API 400: /private/provider-receipt.json invalid model response', error={'message': 'private backend diagnostics'}, errorCode=400)
    projected = store.asset_generation_view(job)
    assert projected['message'] == 'The image could not be generated. Try another prompt.'
    assert projected['error'] is None
    assert 'private' not in json.dumps(projected)

def test_rejected_symlink_checkpoint_stops_without_provider_call(tmp_path):
    store, identity = queued(tmp_path)
    root = worker.private_root(tmp_path / 'work')
    outside = worker.private_root(tmp_path / 'outside')
    (root / identity).symlink_to(outside, target_is_directory=True)
    images = Images()
    assert not worker.process(store, identity, root, SimpleNamespace(images=images), 'gpt-image-1')
    assert not images.calls
    assert store.get('asset-generation', identity)['status'] == 'ATTENTION'
    assert not list(outside.iterdir())
