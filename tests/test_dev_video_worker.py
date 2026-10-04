"""Explicit scene renders submit once, safely poll, and publish real media only."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('dev_video_worker', Path(__file__).parents[1] / 'tools/dev_video_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class Fal:
    def __init__(self, fail=False, pending=False):
        self.calls = []
        self.fail, self.pending = fail, pending
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == 'POST':
            if self.fail:
                raise TimeoutError('private-body')
            prefix = 'https://queue.fal.run/fal-ai/veo3.1/requests/request-example'
            return {'request_id': 'request-example', 'status_url': prefix + '/status', 'response_url': prefix}
        if url.endswith('/status'):
            return {'status': 'IN_PROGRESS' if self.pending else 'COMPLETED', 'request_id': 'request-example'}
        return {'video': {'url': 'https://fal.media/example.mp4'}}


def queued(tmp_path):
    store = worker.Store(tmp_path / 'private.sqlite')
    ref = {'episodeId': 'episode-example', 'sceneId': 'scene-example', 'revision': 'revision-example'}
    scene = {'gameId': 'fictional', 'episodeId': ref['episodeId'], 'id': ref['sceneId'], 'revision': ref['revision'], 'name': 'A journey'}
    store.put('scene-history', 'fictional:' + ':'.join(ref.values()), {'record': scene}, 'fictional')
    identity = 'a' * 64
    job = {'id': identity, 'jobId': identity, 'gameId': 'fictional', 'sceneRef': ref, 'sceneType': 'general', 'prompt': 'Travel through a fictional city', 'status': 'QUEUED'}
    store.put('scene-render', identity, job, 'fictional')
    return store, identity


def fake_download(url, target):
    worker.retain(target, b'real test bytes')


def fake_probe(file):
    return {'format': {'duration': '8'}, 'streams': [{'codec_type': 'video', 'width': 1280, 'height': 720}]}


def test_render_polls_and_resumes_without_repeated_submission(tmp_path):
    store, identity = queued(tmp_path)
    client = Fal(pending=True)
    root = worker.private_root(tmp_path / 'work')
    assert not worker.process(store, identity, root, client, downloader=fake_download, media_probe=fake_probe)
    assert store.get('scene-render', identity)['status'] == 'IN_PROGRESS'
    client.pending = False
    assert worker.process(store, identity, root, client, downloader=fake_download, media_probe=fake_probe)
    assert len([call for call in client.calls if call[0] == 'POST']) == 1
    job = store.get('scene-render', identity)
    assert job['status'] == 'DONE'
    metadata, video = store.object(job['outputKey'])
    assert video == b'real test bytes'
    assert metadata['extra']['sceneRef']['revision'] == 'revision-example'
    assert metadata['extra']['generation']['model'] == 'Veo 3.1 Fast'
    assert metadata['extra']['generation']['cost']['status'] == 'unknown'
    assert store.get('scene', 'fictional:scene-example') is None  # No silent selection or creation.


def test_unknown_post_never_repeats_or_publishes_video(tmp_path):
    store, identity = queued(tmp_path)
    client = Fal(fail=True)
    root = worker.private_root(tmp_path / 'work')
    assert not worker.process(store, identity, root, client)
    assert store.get('scene-render', identity)['status'] == 'UNKNOWN'
    assert not worker.process(store, identity, root, client)
    assert len(client.calls) == 1 and not store.objects('fictional')
    assert 'private-body' not in store.get('scene-render', identity)['message']


def test_model_routes_are_explicit_by_scene_type():
    assert worker.model_for({'sceneType': 'action'}) == 'kling-3-pro'
    assert worker.model_for({'sceneType': 'dialogue'}) == 'h3-max'
    assert worker.model_for({'sceneType': 'general'}) == 'veo-3.1-fast'
    assert worker.model_for({'sceneType': 'map', 'mapPin': {'key': 'example'}}) == 'veo-3.1-fast-image-silent'


def standalone(tmp_path, monkeypatch, **changes):
    import sys
    from types import SimpleNamespace
    store = worker.Store(tmp_path / 'standalone.sqlite')
    identity = 'b' * 64
    job = {'jobId': identity, 'gameId': 'fictional', 'mediaType': 'video', 'type': 'video',
           'model': 'veo-3.1-fast', 'prompt': 'A city at dawn', 'status': 'QUEUED',
           'inputs': {'duration': 8, 'aspectRatio': '16:9'}, 'inputRefs': [], 'sourceKeys': []}
    job.update(changes)
    store.put('asset-generation', identity, job, 'fictional')
    def ensure_title(store, kind, identity, job, folder, client):
        job['name'] = 'Dawn over the City'
        store.put(kind, identity, job, job['gameId'])
    monkeypatch.setitem(sys.modules, 'dev_asset_title', SimpleNamespace(ensure_title=ensure_title))
    return store, identity


def test_standalone_video_has_real_output_generated_title_and_no_scene(tmp_path, monkeypatch):
    store, identity = standalone(tmp_path, monkeypatch)
    client = Fal()
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), client,
                          record_kind='asset-generation', downloader=fake_download, media_probe=fake_probe)
    job = store.get('asset-generation', identity)
    assert job['status'] == 'PUBLISHED'
    metadata, _ = store.object(job['assetKey'])
    assert metadata['title'] == 'Dawn over the City'
    assert not any(k in metadata['extra'] for k in ('sceneRef', 'episodeId', 'sceneId'))
    assert not store.list('scene') and not store.list('episode')
    assert len([c for c in client.calls if c[0] == 'POST']) == 1
    assert not worker.process(store, identity, tmp_path / 'work', client, record_kind='asset-generation')


def test_standalone_video_missing_image_cannot_fallback_to_text(tmp_path, monkeypatch):
    store, identity = standalone(tmp_path, monkeypatch, model='veo-3.1-fast-image')
    client = Fal()
    assert not worker.process(store, identity, worker.private_root(tmp_path / 'work'), client, record_kind='asset-generation')
    assert not client.calls
    assert store.get('asset-generation', identity)['status'] == 'FAILED'


def test_standalone_unknown_submission_never_repeats(tmp_path, monkeypatch):
    store, identity = standalone(tmp_path, monkeypatch)
    client = Fal(fail=True)
    root = worker.private_root(tmp_path / 'work')
    assert not worker.process(store, identity, root, client, record_kind='asset-generation')
    assert store.get('asset-generation', identity)['status'] == 'UNKNOWN'
    assert not worker.process(store, identity, root, client, record_kind='asset-generation')
    assert len(client.calls) == 1


def test_standalone_image_model_pins_initial_frame_and_lineage(tmp_path, monkeypatch):
    import base64
    import hashlib
    import json
    from io import BytesIO
    from PIL import Image
    buffer = BytesIO()
    Image.new('RGB', (160, 90), 'blue').save(buffer, format='PNG')
    raw = buffer.getvalue()
    key = 'games/fictional/assets/starting-frame/original/frame.png'
    pin = {'key': key, 'sha256': base64.b64encode(hashlib.sha256(raw).digest()).decode(), 'size': len(raw), 'contentType': 'image/png'}
    store, identity = standalone(tmp_path, monkeypatch, model='veo-3.1-fast-image', imagePin=pin, inputRefs=[pin], visualStyle='watercolor')
    with store.connect() as db:
        db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, 'fictional', json.dumps({'kind': 'image', 'contentType': 'image/png'}), raw, '2026-01-01T00:00:00Z'))
    client = Fal()
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), client,
                          record_kind='asset-generation', downloader=fake_download, media_probe=fake_probe)
    payload = client.calls[0][2]['json']
    assert payload['image_url'] == 'data:image/png;base64,' + base64.b64encode(raw).decode()
    assert 'Visual style: watercolor' in payload['prompt']
    metadata, _ = store.object(store.get('asset-generation', identity)['assetKey'])
    assert key in metadata['sourceKeys']
    assert metadata['extra']['generation']['model'] == 'Veo 3.1 Fast'


def test_unknown_with_verified_queue_identity_resumes_without_post(tmp_path):
    store, identity = queued(tmp_path)
    client = Fal(pending=True)
    root = worker.private_root(tmp_path / 'work')
    worker.process(store, identity, root, client)
    job = store.get('scene-render', identity)
    job['status'] = 'UNKNOWN'
    store.put('scene-render', identity, job, 'fictional')
    client.pending = False
    assert worker.process(store, identity, root, client, downloader=fake_download, media_probe=fake_probe)
    assert len([call for call in client.calls if call[0] == 'POST']) == 1
    assert store.get('scene-render', identity)['status'] == 'DONE'


def test_completed_input_rejection_stops_polling_without_another_submission(tmp_path):
    store, identity = queued(tmp_path)
    client = Fal(pending=True)
    root = worker.private_root(tmp_path / 'work')
    worker.process(store, identity, root, client, downloader=fake_download, media_probe=fake_probe)
    class Rejected:
        def request(self, method, url, **kwargs):
            assert method == 'GET'
            if kwargs.get('completed_result'):
                raise worker.v.TerminalInputRejection('The provider rejected the video prompt because it exceeds its length limit.', {'detail': [{'type': 'string_too_long', 'input': 'synthetic-private-input'}]})
            return {'status': 'COMPLETED', 'request_id': 'request-example'}
    worker.process(store, identity, root, Rejected())
    assert store.get('scene-render', identity)['status'] == 'FAILED'
    assert b'synthetic-private-input' in (root / identity / 'provider-rejection.json').read_bytes()
    assert not worker.process(store, identity, root, Rejected())
    assert len([call for call in client.calls if call[0] == 'POST']) == 1


def test_reference_render_keeps_actual_endpoint_on_resume_and_selected_cast(tmp_path):
    import json
    from test_dev_video_conditioning import fixture
    store, identity = queued(tmp_path)
    reference_store, references = fixture(tmp_path / 'references')
    with reference_store.connect() as source, store.connect() as target:
        for row in source.execute('SELECT * FROM objects'):
            target.execute('INSERT INTO objects VALUES (?,?,?,?,?)', row)
    job = store.get('scene-render', identity)
    job.update(sceneType='dialogue', videoPromptPolicy=2,
        characterIds=['hero', 'absent'], characterContext=references['characterContext'],
        inputRefs=[c['portraitPin'] for c in references['characterContext']],
        preparedPrompt='Hero closes the door.', promptComposition={'schemaVersion': 2, 'visibleCharacterIds': ['hero']})
    store.put('scene-render', identity, job, 'fictional')

    class ReferenceFal(Fal):
        def request(self, method, url, **kwargs):
            if method == 'POST':
                self.calls.append((method, url, kwargs))
                prefix = 'https://queue.fal.run/minimax/h3-max/requests/request-example'
                return {'request_id': 'request-example', 'status_url': prefix + '/status', 'response_url': prefix}
            return super().request(method, url, **kwargs)

    client = ReferenceFal(pending=True)
    root = worker.private_root(tmp_path / 'work')
    assert not worker.process(store, identity, root, client, downloader=fake_download, media_probe=fake_probe)
    assert store.get('scene-render', identity)['endpoint'] == 'minimax/h3-max/reference-to-video'
    client.pending = False
    assert worker.process(store, identity, root, client, downloader=fake_download, media_probe=fake_probe)
    assert len([call for call in client.calls if call[0] == 'POST']) == 1
    finished = store.get('scene-render', identity)
    metadata, _ = store.object(finished['outputKey'])
    assert metadata['characterIds'] == ['hero']
    assert metadata['extra']['generation']['model'] == 'MiniMax H3 Max (post-trained by fal)'
    assert metadata['extra']['generation']['cost']['status'] == 'unknown'
    assert 'costEstimate' not in metadata['extra']  # Never reuse a different endpoint's price.
    request = json.loads((root / identity / 'request.json').read_text())
    assert len(request['payload']['reference_image_urls']) == 1
    assert 'Absent' not in request['payload']['prompt']


def test_long_prompt_is_submitted_once_and_original_is_retained(tmp_path):
    import json
    store, identity = queued(tmp_path)
    job = store.get('scene-render', identity)
    job['prompt'] = 'Travel through the city. ' + 'Architectural detail. ' * 400
    original = job['prompt']
    store.put('scene-render', identity, job, 'fictional')
    client = Fal()
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), client,
                          downloader=fake_download, media_probe=fake_probe)
    posts = [call for call in client.calls if call[0] == 'POST']
    assert len(posts) == 1 and len(posts[0][2]['json']['prompt']) <= 2500
    completed = store.get('scene-render', identity)
    assert completed['prompt'] == original and completed['promptFitting']['truncated']
    response = json.loads(store.object(completed['responseKey'])[1])
    assert response['promptFitting']['originalPrompt'] == original
    assert response['request']['payload']['prompt'] == posts[0][2]['json']['prompt']
