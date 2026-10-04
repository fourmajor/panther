"""Generic media options, immutable submissions, real receipts and title edits."""
import base64
import hashlib
from io import BytesIO
import json
from types import SimpleNamespace
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
import dev_image_worker as images_worker
import dev_text_asset as text_worker
from dev_server import Store


def store_at(tmp_path):
    store = Store(tmp_path / 'database.sqlite')
    store.put('game', 'imaginary', {'id': 'imaginary', 'name': 'Imaginary', 'description': '', 'visualStyle': 'watercolor'})
    return store


def request(kind='text', **extra):
    return {'gameId': 'imaginary', 'type': kind, 'prompt': 'A fictional river journey', 'operationId': 'a' * 32, **extra}


class Responses:
    def __init__(self, text, error=None):
        self.calls, self.text, self.error = [], text, error

    def create(self, **body):
        self.calls.append(body)
        if self.error:
            raise self.error
        return SimpleNamespace(id='response-fictional', output_text=json.dumps(self.text), model_dump=lambda **kw: {'status': 'completed', 'model': body['model'], 'usage': {'total_tokens': 12}})


def test_options_honest_and_narration_failure_does_not_hide_other_media(tmp_path, monkeypatch):
    store = store_at(tmp_path)
    monkeypatch.setattr(store, 'generation_capabilities', lambda: dict.fromkeys(('images', 'editorial', 'video', 'narration'), True))
    monkeypatch.setattr(store, 'narration_voices', lambda: (_ for _ in ()).throw(ValueError('not configured')))
    kinds = {entry['id']: entry for entry in store.asset_generation_options('imaginary')['generationTypes']}
    assert kinds['text']['available'] and kinds['map']['available']
    assert not kinds['narration']['available'] and kinds['narration']['voices'] == []
    assert {m['id'] for m in kinds['map']['models']} == {'gpt-image-2'}
    assert [m['id'] for m in kinds['video']['models']] == ['h3-max', 'veo-3.1-fast', 'kling-3-pro']
    assert all(m['inputs']['optionalInitialImage'] for m in kinds['video']['models'])


def test_titleless_submission_pins_model_style_and_operation(tmp_path):
    store = store_at(tmp_path)
    body = request('map', model='gpt-image-1-mini', style='anime')
    created = store.submit_asset_generation(body)
    job = store.get('asset-generation', created['jobId'])
    assert 'name' not in job and job['mediaType'] == 'image'
    assert job['model'] == 'gpt-image-1-mini' and job['visualStyle'] == 'anime'
    assert store.submit_asset_generation(body)['jobId'] == job['jobId']
    with pytest.raises(ValueError, match='Operation reused'):
        store.submit_asset_generation({**body, 'style': 'watercolor'})
    with pytest.raises(ValueError, match='available model'):
        store.submit_asset_generation(request('map', model='invented', operationId='b' * 32))


def test_text_actual_output_and_receipts_published_once(tmp_path):
    store = store_at(tmp_path)
    identity = store.submit_asset_generation(request())['jobId']
    responses = Responses({'title': 'River journey', 'markdown': '# River journey\n\nThe boat departed.'})
    client = SimpleNamespace(responses=responses)
    assert text_worker.process(store, identity, tmp_path / 'work', client, 'gpt-5-mini')
    job = store.get('asset-generation', identity)
    metadata, raw = store.object(job['assetKey'])
    assert job['status'] == 'PUBLISHED' and job['name'] == 'River journey'
    assert raw == b'# River journey\n\nThe boat departed.' and metadata['contentType'] == 'text/markdown'
    assert metadata['extra']['responseId'] == 'response-fictional'
    assert len(metadata['sourceKeys']) == 2
    assert not text_worker.process(store, identity, tmp_path / 'work', client, 'gpt-5-mini')
    assert len(responses.calls) == 1


def test_text_unknown_never_retries(tmp_path):
    store = store_at(tmp_path)
    identity = store.submit_asset_generation(request())['jobId']
    responses = Responses({}, TimeoutError())
    assert not text_worker.process(store, identity, tmp_path / 'work', SimpleNamespace(responses=responses), 'gpt-5-mini')
    assert store.get('asset-generation', identity)['outcomeUnknown']
    assert not text_worker.process(store, identity, tmp_path / 'work', SimpleNamespace(responses=responses), 'gpt-5-mini')
    assert len(responses.calls) == 1 and not store.objects('imaginary')


def test_video_frame_exact_pin_and_narration_words(tmp_path, monkeypatch):
    store = store_at(tmp_path)
    key = 'games/imaginary/assets/map/original/map.png'
    buffer = BytesIO()
    Image.new('RGB', (160, 90)).save(buffer, format='PNG')
    raw = buffer.getvalue()
    with store.connect() as db:
        db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, 'imaginary', json.dumps({'contentType': 'image/png'}), raw, 'now'))
    created = store.submit_asset_generation(request('video', model='h3-max-image', inputs={'initialImageKey': key, 'duration': 8, 'aspectRatio': '16:9'}))
    job = store.get('asset-generation', created['jobId'])
    assert job['imagePin']['sha256'] == base64.b64encode(hashlib.sha256(raw).digest()).decode()
    assert job['inputRefs'] == [job['imagePin']] and job['sourceKeys'] == [key]
    for index, family in enumerate(('h3-max', 'veo-3.1-fast', 'kling-3-pro')):
        payload = request('video', model=family, operationId=str(index + 3) * 32, inputs={'initialImageKey': key})
        selected = store.submit_asset_generation(payload)
        pinned = store.get('asset-generation', selected['jobId'])
        assert pinned['model'] == family + '-image'
        assert pinned['request']['model'] == family
        assert pinned['imagePin'] == job['imagePin']
        assert store.submit_asset_generation(payload)['jobId'] == selected['jobId']
    monkeypatch.setattr(store, 'narration_voices', lambda: {'voices': [{'id': 'fictional-voice', 'name': 'Narrator'}]})
    created = store.submit_asset_generation(request('narration', operationId='b' * 32, inputs={'voiceId': 'fictional-voice', 'direction': 'Warm'}))
    job = store.get('asset-generation', created['jobId'])
    assert job['text'] == job['prompt'] and job['voiceId'] == 'fictional-voice' and job['direction'] == 'Warm'
    assert not images_worker.process(store, job['jobId'], tmp_path / 'work', None, 'gpt-image-1')


def test_rename_changes_only_title_with_history_checksum_and_idempotence(tmp_path):
    store = store_at(tmp_path)
    key = 'games/imaginary/assets/prose/original/text.md'
    metadata = {'title': 'Old title', 'extra': {'version': {'preserved': True}}}
    raw = b'Immutable words'
    with store.connect() as db:
        db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, 'imaginary', json.dumps(metadata), raw, 'now'))
    body = {'gameId': 'imaginary', 'key': key, 'title': 'New title', 'operationId': 'c' * 32, 'sha256': base64.b64encode(hashlib.sha256(raw).digest()).decode()}
    assert store.rename_asset(body) == store.rename_asset(body)
    assert store.rename_asset(body)['asset']['metadata']['title'] == 'New title'
    revised, preserved = store.object(key)
    assert preserved == raw and revised == {**metadata, 'title': 'New title'}
    assert len(store.list('asset-metadata-history', 'imaginary')) == 1
    assert store.list('asset-metadata-history', 'imaginary')[0]['previousMetadata'] == metadata
    with pytest.raises(FileExistsError, match='changed'):
        store.rename_asset({**body, 'operationId': 'd' * 32, 'sha256': 'invalid'})


def test_image_generated_title_selected_model_and_title_unknown_prevents_media(tmp_path):
    store = store_at(tmp_path)
    identity = store.submit_asset_generation(request('image', model='gpt-image-2'))['jobId']
    class Images:
        def __init__(self):
            self.calls = []
        def generate(self, **body):
            self.calls.append(body)
            buffer = BytesIO()
            Image.new('RGB', (8, 8)).save(buffer, format='PNG')
            return SimpleNamespace(_request_id='fictional-image', model_dump=lambda **kw: {'data': [{'b64_json': base64.b64encode(buffer.getvalue()).decode()}]})
    images = Images()
    client = SimpleNamespace(images=images, responses=Responses({'title': 'River boat'}))
    assert images_worker.process(store, identity, tmp_path / 'work', client, 'gpt-image-1')
    job = store.get('asset-generation', identity)
    assert job['name'] == 'River boat' and images.calls[0]['model'] == 'gpt-image-2'
    metadata, _ = store.object(job['assetKey'])
    assert metadata['title'] == 'River boat' and metadata['extra']['titleGeneration']['provider'] == 'OpenAI'
    images_worker.asset_metadata.validate_generation(metadata['extra']['titleGeneration'])
    identity = store.submit_asset_generation(request('map', operationId='b' * 32))['jobId']
    client.responses = Responses({}, TimeoutError())
    assert not images_worker.process(store, identity, tmp_path / 'work', client, 'gpt-image-1')
    assert store.get('asset-generation', identity)['outcomeUnknown']
    assert len(images.calls) == 1
    assert not images_worker.process(store, identity, tmp_path / 'work', client, 'gpt-image-1')
    assert len(client.responses.calls) == 1


@pytest.mark.parametrize('raw,visible', [('DONE', 'PUBLISHED'), ('IN_QUEUE', 'QUEUED'), ('SUBMITTED', 'QUEUED'), ('IN_PROGRESS', 'GENERATING'), ('COMPOSING', 'GENERATING')])
def test_generic_state_projection_preserves_real_worker_records(tmp_path, raw, visible):
    import time
    store = store_at(tmp_path)
    job = {'gameId': 'imaginary', 'jobId': 'fictional', 'status': raw, 'mediaType': 'video'}
    store.put('asset-generation', 'fictional', job, 'imaginary')
    store.put('service', 'video', {'status': 'RUNNING', 'updatedAt': time.time() - 60})
    assert store.asset_generation_view(job)['status'] == visible
    assert store.get('asset-generation', 'fictional') == job


def test_completed_title_contract_repair_reuses_receipt_without_another_title_request(tmp_path):
    from panther_journal.asset_generation_title import request_for, validate_response
    from dev_playback_worker import retain
    store = store_at(tmp_path)
    identity = store.submit_asset_generation(request('image', model='gpt-image-2'))['jobId']
    job = store.get('asset-generation', identity)
    job.update(status='ATTENTION', titlePhase='GENERATING')
    store.put('asset-generation', identity, job, 'imaginary')
    title = 'A' * 81
    folder = tmp_path / 'work' / identity
    folder.mkdir(parents=True)
    retain(folder / 'title-request.json', json.dumps(request_for(job['type'], job['prompt'])).encode())
    receipt = {'id':'retained-title','responseId':'retained-title','status':'completed','output_text':json.dumps({'title':title})}
    retain(folder / 'title-response.json', json.dumps(receipt).encode())
    buffer = BytesIO()
    Image.new('RGB', (8, 8)).save(buffer, format='PNG')
    images = []
    def generate(**body):
        images.append(body)
        return SimpleNamespace(_request_id='fictional-image',model_dump=lambda **kw:{'data':[{'b64_json':base64.b64encode(buffer.getvalue()).decode()}]})
    client = SimpleNamespace(images=SimpleNamespace(generate=generate),responses=Responses({},AssertionError('Title inference must not repeat')))
    assert images_worker.process(store,identity,tmp_path/'work',client,'gpt-image-2')
    assert store.get('asset-generation',identity)['name'] == title
    assert not client.responses.calls and len(images) == 1
    assert not images_worker.process(store,identity,tmp_path/'work',client,'gpt-image-2')
    assert len(images) == 1
    with pytest.raises(ValueError):
        validate_response({**receipt,'output_text':json.dumps({'title':'A'*161})})
