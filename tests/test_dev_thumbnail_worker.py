"""Actual frame extraction is repeatable, source-pinned and projected into libraries."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageStat
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
spec = importlib.util.spec_from_file_location('dev_thumbnail_worker', Path(__file__).parents[1] / 'tools/dev_thumbnail_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def put_video(store, raw, name='opening'):
    key = f'games/fictional/assets/{name}/original/video.mp4'
    metadata = {'contentType': 'video/mp4', 'kind': 'scene-video', 'title': 'Opening'}
    with store.connect() as db:
        db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, 'fictional', json.dumps(metadata), raw, 'now'))
    return key


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='Requires actual FFmpeg frame extraction')
def test_backfill_skips_black_opener_and_preserves_original_and_history(tmp_path):
    source = tmp_path / 'fixture.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=black:s=160x90:d=1:r=24',
                    '-f', 'lavfi', '-i', 'testsrc2=s=160x90:d=1:r=24', '-filter_complex',
                    '[0:v][1:v]concat=n=2:v=1:a=0[out]', '-map', '[out]', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', str(source)], check=True)
    store = worker.Store(tmp_path / 'db.sqlite')
    key = put_video(store, source.read_bytes())
    original = store.object(key)
    root = worker.private_root(tmp_path / 'frames')
    # A deterministic decode interrupted before publication resumes safely.
    import hashlib
    store.put('video-thumbnail', key, {'status': 'PROCESSING', 'sourceSha256': hashlib.sha256(original[1]).hexdigest()}, 'fictional')
    assert worker.process(store, key, root)
    thumbnail = store.get('video-thumbnail', key)
    assert thumbnail['status'] == 'READY' and thumbnail['nonblank']
    assert thumbnail['timestampSeconds'] >= 1
    metadata, raw = store.object(thumbnail['thumbnailKey'])
    assert metadata['sourceKeys'] == [key]
    assert metadata['extra']['relationshipRole'] == 'intermediate'
    output = tmp_path / 'thumbnail.jpg'
    output.write_bytes(raw)
    with Image.open(output) as image:
        assert image.width == 640 and ImageStat.Stat(image.convert('L')).stddev[0] > 8
    assert worker.process(store, key, root)
    assert store.object(key) == original
    assert len(store.objects('fictional')) == 2
    projected = next(asset for asset in store.objects('fictional') if asset['key'] == key)
    assert projected['thumbnailKey'] == thumbnail['thumbnailKey']
    store.put('scene', 'first', {'episodeId': 'journey', 'position': 0, 'selectedOutputKey': key}, 'fictional')
    store.put('scene', 'later', {'episodeId': 'journey', 'position': 1, 'selectedOutputKey': 'missing'}, 'fictional')
    episode = store.episode_thumbnails('fictional', [{'id': 'journey'}])[0]
    assert episode['thumbnailKey'] == thumbnail['thumbnailKey']
    assert not store.episode_thumbnails('another', [{'id': 'journey'}])[0].get('thumbnailKey')


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='Requires actual FFmpeg invalid-input check')
def test_invalid_video_failure_is_persisted_and_not_retried(tmp_path, monkeypatch):
    store = worker.Store(tmp_path / 'db.sqlite')
    key = put_video(store, b'invalid-video')
    root = worker.private_root(tmp_path / 'frames')
    assert not worker.process(store, key, root)
    assert store.get('video-thumbnail', key)['status'] == 'FAILED'
    assert len(store.objects('fictional')) == 1
    monkeypatch.setattr(worker.subprocess, 'run', lambda *_args, **_kwargs: pytest.fail('Failure must not loop'))
    assert not worker.process(store, key, root)
    assert store.objects('fictional')[0]['thumbnailStatus'] == 'FAILED'


def test_episode_poster_does_not_substitute_later_scene_while_first_is_pending(tmp_path):
    store = worker.Store(tmp_path / 'db.sqlite')
    first = put_video(store, b'first', 'first')
    later = put_video(store, b'later', 'later')
    store.put('scene', 'first', {'episodeId': 'journey', 'position': 0, 'selectedOutputKey': first}, 'fictional')
    store.put('scene', 'later', {'episodeId': 'journey', 'position': 1, 'selectedOutputKey': later}, 'fictional')
    store.put('video-thumbnail', later, {'status': 'READY', 'thumbnailKey': 'later.jpg'}, 'fictional')
    assert 'thumbnailKey' not in store.episode_thumbnails('fictional', [{'id': 'journey'}])[0]


def test_unselected_completed_scene_supplies_poster_without_selecting_take(tmp_path):
    store = worker.Store(tmp_path / 'db.sqlite')
    key = put_video(store, b'actual-output')
    scene = {'id': 'arrival', 'episodeId': 'journey', 'position': 0, 'selectedOutputKey': None}
    store.put('scene', 'fictional:journey:arrival', scene, 'fictional')
    store.put('scene-render', 'done', {'sceneRef': {'episodeId': 'journey', 'sceneId': 'arrival'},
                                      'status': 'DONE', 'outputKey': key, 'completedAt': 10}, 'fictional')
    store.put('video-thumbnail', key, {'status': 'READY', 'thumbnailKey': 'actual.jpg'}, 'fictional')
    assert store.episode_thumbnails('fictional', [{'id': 'journey'}])[0]['thumbnailKey'] == 'actual.jpg'
    assert store.get('scene', 'fictional:journey:arrival') == scene
    assert 'thumbnailKey' not in store.episode_thumbnails('another', [{'id': 'journey'}])[0]
    # Archived output and unrelated jobs never masquerade as an episode's poster.
    store.put('asset-deletion', key, {}, 'fictional')
    assert 'thumbnailKey' not in store.episode_thumbnails('fictional', [{'id': 'journey'}])[0]
