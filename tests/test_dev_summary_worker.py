"""Local summaries preserve pinned speech and never guess participant identity."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from test_editorial import raw

spec = importlib.util.spec_from_file_location('dev_summary_worker', Path(__file__).parents[1] / 'tools/dev_summary_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def queued(tmp_path):
    store = worker.Store(tmp_path / 'private.sqlite')
    doc = raw()
    store.put('game', doc['gameId'], {'id': doc['gameId'], 'name': 'Fictional game', 'description': ''})
    key = 'games/test-game/assets/transcript-example/original/raw.json'
    source = json.dumps(doc).encode()
    with store.connect() as db:
        db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, doc['gameId'], json.dumps({'kind': 'raw-transcript'}), source, 'now'))
    job = store.submit_transcript_summary({'gameId': doc['gameId'], 'key': key})
    job.update(status='QUEUED', message=None)
    store.put('transcript-summary', job['jobId'], job, doc['gameId'])
    return store, job, source


class Responses:
    def __init__(self, fail=False, segment=0):
        self.calls = []
        self.fail = fail
        self.segment = segment
    def create(self, **request):
        self.calls.append(request)
        if self.fail:
            raise TimeoutError('private-body')
        summary = {'title': 'Ask the captain', 'summary': 'The speaker asks about Captain Kade and says they have 13 left.', 'segmentIndexes': [self.segment], 'uncertainties': []}
        return SimpleNamespace(id='resp-example', output_text=json.dumps(summary), model_dump=lambda **kw: {'id': 'resp-example', 'status': 'completed', 'model': 'test-model', 'usage': {'input_tokens': 10}})


def test_summary_validates_speech_evidence_and_preserves_original(tmp_path):
    store, job, original = queued(tmp_path)
    response = Responses()
    assert worker.process(store, job['jobId'], worker.private_root(tmp_path / 'work'), SimpleNamespace(responses=response))
    ready = store.transcript_summary_view(job['gameId'], job['key'])
    assert ready['status'] == 'READY'
    assert ready['summary']['segmentIndexes'] == [0]
    assert ready['participants'] == [{'id': 'person'}]
    assert store.object(job['key'])[1] == original
    metadata, document = store.object(ready['assetKey'])
    assert metadata['sourceKeys'] == [job['key']]
    assert json.loads(document)['generation']['model'] == 'test-model'
    assert not worker.process(store, job['jobId'], tmp_path / 'work', SimpleNamespace(responses=response))
    assert len(response.calls) == 1


def test_invalid_citation_keeps_previous_evidence_and_no_summary(tmp_path):
    store, job, original = queued(tmp_path)
    assert not worker.process(store, job['jobId'], worker.private_root(tmp_path / 'work'), SimpleNamespace(responses=Responses(segment=99)))
    assert store.get('transcript-summary', job['jobId'])['status'] == 'ATTENTION'
    assert not store.get('transcript-summary', job['jobId'])['assetKey']
    assert store.object(job['key'])[1] == original


def test_timeout_never_repeats_paid_summary(tmp_path):
    store, job, original = queued(tmp_path)
    responses = Responses(fail=True)
    client = SimpleNamespace(responses=responses)
    assert not worker.process(store, job['jobId'], worker.private_root(tmp_path / 'work'), client)
    assert not worker.process(store, job['jobId'], tmp_path / 'work', client)
    assert len(responses.calls) == 1
    assert 'private-body' not in store.get('transcript-summary', job['jobId'])['message']


def test_summary_cancellation_during_provider_request_is_not_overwritten(tmp_path):
    store, job, original = queued(tmp_path)
    class Cancelling(Responses):
        def create(self, **request):
            response = super().create(**request)
            current = store.get('transcript-summary', job['jobId'])
            current['status'] = 'CANCELLED'
            store.put('transcript-summary', job['jobId'], current, job['gameId'])
            return response
    responses = Cancelling()
    assert not worker.process(store, job['jobId'], worker.private_root(tmp_path / 'work'), SimpleNamespace(responses=responses))
    assert store.get('transcript-summary', job['jobId'])['status'] == 'CANCELLED'
    assert len(responses.calls) == 1
    assert not [item for item in store.objects(job['gameId']) if item['kind'] == 'transcript-summary']
