"""Assemble immutable local scene outputs into real continuous episode videos."""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools'), str(ROOT / 'infra/lambda/media-api')]
from dev_server import Store  # noqa: E402 — local application module paths are configured above
from dev_playback_worker import private_root, retain  # noqa: E402 — local application module paths are configured above
from panther_journal import episode_rendering, generation_metadata  # noqa: E402 — local application module paths are configured above
import asset_metadata  # noqa: E402 — local application module paths are configured above
import storage_layout  # noqa: E402 — local application module paths are configured above


def process(store, job, root):
    identity, game = job['jobId'], job['gameId']
    folder = root / identity / uuid.uuid4().hex
    folder.mkdir(parents=True, mode=0o700)
    job.update(status='RUNNING', updatedAt=time.time(), message=None)
    store.put('episode-render', identity, job, game)
    try:
        manifest = job['composition']
        paths = []
        for index, scene in enumerate(manifest['scenes']):
            _, raw = store.object(scene['assetKey'])
            if len(raw) != scene['size'] or hashlib.sha256(raw).hexdigest() != scene['sha256']:
                raise ValueError('A selected scene changed. Select its video again before assembling.')
            file = folder / ('input-' + str(index) + Path(scene['assetKey']).suffix)
            retain(file, raw)
            paths.append(file)
        result = episode_rendering.assemble(manifest, paths, folder)
        outputs = []
        for file, kind, mime in [(folder / result['output'], 'episode-video', 'video/mp4')]:
            key = f"games/{game}/assets/episode-{identity[:32]}-{folder.name[:12]}/original/{file.name}"
            raw = file.read_bytes()
            meta = asset_metadata.defaults(kind, {'title': manifest['episode']['name'], 'kind': kind, 'contentType': mime, 'sourceKeys': manifest['sourceKeys'], 'extra': {'episodeId': job['episodeId'], 'compositionHash': manifest['compositionHash'], 'relationshipRole': 'finished', 'generation': generation_metadata.local('FFmpeg'), 'sha256': base64.b64encode(hashlib.sha256(raw).digest()).decode(), 'assembly': result}}, file.name, mime, key)
            storage_layout.location(key, kind, meta)
            outputs.append((key, raw, meta))
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for scene, file in zip(manifest['scenes'], paths, strict=True):
                row = db.execute('SELECT game,data FROM objects WHERE key=?', (scene['assetKey'],)).fetchone()
                if row != (game, file.read_bytes()):
                    raise ValueError('A selected source changed during assembly.')
            for key, raw, meta in outputs:
                db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, game, json.dumps(meta), raw, datetime.now(timezone.utc).isoformat()))
            job.update(status='DONE', outputKey=outputs[0][0], updatedAt=time.time(), message=None)
            db.execute("UPDATE records SET payload=? WHERE kind='episode-render' AND id=?", (json.dumps(job), identity))
    except Exception as exc:
        job.update(status='FAILED', message=str(exc)[:600], updatedAt=time.time())
        store.put('episode-render', identity, job, game)
        return False
    return True


def run(database, work_dir, once=False):
    os.umask(0o077)
    store, root = Store(database), private_root(work_dir)
    with store.path.with_name(store.path.name + '.episode.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            store.put('service', 'episodes', {'status': 'RUNNING', 'updatedAt': time.time()})
            for job in reversed(store.list('episode-render')):
                if job['status'] in {'QUEUED', 'RUNNING'}:
                    process(store, job, root)
            if once:
                break
            time.sleep(3)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path.home() / '.local/state/panther/development.sqlite')
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    run(args.database, args.work_dir, args.once)
