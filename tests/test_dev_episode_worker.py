"""Local episode assembly uses actual selected bytes and preserves ordered lineage."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

spec = importlib.util.spec_from_file_location('dev_episode_worker', Path(__file__).parents[1] / 'tools/dev_episode_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def queued(tmp_path):
    store = worker.Store(tmp_path / 'private.sqlite')
    store.put('game', 'fictional', {'id': 'fictional', 'name': 'Imaginary game'})
    scenes = []
    for index, color in enumerate(('red', 'blue')):
        file = tmp_path / f'{index}.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'color=c={color}:s=160x90:d=0.4:r=24', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(file)], check=True)
        raw = file.read_bytes()
        key = f'games/fictional/assets/scene-{index}/original/video.mp4'
        with store.connect() as db:
            db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, 'fictional', '{}', raw, 'now'))
        scenes.append({'assetKey': key, 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw), 'sceneRef': {'episodeId': 'journey', 'sceneId': f'scene-{index}', 'revision': 'fixed'}})
    composition = {'episode': {'id': 'journey', 'name': 'Journey'}, 'scenes': scenes, 'sourceKeys': [s['assetKey'] for s in scenes], 'compositionHash': 'fixed'}
    job = {'jobId': 'a' * 64, 'gameId': 'fictional', 'episodeId': 'journey', 'status': 'QUEUED', 'composition': composition}
    store.put('episode-render', job['jobId'], job, 'fictional')
    return store, job


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='Requires real FFmpeg tools')
def test_continuous_episode_has_actual_video_audio_and_ordered_inputs(tmp_path):
    store, job = queued(tmp_path)
    assert worker.process(store, job, worker.private_root(tmp_path / 'work'))
    result = store.get('episode-render', job['jobId'])
    assert result['status'] == 'DONE'
    meta, raw = store.object(result['outputKey'])
    output = tmp_path / 'episode.mp4'
    output.write_bytes(raw)
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(output)]))
    assert {stream['codec_type'] for stream in probe['streams']} == {'video', 'audio'}
    assert 0.7 < float(probe['format']['duration']) < 1.1
    assert meta['sourceKeys'] == job['composition']['sourceKeys']
    for seconds, channel in ((0.1, 0), (0.6, 2)):
        pixel = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', str(seconds), '-i', str(output), '-frames:v', '1', '-vf', 'scale=1:1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
        assert pixel[channel] > 100 and pixel[channel] > pixel[(channel + 1) % 3] * 2


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='Requires FFmpeg fixture')
def test_changed_immutable_scene_fails_without_publishing(tmp_path):
    store, job = queued(tmp_path)
    with store.connect() as db:
        db.execute('UPDATE objects SET data=? WHERE key=?', (b'changed', job['composition']['sourceKeys'][0]))
    assert not worker.process(store, job, worker.private_root(tmp_path / 'work'))
    result = store.get('episode-render', job['jobId'])
    assert result['status'] == 'FAILED' and 'changed' in result['message']
    assert 'outputKey' not in result
    assert len(store.objects('fictional')) == 2
