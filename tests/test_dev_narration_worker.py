"""Narration publishes verified audio and never repeats an uncertain paid call."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('dev_narration_worker', Path(__file__).parents[1] / 'tools/dev_narration_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def queued(tmp_path):
    store = worker.Store(tmp_path / 'private.sqlite')
    identity = 'a' * 64
    store.put('narration', identity, {'id': identity, 'gameId': 'fictional', 'text': '[calm] An imaginary adventure begins.', 'voiceId': 'FictionalVoice123', 'status': 'QUEUED'}, 'fictional')
    return store, identity


class Client:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail
    def generate(self, voice, text):
        self.calls += 1
        if self.fail:
            raise TimeoutError('private-body')
        return b'example mp3 bytes', {'request-id': 'request-example', 'character-cost': '43'}


def test_actual_provider_audio_is_published_with_v3_identity_and_unknown_billing(tmp_path):
    store, identity = queued(tmp_path)
    client = Client()
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), client, media_probe=lambda file: {'duration': .2})
    job = store.get('narration', identity)
    assert job['status'] == 'DONE'
    metadata, audio = store.object(job['outputKey'])
    assert audio == b'example mp3 bytes'
    assert metadata['extra']['generation']['model'] == 'Eleven v3'
    assert metadata['extra']['generation']['cost']['status'] == 'unknown'
    assert metadata['extra']['generation']['evidence']['character-cost'] == '43'
    assert not worker.process(store, identity, tmp_path / 'work', client)
    assert client.calls == 1


def test_unknown_narration_request_is_never_automatically_repeated(tmp_path):
    store, identity = queued(tmp_path)
    client = Client(fail=True)
    assert not worker.process(store, identity, worker.private_root(tmp_path / 'work'), client)
    assert store.get('narration', identity)['status'] == 'UNKNOWN'
    assert not worker.process(store, identity, tmp_path / 'work', client)
    assert client.calls == 1
    assert 'private-body' not in store.get('narration', identity)['message']
    assert not store.objects('fictional')


def test_completed_provider_audio_recovers_after_interruption_without_paid_retry(tmp_path):
    store, identity = queued(tmp_path)
    client = Client()
    root = worker.private_root(tmp_path / 'work')
    class Interrupted(BaseException):
        pass
    def interrupted_probe(file):
        raise Interrupted()
    import pytest
    with pytest.raises(Interrupted):
        worker.process(store, identity, root, client, media_probe=interrupted_probe)
    assert store.get('narration', identity)['providerCompleted']
    assert worker.process(store, identity, root, client, media_probe=lambda file: {'duration': .2})
    assert store.get('narration', identity)['status'] == 'DONE'
    assert client.calls == 1


def test_concurrent_cancellation_is_not_overwritten_when_provider_returns(tmp_path):
    store, identity = queued(tmp_path)
    class Cancelling(Client):
        def generate(self, voice, text):
            result = super().generate(voice, text)
            job = store.get('narration', identity)
            job['status'] = 'CANCELLED'
            store.put('narration', identity, job, job['gameId'])
            return result
    # Checkpoint update currently precedes publish; cancellation must remain authoritative.
    client = Cancelling()
    assert not worker.process(store, identity, worker.private_root(tmp_path / 'work'), client, media_probe=lambda file: {'duration': .2})
    assert store.get('narration', identity)['status'] == 'CANCELLED'


def test_probe_rejects_nonfinite_or_wrong_format_audio(monkeypatch, tmp_path):
    import json
    import pytest
    from types import SimpleNamespace
    def result(duration='NaN', codec='mp3'):
        return SimpleNamespace(returncode=0, stdout=json.dumps({'format': {'duration': duration}, 'streams': [{'codec_type': 'audio', 'codec_name': codec, 'sample_rate': '44100', 'channels': 1}]}))
    monkeypatch.setattr(worker.subprocess, 'run', lambda *args, **kwargs: result())
    with pytest.raises(ValueError, match='playable'):
        worker.probe(tmp_path / 'audio.mp3')
    monkeypatch.setattr(worker.subprocess, 'run', lambda *args, **kwargs: result('2.0', 'aac'))
    with pytest.raises(ValueError, match='MP3'):
        worker.probe(tmp_path / 'audio.mp3')


def test_standalone_narration_preserves_spoken_words_and_generates_title(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    store = worker.Store(tmp_path / 'standalone.sqlite')
    identity = 'b' * 64
    spoken = 'The harbor wakes beneath a red sunrise.'
    store.put('asset-generation', identity, {'jobId': identity, 'gameId': 'fictional', 'type': 'narration',
              'mediaType': 'audio', 'model': 'eleven_v3', 'prompt': spoken, 'text': spoken,
              'voiceId': 'FictionalVoice123', 'direction': '', 'status': 'QUEUED', 'inputs': {}, 'inputRefs': [], 'sourceKeys': []}, 'fictional')
    def title(store, kind, identity, job, folder, client):
        job['name'] = 'Harbor Sunrise'
        store.put(kind, identity, job, job['gameId'])
    monkeypatch.setitem(sys.modules, 'dev_asset_title', SimpleNamespace(ensure_title=title))
    class Speech(Client):
        def generate(self, voice, text):
            assert text == spoken
            return super().generate(voice, text)
    client = Speech()
    assert worker.process(store, identity, worker.private_root(tmp_path / 'work'), client,
                          record_kind='asset-generation', media_probe=lambda file: {'duration': 3})
    job = store.get('asset-generation', identity)
    assert job['status'] == 'PUBLISHED'
    metadata, _ = store.object(job['assetKey'])
    assert metadata['title'] == 'Harbor Sunrise'
    assert metadata['extra']['generation']['model'] == 'Eleven v3'
    assert 'sceneRef' not in metadata['extra']
    assert not store.list('scene')
    assert not worker.process(store, identity, tmp_path / 'work', client, record_kind='asset-generation')
    assert client.calls == 1
