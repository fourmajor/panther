"""Local API worker preserves real stage contracts and fails closed on unknown requests."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('dev_editorial_worker', Path(__file__).parents[1] / 'tools/dev_editorial_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class Responses:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def create(self, **request):
        self.calls.append(request)
        if self.fail:
            raise TimeoutError('private request details')
        report = {'passed': True, 'title': 'The Crossing', 'markdown': 'A complete fictional chapter.', 'evidenceIds': ['creation'],
                  'uncertainties': [], 'decisions': [], 'selectedKeys': [], 'shots': [], 'edits': []}
        raw = {'id': 'resp-example-' + str(len(self.calls)), 'model': 'test-model', 'status': 'completed', 'usage': {'input_tokens': 20, 'output_tokens': 10}}
        return SimpleNamespace(id=raw['id'], output_text=json.dumps(report), model_dump=lambda **kwargs: raw)


def queued(tmp_path):
    store = worker.Store(tmp_path / 'private.sqlite')
    store.put('game', 'fictional', {'id': 'fictional', 'name': 'Fictional', 'description': '', 'visualStyle': 'watercolor'})
    identity = 'a' * 64
    job = {'jobId': identity, 'gameId': 'fictional', 'creation': {'schemaVersion': 3, 'target': 'novel', 'title': 'The Crossing',
           'brief': 'An imaginary journey', 'sourceKeys': [], 'contextKeys': []}, 'createdAt': 1, 'status': 'QUEUED'}
    store.put('editorial', identity, job, 'fictional')
    return store, identity


def test_full_novel_stages_publish_real_reviewed_output_without_cli(tmp_path, monkeypatch):
    store, identity = queued(tmp_path)
    responses = Responses()
    monkeypatch.setattr(worker.editorial.local, 'run_process', lambda *a, **kw: pytest.fail('CLI must never run'))
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), SimpleNamespace(responses=responses), 'test-model')
    job = store.get('editorial', identity)
    assert job['status'] == 'NOVEL_READY'
    assert len(responses.calls) == 11
    assert all(request['store'] is False for request in responses.calls)
    assert all(request['text']['format']['strict'] for request in responses.calls)
    tasks = sorted(store.list('editorial-task'), key=lambda task: task['ordinal'])
    assert [task['stage'] for task in tasks] == ['context'] + worker.editorial.PLAN['novel']
    assert all(task['status'] == 'DONE' and task['output']['sha256'] for task in tasks)
    chapter = store.get('chapter', identity)
    assert chapter['markdown'] == 'A complete fictional chapter.'
    metadata, raw = store.object(chapter['assetKey'])
    envelope = json.loads(raw)
    assert envelope['engine'] == 'openai-responses-api'
    assert envelope['payload']['review']['passed'] is True
    assert envelope['inputArtifacts']['novel-proof']['sha256']
    assert metadata['extra']['generation']['model'] == 'test-model'
    assert metadata['extra']['generation']['cost']['status'] == 'unknown'
    assert metadata['sourceKeys'] == envelope['sourceKeys']
    assert not worker.process(store, identity, tmp_path / 'work', SimpleNamespace(responses=responses), 'test-model')
    assert len(responses.calls) == 11


def test_unknown_request_blocks_no_automatic_retry_or_chapter(tmp_path):
    store, identity = queued(tmp_path)
    responses = Responses(fail=True)
    client = SimpleNamespace(responses=responses)
    assert not worker.process(store, identity, worker.private_root(tmp_path / 'work'), client, 'test-model')
    assert store.get('editorial', identity)['status'] == 'BLOCKED'
    assert 'unknown' in store.get('editorial', identity)['message']
    assert 'private request details' not in store.get('editorial', identity)['message']
    assert not worker.process(store, identity, tmp_path / 'work', client, 'test-model')
    assert len(responses.calls) == 1
    assert not store.list('chapter')
    assert len(list((tmp_path / 'work').rglob('request-failed.json'))) == 1


def test_interrupted_stage_requires_review_before_resubmission(tmp_path):
    store, identity = queued(tmp_path)
    store.put('editorial-task', identity + ':context', {'stage': 'context', 'status': 'PROCESSING'}, 'fictional')
    responses = Responses()
    assert not worker.process(store, identity, worker.private_root(tmp_path / 'work'), SimpleNamespace(responses=responses), 'test-model')
    assert store.get('editorial', identity)['status'] == 'BLOCKED'
    assert not responses.calls


def test_legacy_upgrade_keeps_audited_original_and_pins_now(tmp_path):
    store, identity = queued(tmp_path)
    old = store.get('editorial', identity)
    old.update(status='BLOCKED', message=worker.LEGACY_MESSAGE)
    store.put('editorial', identity, old, 'fictional')
    worker.migrate_legacy(store)
    assert store.get('editorial', identity)['status'] == 'QUEUED'
    audit = store.get('development-migration', 'editorial-api-v1:' + identity)
    assert audit['previousRecord'] == old
    worker.migrate_legacy(store)
    assert len(store.list('development-migration')) == 3  # Store's two preexisting schema migrations.


def test_changed_pinned_source_is_rejected(tmp_path):
    store, identity = queued(tmp_path)
    key = 'games/fictional/assets/example/original/source.txt'
    with store.connect() as db:
        db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, 'fictional', '{}', b'original', 'now'))
    reference = worker.pin(store, key, 'fictional')
    with store.connect() as db:
        db.execute('UPDATE objects SET data=? WHERE key=?', (b'changed', key))
    adapter = worker.Transport(store, store.get('editorial', identity), None, 'test-model')
    with pytest.raises(ValueError, match='checksum'):
        adapter.download(None, reference, tmp_path / 'source.txt')


def test_key_file_and_environment_file_require_private_permissions(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    path = tmp_path / '.env'
    path.write_text('OPENAI_API_KEY=fictional-test-key\n')
    path.chmod(0o644)
    with pytest.raises(ValueError, match='chmod 600'):
        worker.load_key(env_file=path)
    path.chmod(0o600)
    assert worker.load_key(env_file=path) == 'fictional-test-key'
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)


def test_selected_transcript_correction_and_independent_audit_preserve_raw(tmp_path):
    from test_editorial import raw
    store, identity = queued(tmp_path)
    doc = raw()
    doc['gameId'] = 'fictional'
    key = 'games/fictional/assets/transcript-example/original/raw.json'
    original = json.dumps(doc).encode()
    with store.connect() as db:
        db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, 'fictional', json.dumps({'kind': 'raw-transcript', 'contentType': 'application/json'}), original, 'now'))
    job = store.get('editorial', identity)
    job['creation']['sourceKeys'] = [key]
    store.put('editorial', identity, job, 'fictional')
    responses = Responses()
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), SimpleNamespace(responses=responses), 'test-model')
    assert len(responses.calls) == 13
    assert store.object(key)[1] == original
    artifact = store.get('editorial', identity)['artifacts']['corrected-transcript']
    corrected = json.loads(store.object(artifact['key'])[1])
    assert corrected['payload']['transcript']['segments'] == doc['segments']
    assert corrected['payload']['review']['passed'] is True
    assert corrected['sourceKeys'] == [key, store.get('editorial', identity)['artifacts']['context']['key'], store.get('editorial', identity)['artifacts']['correction']['key']]


@pytest.mark.parametrize('status,fragment', [(401, 'API key'), (403, 'permissions'), (429, 'quota'), (400, 'schema')])
def test_provider_errors_explain_action_without_request_body(tmp_path, status, fragment):
    class ProviderError(Exception):
        status_code = status
        request_id = 'req-example'
    class Fail:
        def create(self, **kwargs):
            raise ProviderError('private-body')
    store, identity = queued(tmp_path)
    assert not worker.process(store, identity, worker.private_root(tmp_path / 'work'), SimpleNamespace(responses=Fail()), 'test-model')
    message = store.get('editorial', identity)['message']
    assert fragment in message and 'req-example' in message and 'private-body' not in message


def test_unstarted_submitted_job_upgrades_but_started_job_does_not(tmp_path):
    store, identity = queued(tmp_path)
    job = store.get('editorial', identity)
    job['status'] = 'SUBMITTED'
    store.put('editorial', identity, job, 'fictional')
    worker.migrate_legacy(store)
    assert store.get('editorial', identity)['status'] == 'QUEUED'
    other = 'b' * 64
    store.put('editorial', other, {**job, 'jobId': other}, 'fictional')
    store.put('editorial-task', other + ':context', {'jobId': other, 'stage': 'context', 'status': 'RUNNING'}, 'fictional')
    worker.migrate_legacy(store)
    assert store.get('editorial', other)['status'] == 'SUBMITTED'


def test_metadata_kind_repair_is_audited_from_explicit_artifact_and_keeps_bytes(tmp_path):
    store, identity = queued(tmp_path)
    game = 'fictional'
    key = f'games/{game}/assets/editorial-example/original/novel-draft.json'
    raw = json.dumps({'entityType': 'EditorialArtifact', 'gameId': game, 'stage': 'novel-draft', 'payload': {'markdown': 'Original'}}).encode()
    metadata = {'extra': {'artifactType': 'novel-draft'}}
    with store.connect() as db:
        db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, game, json.dumps(metadata), raw, 'now'))
    worker.migrate_editorial_metadata(store)
    new_meta, new_raw = store.object(key)
    assert new_meta['kind'] == 'novel-draft' and new_raw == raw
    audits = [audit for audit in store.list('development-migration') if audit.get('assetKey') == key]
    assert len(audits) == 1 and audits[0]['previousMetadata'] == metadata
    worker.migrate_editorial_metadata(store)
    assert len([audit for audit in store.list('development-migration') if audit.get('assetKey') == key]) == 1


def test_completed_provider_response_reused_only_for_exact_request(tmp_path):
    store, identity = queued(tmp_path)
    class Complete(Responses):
        def create(self, **request):
            response = super().create(**request)
            raw = response.model_dump()
            raw['output'] = [{'type': 'message', 'content': [{'type': 'output_text', 'text': response.output_text}]}]
            return SimpleNamespace(id=raw['id'], output_text=response.output_text, model_dump=lambda **kw: raw)
    responses = Complete()
    adapter = worker.Transport(store, store.get('editorial', identity), SimpleNamespace(responses=responses), 'test-model')
    inputs = {'creation': store.get('editorial', identity)['creation'], 'catalog': {}, 'candidates': [], 'raw': None}
    folders = [tmp_path / 'work' / identity / attempt / 'revision-01-context' for attempt in ('context-first', 'context-recovery', 'context-changed')]
    for folder in folders:
        folder.mkdir(parents=True)
    first = adapter.agent(folders[0], 'context', inputs, lambda: None)
    assert adapter.agent(folders[1], 'context', inputs, lambda: None) == first
    assert len(responses.calls) == 1 and (folders[1] / 'reused-response.json').exists()
    inputs['catalog'] = {'game': {'name': 'Changed context'}}
    adapter.agent(folders[2], 'context', inputs, lambda: None)
    assert len(responses.calls) == 2


def test_offline_revalidation_publishes_original_review_after_guard_fix_without_network(tmp_path):
    store, identity = queued(tmp_path)
    class Complete(Responses):
        def create(self, **request):
            response = super().create(**request)
            raw = response.model_dump()
            raw['output'] = [{'type': 'message', 'content': [{'type': 'output_text', 'text': response.output_text}]}]
            return SimpleNamespace(id=raw['id'], output_text=response.output_text, model_dump=lambda **kw: raw)
    root = worker.private_root(tmp_path / 'work')
    client = SimpleNamespace(responses=Complete())
    assert worker.process(store, identity, root, client, 'test-model')
    job = store.get('editorial', identity)
    final = job['artifacts'].pop('novel-chapter')
    # Synthetic interrupted-publication fixture: provider response exists, final output does not.
    with store.connect() as db:
        db.execute("DELETE FROM records WHERE kind='chapter' AND id=?", (identity,))
        db.execute('DELETE FROM objects WHERE key IN (?,?)', (final['key'], final['key'][:-5] + '.md'))
    job.update(status='QUEUED', currentStage='novel-chapter')
    store.put('editorial', identity, job, 'fictional')
    class NoNetwork:
        def create(self, **request):
            pytest.fail('offline validation must never submit any API request')
    assert worker.process(store, identity, root, SimpleNamespace(responses=NoNetwork()), 'test-model', offline_revalidation=True)
    chapter = store.get('chapter', identity)
    envelope = json.loads(store.object(chapter['assetKey'])[1])
    assert envelope['apiResponse']['revalidation']['mode'] == 'offline-original-response-revalidation'
    assert envelope['payload']['chapter'] == 'A complete fictional chapter.'
    assert envelope['payload']['review']['passed'] is True


def test_chapter_runs_existing_screen_stages_and_atomically_publishes_owned_episode(tmp_path, monkeypatch):
    """Exercise the entire real stage graph with a synthetic provider response."""
    store, unused = queued(tmp_path)
    with store.connect() as db:
        db.execute("DELETE FROM records WHERE kind='editorial'")
    chapter_id = 'c' * 64
    key = 'games/fictional/assets/chapter-source/original/chapter.json'
    manuscript = {'gameId': 'fictional', 'title': 'The crossing', 'markdown': 'The travelers reach the gates at dusk.'}
    with store.connect() as db:
        db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, 'fictional', json.dumps({'kind': 'novel-chapter', 'contentType': 'application/json'}), json.dumps(manuscript).encode(), 'now'))
    store.put('chapter', chapter_id, {'id': chapter_id, 'gameId': 'fictional', 'title': manuscript['title'], 'assetKey': key}, 'fictional')
    job = store.submit_episode_adaptation('fictional', {'schemaVersion': 4, 'target': 'video', 'chapterId': chapter_id})

    class ScreenResponses(Responses):
        def create(self, **request):
            response = super().create(**request)
            value = json.loads(response.output_text)
            value['shots'] = [{'sceneId': 'SC01', 'shotId': 'SC01_SH01', 'durationSeconds': 8,
                              'description': 'The gates open at dusk.', 'camera': 'Wide', 'color': '#223344', 'subjects': []}]
            properties = request['text']['format']['schema']['properties']
            if 'sourceFacts' in properties:
                value['sourceFacts'] = []
            if 'episode' in properties:
                value['shots'] = []
                value['episode'] = {'schemaVersion': 1, 'title': 'The crossing', 'synopsis': 'The travelers arrive.', 'scenes': [
                    {'id': 'arrival', 'title': 'Arrival', 'type': 'general', 'prompt': 'The gates open at dusk.',
                     'narration': 'At dusk, the travelers arrived.', 'characterIds': [], 'referenceKeys': [], 'shotIds': ['SC01_SH01']}]}
            response.output_text = json.dumps(value)
            return response

    responses = ScreenResponses()
    monkeypatch.setattr(worker.editorial.local, 'run_process', lambda *args, **kwargs: pytest.fail('No parallel CLI pipeline'))
    assert worker.process(store, job['jobId'], worker.private_root(tmp_path / 'screen-work'), SimpleNamespace(responses=responses), 'test-model')
    completed = store.get('editorial', job['jobId'])
    assert completed['status'] == 'READY_FOR_VIDEO_DISCUSSION'
    assert len(responses.calls) == len(worker.stages_for(job))
    assert all(request['store'] is False for request in responses.calls)
    assert manuscript['markdown'] in json.dumps(responses.calls[0]['input'])
    episode = store.get('episode', 'fictional:' + job['episodeRef']['episodeId'])
    assert episode['production']['state'] == 'planned' and episode['sceneIds'] == ['arrival']
    scene = store.get('scene', 'fictional:' + episode['id'] + ':arrival')
    assert scene['narration'] == 'At dusk, the travelers arrived.'
    assert scene['planningState'] == 'needs-approval' and scene['storyboard']['origin'] == 'ai'
    assert scene['selectedOutputKey'] is None
    assert store.get('scene-history', 'fictional:' + episode['id'] + ':arrival:' + scene['revision'])['record'] == scene
    assert not store.list('scene-render') and not store.list('narration')


def test_resume_requires_confirmed_structural_failure_and_retains_audit(tmp_path):
    store=worker.Store(tmp_path/'resume.sqlite')
    store.put('game','fictional',{'id':'fictional','name':'Fictional'})
    job={'jobId':'a'*64,'gameId':'fictional','status':'FAILED','updatedAt':1,'message':'No structurally valid editorial output; retry later without spending or requesting editorial approval.'}
    store.put('editorial',job['jobId'],job,'fictional')
    body={'gameId':'fictional','jobId':job['jobId'],'expectedUpdatedAt':1}
    assert store.resume_editorial(body)['status']=='QUEUED'
    assert store.list('editorial-recovery','fictional')[0]['previousRecord']==job
    with pytest.raises(FileExistsError):
        store.resume_editorial(body)
    job.update(status='ATTENTION',message='Provider outcome unknown')
    store.put('editorial',job['jobId'],job,'fictional')
    with pytest.raises(ValueError,match='unknown provider'):
        store.resume_editorial(body)
