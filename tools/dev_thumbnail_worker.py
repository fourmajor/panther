"""Create immutable video preview images without provider calls or request-handler work."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from PIL import Image, ImageStat

from dev_server import Store
from dev_playback_worker import private_root, retain
import asset_metadata
import storage_layout
from panther_journal.generation_metadata import local


def process(store, key, root):
    metadata, raw = store.object(key)
    if not metadata.get('contentType', '').startswith('video/'):
        return False
    checksum = hashlib.sha256(raw).hexdigest()
    previous = store.get('video-thumbnail', key)
    if previous and previous.get('sourceSha256') == checksum and previous.get('status') in {'READY', 'FAILED'}:
        return previous.get('status') == 'READY'
    game = storage_layout.parts(key)['game']
    record = {'schemaVersion': 1, 'sourceKey': key, 'sourceSha256': checksum,
              'status': 'PROCESSING', 'updatedAt': time.time()}
    store.put('video-thumbnail', key, record, game)
    try:
        folder = root / hashlib.sha256(key.encode()).hexdigest() / checksum
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        source = folder / ('source' + Path(key).suffix)
        retain(source, raw)
        # Sampling starts at the beginning; a black opener does not become the poster.
        # Decode at most the first ten seconds, bounded to twenty modest JPEG frames.
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source),
                        '-t', '10', '-vf', 'fps=2,scale=640:-2', '-frames:v', '20',
                        '-q:v', '3', str(folder / 'frame-%03d.jpg')],
                       check=True, timeout=90, capture_output=True)
        frames = sorted(folder.glob('frame-*.jpg'))
        if not frames:
            raise ValueError('Video has no decodable frame')
        selected, timestamp, nonblank = frames[0], 0.0, False
        for index, frame in enumerate(frames):
            with Image.open(frame) as image:
                stats = ImageStat.Stat(image.convert('L'))
                # Black fades and nearly-white blank title cards are skipped. Actual
                # uniformly colored footage is still legitimate and gets a preview.
                if 8 < stats.mean[0] < 247 or stats.stddev[0] > 8:
                    selected, timestamp, nonblank = frame, (index + .5) / 2, True
                    break
        image_raw = selected.read_bytes()
        identity = hashlib.sha256((key + ':' + checksum).encode()).hexdigest()[:40]
        output_key = f'games/{game}/assets/video-thumbnail-{identity}/original/thumbnail.jpg'
        output_meta = asset_metadata.defaults('video-thumbnail', {
            'title': metadata.get('title') or Path(key).stem, 'kind': 'video-thumbnail',
            'contentType': 'image/jpeg', 'sourceKeys': [key],
            'characterIds': metadata.get('characterIds', []),
            'extra': {'relationshipRole': 'intermediate', 'generation': local('FFmpeg'),
                      'sha256': base64.b64encode(hashlib.sha256(image_raw).digest()).decode(),
                      'videoThumbnail': {'schemaVersion': 1, 'sourceSha256': checksum,
                                         'timestampSeconds': timestamp, 'nonblank': nonblank}},
        }, 'thumbnail.jpg', 'image/jpeg', output_key)
        storage_layout.location(output_key, 'video-thumbnail', output_meta)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT game,data FROM objects WHERE key=?', (key,)).fetchone()
            if existing != (game, raw):
                raise ValueError('Video changed during thumbnail extraction')
            saved = db.execute('SELECT game,data,metadata FROM objects WHERE key=?', (output_key,)).fetchone()
            if saved and (saved[:2] != (game, image_raw) or json.loads(saved[2]) != output_meta):
                raise ValueError('Existing thumbnail differs; refusing overwrite')
            if not saved:
                db.execute('INSERT INTO objects VALUES (?,?,?,?,?)',
                           (output_key, game, json.dumps(output_meta), image_raw,
                            datetime.now(timezone.utc).isoformat()))
            record.update(status='READY', thumbnailKey=output_key,
                          timestampSeconds=timestamp, nonblank=nonblank, updatedAt=time.time())
            db.execute("UPDATE records SET payload=? WHERE kind='video-thumbnail' AND id=?",
                       (json.dumps(record), key))
        return True
    except Exception as exc:
        record.update(status='FAILED', message=str(exc)[:500], updatedAt=time.time())
        store.put('video-thumbnail', key, record, game)
        return False


def run(database, work_dir, once=False):
    os.umask(0o077)
    store, root = Store(database), private_root(work_dir)
    with store.path.with_name(store.path.name + '.thumbnail.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            store.put('service', 'thumbnail', {'status': 'RUNNING', 'updatedAt': time.time()})
            with store.connect() as db:
                keys = db.execute("SELECT key FROM objects WHERE json_extract(metadata,'$.contentType') LIKE 'video/%' AND NOT EXISTS (SELECT 1 FROM records WHERE kind='asset-deletion' AND id=objects.key) AND NOT EXISTS (SELECT 1 FROM records WHERE kind='video-thumbnail' AND id=objects.key AND json_extract(payload,'$.status') IN ('READY','FAILED')) ORDER BY created LIMIT 25").fetchall()
            for (key,) in keys:
                process(store, key, root)
            if once and not keys:
                return
            if not once:
                time.sleep(3)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path.home() / '.local/state/panther/development.sqlite')
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    run(args.database, args.work_dir, args.once)
