"""Real local audio worker contracts; fake provider never creates fake application previews."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from test_browser_recording import manifest, wav

spec = importlib.util.spec_from_file_location('dev_transcription_worker', Path(__file__).parents[1] / 'tools/dev_transcription_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def queued(tmp_path, mode='final'):
    store = worker.Store(tmp_path / 'private.sqlite')
    doc = manifest()
    store.put("game", doc["gameId"], {"id": doc["gameId"], "name": "Fictional game"}, doc["gameId"])
    record_key = f"games/{doc['gameId']}/assets/{doc['id']}/original/recording.json"
    part_key = record_key.rsplit('/', 1)[0] + '/part-0000.wav'
    raw = json.dumps(doc).encode()
    audio = wav()
    with store.connect() as db:
        for key, data in ((record_key, raw), (part_key, audio)):
            db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, doc['gameId'], '{}', data, 'now'))
    identity = 'a' * 64
    job = {'id': identity, 'gameId': doc['gameId'], 'recordingId': doc['id'], 'sessionId': doc['sessionId'], 'sessionName': doc.get('sessionName'),
           'mode': mode, 'status': 'SUBMITTED', 'recording': {'key': record_key, 'sha256': worker.digest(raw), 'size': len(raw)},
           'inputs': [{'key': part_key, 'sha256': worker.digest(audio), 'size': len(audio), 'duration': .1}]}
    store.put('transcription', identity, job, doc['gameId'])
    return store, identity, job


class Provider:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail
        self.audio = SimpleNamespace(transcriptions=self)
    def create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise TimeoutError('private-body')
        assert kw['file'].read().startswith(b'RIFF')
        return SimpleNamespace(model_dump=lambda **kw: {'text': 'A real model response in this test.', 'usage': {'type': 'duration', 'seconds': .1}})


def test_final_pass_uses_original_wavs_and_publishes_transcript_with_response_evidence(tmp_path):
    store, identity, job = queued(tmp_path)
    original = store.object(job['inputs'][0]['key'])[1]
    client = Provider()
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), client)
    result = store.get('transcription', identity)
    assert result['status'] == 'DONE' and len(client.calls) == 1
    assert client.calls[0]['extra_body'] == {'languages': ['en']}
    metadata, raw = store.object(result['transcriptKey'])
    transcript = json.loads(raw)
    assert transcript['segments'][0]['playerId'] is None
    assert transcript['requestedModel'] == 'gpt-transcribe'
    assert transcript['timestampPrecision'] == 'window-boundary'
    assert transcript['recordedAt'] == '2026-01-01T00:00:00Z'
    assert result['summaryJobId']
    assert store.get('transcript-summary', result['summaryJobId'])['recordedAt'] == transcript['recordedAt']
    assert result['responseKey'] in metadata['sourceKeys']
    assert store.object(job['inputs'][0]['key'])[1] == original
    assert metadata['extra']['generation']['cost']['status'] == 'unknown'
    assert not worker.process(store, identity, tmp_path / 'work', client)
    assert len(client.calls) == 1


def test_live_transcription_is_separate_from_final(tmp_path):
    store, identity, job = queued(tmp_path, 'live')
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), Provider())
    result = store.get('transcription', identity)
    metadata, raw = store.object(result['transcriptKey'])
    assert metadata['kind'] == 'live-transcript'
    assert json.loads(raw)['mode'] == 'live'


def test_unknown_and_interrupted_requests_are_never_automatically_repeated(tmp_path):
    store, identity, job = queued(tmp_path)
    client = Provider(fail=True)
    assert not worker.process(store, identity, worker.private_root(tmp_path / 'work'), client)
    assert store.get('transcription', identity)['status'] == 'UNKNOWN'
    assert 'private-body' not in store.get('transcription', identity)['message']
    assert not worker.process(store, identity, tmp_path / 'work', client)
    assert len(client.calls) == 1
    store.put('transcription', identity, {**job, 'status': 'RUNNING'}, job['gameId'])
    assert not worker.process(store, identity, tmp_path / 'work', client)
    assert len(client.calls) == 1


def test_modified_recording_sources_fail_before_spending(tmp_path):
    store, identity, job = queued(tmp_path)
    with store.connect() as db:
        db.execute('UPDATE objects SET data=? WHERE key=?', (b'bad', job['inputs'][0]['key']))
    client = Provider()
    assert not worker.process(store, identity, worker.private_root(tmp_path / 'work'), client)
    assert store.get('transcription', identity)['status'] == 'FAILED'
    assert not client.calls


def test_summary_queue_failure_does_not_undo_successful_transcription(tmp_path, monkeypatch):
    store, identity, job = queued(tmp_path)
    def unavailable(body):
        raise RuntimeError('Summary queue unavailable')
    monkeypatch.setattr(store, 'submit_transcript_summary', unavailable)
    client = Provider()
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), client)
    result = store.get('transcription', identity)
    assert result['status'] == 'DONE'
    assert result['summaryMessage'] == 'Summary queue unavailable'
    assert store.object(result['transcriptKey'])[1]
    assert len(client.calls) == 1


def test_cancelled_transcription_does_not_publish_or_replace_cancellation(tmp_path):
    store, identity, job = queued(tmp_path)
    class Cancelling(Provider):
        def create(self, **kw):
            response = super().create(**kw)
            current = store.get('transcription', identity)
            current['status'] = 'CANCELLED'
            store.put('transcription', identity, current, job['gameId'])
            return response
    client = Cancelling()
    assert not worker.process(store, identity, worker.private_root(tmp_path / 'work'), client)
    assert store.get('transcription', identity)['status'] == 'CANCELLED'
    assert not [item for item in store.objects(job['gameId']) if item['kind'] == 'raw-transcript']
    assert len(client.calls) == 1
