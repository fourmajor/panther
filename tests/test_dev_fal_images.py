"""Dynamic fal image contracts and durable provider queue recovery (no API calls)."""
import importlib.util
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

TOOLS = Path(__file__).parents[1] / 'tools'
spec = importlib.util.spec_from_file_location('fal_image_worker_test', TOOLS / 'dev_image_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
import dev_fal_image_catalog as catalog  # noqa: E402

ENDPOINT = 'fal-ai/fictional-image'


def model(endpoint=ENDPOINT, required=None):
    return {'endpoint_id': endpoint, 'metadata': {'status': 'active', 'category': 'text-to-image', 'display_name': 'Fictional image'},
        'openapi': {'components': {'schemas': {'Input': {'type': 'object', 'required': required or ['prompt'], 'properties': {'prompt': {'type': 'string'}, 'num_images': {'type': 'integer', 'default': 2}, 'output_format': {'enum': ['jpeg', 'png']}, 'image_url': {'type': 'string'}}}, 'Output': {'type': 'object', 'properties': {'images': {'type': 'array', 'items': {'type': 'object', 'properties': {'url': {'type': 'string'}}}}}}}},
            'paths': {'/' + endpoint: {'post': {'requestBody': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Input'}}}}}}, '/' + endpoint + '/requests/{request_id}': {'get': {'responses': {'200': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Output'}}}}}}}}}}


def queued(tmp_path, kind="image"):
    store = worker.Store(tmp_path / 'db.sqlite')
    store.put('game', 'fictional', {'id': 'fictional', 'name': 'Imaginary game', 'description': '', 'visualStyle': 'watercolor'})
    store.put('service', 'images', {'status': 'RUNNING', 'updatedAt': __import__('time').time(), 'falAvailable': True})
    pinned = catalog.contract(model())
    pinned['priceEstimate'] = catalog.price_options({'prices': [{'endpoint_id': ENDPOINT, 'unit_price': .02, 'currency': 'USD', 'unit': 'images'}]}, '2026-10-03')[ENDPOINT]
    store.put('model-catalog', catalog.CATALOG_ID, {'schemaVersion': 1, 'complete': True, 'models': [pinned]})
    body = {'gameId': 'fictional', 'type': kind, 'name': 'A fictional river', 'prompt': 'A river beside a quiet forest', 'operationId': 'a' * 32, 'model': ENDPOINT}
    if kind == 'portrait':
        store.create_character({'gameId': 'fictional', 'id': 'guide', 'name': 'Guide'})
        body.update(characterId='guide', selectAsPortrait=True)
    result = store.submit_asset_generation(body)
    return store, result['jobId']


class Fal:
    def __init__(self, error=False, queued=False):
        self.calls, self.error, self.queued = [], error, queued

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == 'POST':
            if self.error:
                raise TimeoutError('private provider details')
            return {'request_id': 'fictional-request', 'status_url': f'https://queue.fal.run/{ENDPOINT}/requests/fictional-request/status', 'response_url': f'https://queue.fal.run/{ENDPOINT}/requests/fictional-request'}
        if url.endswith('/status'):
            return {'status': 'IN_QUEUE' if self.queued else 'COMPLETED', 'request_id': 'fictional-request'}
        return {'images': [{'url': 'https://fal.media/fictional/image.jpg'}], 'seed': 42}


def download(url, target):
    assert url == 'https://fal.media/fictional/image.jpg'
    buffer = BytesIO()
    Image.new('RGB', (16, 8), 'blue').save(buffer, format='JPEG')
    worker.retain(target, buffer.getvalue())


def test_complete_contract_prices_pin_selected_defaults_and_model(tmp_path):
    store, identity = queued(tmp_path)
    before = store.get('asset-generation', identity)
    assert before['modelContract']['defaults'] == {'num_images': 1, 'output_format': 'png'}
    store.put('model-catalog', catalog.CATALOG_ID, {'schemaVersion': 1, 'complete': True, 'models': []})
    fal = Fal()
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), SimpleNamespace(), 'gpt-image-1', fal=fal, downloader=download)
    job = store.get('asset-generation', identity)
    metadata, raw = store.object(job['assetKey'])
    assert raw.startswith(b'\xff\xd8') and metadata['contentType'] == 'image/jpeg'
    assert metadata['extra']['generation']['provider'] == 'fal'
    assert metadata['extra']['generation']['model'] == ENDPOINT
    assert metadata['extra']['generation']['cost']['status'] == 'unknown'
    assert metadata['extra']['costEstimate']['amount'] == '0.02'
    response = json.loads(store.object(metadata['sourceKeys'][1])[1])
    assert response == {'images': [{'url': 'https://fal.media/fictional/image.jpg'}], 'seed': 42}
    assert 'watercolor' in fal.calls[0][2]['json']['prompt']
    assert fal.calls[0][2]['headers']['X-Fal-No-Retry'] == '1'
    assert len([call for call in fal.calls if call[0] == 'POST']) == 1


def test_unknown_fal_submission_is_never_repeated(tmp_path):
    store, identity = queued(tmp_path)
    fal = Fal(error=True)
    root = worker.private_root(tmp_path / 'work')
    assert not worker.process(store, identity, root, SimpleNamespace(), 'gpt-image-1', fal=fal)
    assert store.get('asset-generation', identity)['outcomeUnknown'] is True
    assert 'private' not in json.dumps(store.asset_generation_view(store.get('asset-generation', identity)))
    assert not worker.process(store, identity, root, SimpleNamespace(), 'gpt-image-1', fal=fal)
    assert len(fal.calls) == 1


def test_pending_queue_resumes_read_only_and_preserves_original_response(tmp_path):
    store, identity = queued(tmp_path)
    fal = Fal(queued=True)
    root = worker.private_root(tmp_path / 'work')
    assert not worker.process(store, identity, root, SimpleNamespace(), 'gpt-image-1', fal=fal)
    assert store.get('asset-generation', identity)['status'] == 'IN_QUEUE'
    fal.queued = False
    assert worker.process(store, identity, root, SimpleNamespace(), 'gpt-image-1', fal=fal, downloader=download)
    assert len([call for call in fal.calls if call[0] == 'POST']) == 1


def test_publication_failure_recovers_without_inference(tmp_path, monkeypatch):
    store, identity = queued(tmp_path)
    fal = Fal()
    root = worker.private_root(tmp_path / 'work')
    publish = worker.publish
    monkeypatch.setattr(worker, 'publish', lambda *a, **kw: (_ for _ in ()).throw(ValueError('Synthetic database failure')))
    assert not worker.process(store, identity, root, SimpleNamespace(), 'gpt-image-1', fal=fal, downloader=download)
    job = store.get('asset-generation', identity)
    assert job['publicationRecoveryAvailable']
    job['status'] = 'GENERATING'
    store.put('asset-generation', identity, job, 'fictional')
    monkeypatch.setattr(worker, 'publish', publish)
    assert worker.process(store, identity, root, SimpleNamespace(), 'gpt-image-1', fal=None, downloader=lambda *a: pytest.fail('Downloaded twice'))
    assert len([call for call in fal.calls if call[0] == 'POST']) == 1


def test_rejects_required_reference_input_and_inactive_models():
    with pytest.raises(ValueError):
        catalog.contract(model(required=['prompt', 'image_url']))
    document = model()
    document['metadata']['status'] = 'deprecated'
    with pytest.raises(ValueError):
        catalog.contract(document)


def test_complete_pagination_cache_and_pricing_no_partial_replacement(tmp_path):
    store, _ = queued(tmp_path)
    class CatalogFal:
        def request(self, method, url, **kw):
            if url == catalog.PRICES:
                return {'prices': [{'endpoint_id': ENDPOINT, 'currency': 'USD', 'unit': 'images', 'unit_price': .02}]}
            if kw['params'].get('cursor'):
                return {'models': [model(required=['prompt', 'image_url'])], 'has_more': False, 'next_cursor': None}
            return {'models': [model()], 'has_more': True, 'next_cursor': 'next'}
    result = catalog.refresh(store, CatalogFal())
    assert result['complete'] and len(result['models']) == 1 and len(result['excluded']) == 1
    assert result['models'][0]['priceEstimate']['evidence']['response']['unit'] == 'images'
    class BrokenFal:
        def request(self, *a, **kw):
            return {'models': [model()], 'has_more': True, 'next_cursor': 'same'}
    with pytest.raises(ValueError):
        catalog.refresh(store, BrokenFal())
    assert store.get('model-catalog', catalog.CATALOG_ID) == result


def test_options_curate_models_without_erasing_cached_or_queued_contracts(tmp_path):
    store, job_id = queued(tmp_path)
    before = store.get('asset-generation', job_id)
    original = store.get('model-catalog', catalog.CATALOG_ID)
    curated = []
    for endpoint in ('fal-ai/flux-pro/v1.1', 'fal-ai/flux/schnell'):
        value = catalog.contract(model(endpoint))
        value['priceEstimate'] = {'amount': '.04', 'currency': 'USD', 'unit': 'megapixels'}
        curated.append(value)
    store.put('model-catalog', catalog.CATALOG_ID, {**original, 'models': [*original['models'], *curated]})
    store.put('model-pricing', catalog.VIDEO_PRICE_ID, {'schemaVersion': 1, 'prices': {
        'minimax/h3-max/text-to-video': {'amount': '.03', 'unit': 'seconds'},
        'minimax/h3-max/image-to-video': {'amount': '.04', 'unit': 'seconds'}}})
    options = store.asset_generation_options('fictional')
    image = next(item for item in options['generationTypes'] if item['id'] == 'image')
    assert [item['id'] for item in image['models']] == ['fal-ai/flux-pro/v1.1', 'gpt-image-2']
    assert image['defaultModel'] == 'fal-ai/flux-pro/v1.1'
    video = next(item for item in options['generationTypes'] if item['id'] == 'video')
    assert video['models'][0]['providerBasePrice']['amount'] == '.03'
    assert video['models'][0]['providerImageBasePrice']['amount'] == '.04'
    assert image['models'][0]['priceEstimate']['unit'] == 'megapixels'
    assert catalog.selected(store, ENDPOINT) == original['models'][0]
    assert store.get('asset-generation', job_id) == before


def test_fal_official_portrait_preserves_character_history(tmp_path):
    store, identity = queued(tmp_path, 'portrait')
    before = store.get('character', 'fictional:guide')
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), SimpleNamespace(), 'gpt-image-1', fal=Fal(), downloader=download)
    job = store.get('asset-generation', identity)
    after = store.get('character', 'fictional:guide')
    assert job['portraitAssigned'] and after['details']['thumbnailAssetKey'] == job['assetKey']
    assert after['revision'] != before['revision']
    history = store.list('history', 'fictional:guide')
    assert len(history) == 2 and any(item.get('previousDetails') == before['details'] for item in history)


def test_schema_checkpoint_change_rejected_before_paid_submission(tmp_path):
    store, identity = queued(tmp_path)
    root = worker.private_root(tmp_path / 'work')
    folder = root / identity
    folder.mkdir()
    worker.retain(folder / 'request.json', json.dumps({'provider': 'fal', 'endpoint': ENDPOINT, 'contractHash': 'changed', 'payload': {'prompt': 'changed'}}).encode())
    fal = Fal()
    assert not worker.process(store, identity, root, SimpleNamespace(), 'gpt-image-1', fal=fal)
    assert not fal.calls


def test_verified_megapixel_estimate_and_preserving_migration(tmp_path):
    store, identity = queued(tmp_path)
    job = store.get('asset-generation', identity)
    price = job['modelContract']['priceEstimate']
    price.update(amount='0.003', unit='megapixels')
    store.put('asset-generation', identity, job, 'fictional')
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), SimpleNamespace(), 'gpt-image-1', fal=Fal(), downloader=download)
    key = store.get('asset-generation', identity)['assetKey']
    metadata, raw = store.object(key)
    estimate = metadata['extra']['costEstimate']
    assert estimate['amount'] == '0.000000384' and estimate['quantity'] == '0.000128'
    assert estimate['measuredOutput'] == {'width': 16, 'height': 8}
    assert 'rounding' in estimate['scope'] and estimate['billingStatus'] == 'not-reconciled'
    assert metadata['extra']['generation']['cost']['status'] == 'unknown'
    # Simulate the first generated asset before measured estimates were introduced.
    del metadata['extra']['costEstimate']
    with store.connect() as db:
        db.execute('UPDATE objects SET metadata=? WHERE key=?', (json.dumps(metadata), key))
    import dev_cost_estimates
    assert dev_cost_estimates.migrate(store, apply=True)['estimatedAssets'] >= 1
    projected, after = store.object(key)
    assert after == raw and projected['extra']['costEstimate']['amount'] == estimate['amount']
    with store.connect() as db:
        original = json.loads(db.execute('SELECT metadata FROM objects WHERE key=?', (key,)).fetchone()[0])
    assert original == metadata


def test_provider_blocked_image_is_retained_but_never_published_or_selected(tmp_path):
    store, identity = queued(tmp_path,kind='portrait')
    class Blocked(Fal):
        def request(self,method,url,**kwargs):
            result=super().request(method,url,**kwargs)
            if method=='GET' and not url.endswith('/status'):
                result['has_nsfw_concepts']=[True]
            return result
    fal=Blocked()
    root=worker.private_root(tmp_path/'work')
    assert not worker.process(store,identity,root,SimpleNamespace(),'gpt-image-2',fal=fal,downloader=lambda *args:pytest.fail('Blocked output must not download'))
    job=store.get('asset-generation',identity)
    assert job['providerRejected'] and not job['outcomeUnknown']
    assert not job.get('publicationRecoveryAvailable') and not job.get('assetKey')
    assert store.get('character','fictional:guide')['details']['thumbnailAssetKey'] is None
    assert store.asset_generation_view(job)['message']=='The provider blocked this image. Edit the prompt before generating again.'
    assert (root/identity/'provider-response.json').is_file()
    assert not worker.process(store,identity,root,SimpleNamespace(),'gpt-image-2',fal=fal)
    assert sum(method=='POST' for method,*_ in fal.calls)==1
