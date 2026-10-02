"""Local playback uses actual verified browser WAVs and immutable SQLite outputs."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from test_browser_recording import manifest, wav

spec = importlib.util.spec_from_file_location("dev_playback_worker", Path(__file__).parents[1] / "tools/dev_playback_worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def queued(tmp_path):
    store = worker.Store(tmp_path / "development.sqlite")
    doc = manifest()
    key = f"games/{doc['gameId']}/assets/{doc['id']}/original/recording.json"
    raw = json.dumps(doc).encode()
    identity = hashlib.sha256(raw).hexdigest()
    with store.connect() as db:
        for asset_key, data in [(key, raw), (key.rsplit('/', 1)[0] + '/part-0000.wav', wav())]:
            db.execute("INSERT INTO objects VALUES (?,?,?,?,?)", (asset_key, doc['gameId'], '{}', data, 'now'))
    job = {"jobId": identity, "gameId": doc['gameId'], "chunkSetId": doc['id'], "recordingKey": key, "sourceManifestSha256": identity, "workflowVersion": 2, "setStatus": "COMPLETE", "status": "WAITING"}
    store.put("playback", identity, job, doc['gameId'])
    return store, identity, key, doc


@pytest.mark.skipif(not all(shutil.which(tool) for tool in ('ffmpeg', 'ffprobe')), reason="Playback tools unavailable")
def test_actual_playback_is_published_atomically_and_sources_unchanged(tmp_path, monkeypatch):
    store, identity, key, doc = queued(tmp_path)
    originals = {a['key']: store.object(a['key'])[1] for a in store.objects(doc['gameId'])}
    worker.run(store.path, tmp_path / 'private-work', once=True)
    job = store.get('playback', identity)
    assert job['status'] == 'DONE'
    assert store.get('service', 'playback')['status'] == 'STOPPED'
    meta, audio = store.object(job['output']['audioKey'])
    assert len(audio) > 100 and meta['contentType'] == 'audio/mpeg'
    assert meta['sourceKeys'] == [job['output']['manifestKey']]
    assert meta['extra']['captureWarnings'] == doc['captureWarnings']
    assert meta['extra']['generation']['method'] == 'procedural'
    _, manifest_raw = store.object(job['output']['manifestKey'])
    output = json.loads(manifest_raw)
    assert output['inputSamples'] == 3200
    assert output['sourceKeys'] == list(originals)
    assert output['audioSha256'] == hashlib.sha256(audio).hexdigest()
    for original_key, raw in originals.items():
        assert store.object(original_key)[1] == raw
    # Simulate a process dying after publication; resume uses the verified checkpoint.
    store.put('playback', identity, {**job, 'status': 'PROCESSING'}, doc['gameId'])
    monkeypatch.setattr(worker.recording_playback.subprocess, 'Popen', lambda *a, **k: pytest.fail('checkpoint must avoid re-encoding'))
    worker.run(store.path, tmp_path / 'private-work', once=True)
    assert store.get('playback', identity)['status'] == 'DONE'
    assert len(store.objects(doc['gameId'])) == 4


def test_changed_or_uncommitted_sources_fail_without_outputs(tmp_path):
    store, identity, key, doc = queued(tmp_path)
    with store.connect() as db:
        db.execute('UPDATE objects SET data=? WHERE key=?', (b'corrupt', key.rsplit('/', 1)[0] + '/part-0000.wav'))
    worker.run(store.path, tmp_path / 'private-work', once=True)
    assert store.get('playback', identity)['status'] == 'FAILED'
    assert 'checksum' in store.get('playback', identity)['message']
    assert len(store.objects(doc['gameId'])) == 2
    store.put('playback', identity, {**store.get('playback', identity), 'status': 'WAITING', 'setStatus': 'OPEN'}, doc['gameId'])
    worker.run(store.path, tmp_path / 'private-work', once=True)
    assert 'explicitly completed' in store.get('playback', identity)['message']


def test_worker_rejects_repository_work_directory():
    with pytest.raises(ValueError, match='outside Git'):
        worker.private_root(worker.ROOT / 'playback-work')


@pytest.mark.skipif(not all(shutil.which(tool) for tool in ('ffmpeg', 'ffprobe')), reason="Playback tools unavailable")
def test_existing_output_collision_is_retained_not_overwritten(tmp_path):
    store, identity, _, doc = queued(tmp_path)
    worker.run(store.path, tmp_path / 'private-work', once=True)
    job = store.get('playback', identity)
    key = job['output']['audioKey']
    with store.connect() as db:
        db.execute('UPDATE objects SET data=? WHERE key=?', (b'existing conflicting bytes', key))
    store.put('playback', identity, {**job, 'status': 'PROCESSING'}, doc['gameId'])
    worker.run(store.path, tmp_path / 'private-work', once=True)
    assert store.get('playback', identity)['status'] == 'FAILED'
    assert 'refusing overwrite' in store.get('playback', identity)['message']
    assert store.object(key)[1] == b'existing conflicting bytes'
