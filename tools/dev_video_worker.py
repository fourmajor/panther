# ruff: noqa: E402 -- repository modules require the explicit script import path below.
"""Explicit scene video requests through fal, with durable queue identity and real output."""
from __future__ import annotations
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'infra/lambda/media-api'))
sys.path.insert(0, str(ROOT / 'tools'))
import asset_metadata
import storage_layout
import requests
from dotenv import load_dotenv
from dev_server import Store
from dev_playback_worker import private_root, retain
from dev_editorial_worker import now
from dev_prompt_processor import video_prompt
from panther_journal import video as v
from panther_journal.generation_metadata import fal as fal_metadata


class Fal(v.Fal):
    def __init__(self, env_file=None):
        path = Path(env_file or ROOT / '.env').expanduser()
        if path.exists():
            if path.is_symlink() or path.stat().st_mode & 0o077:
                raise ValueError('The environment file must be private (chmod 600)')
            load_dotenv(path, override=False)
        key = os.environ.get('FAL_API_KEY', '').strip()
        if not key:
            raise ValueError('Add FAL_API_KEY to .env and restart the video worker')
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers['Authorization'] = 'Key ' + key


def model_for(job):
    kind = job.get('sceneType', job.get('type', 'general'))
    if kind == 'map':
        if not job.get('mapPin'):
            raise ValueError('Choose a map asset for this scene')
        return 'veo-3.1-fast-image-silent'
    return 'kling-3-pro' if kind == 'action' else 'h3-max' if kind == 'dialogue' else 'veo-3.1-fast'


def verified(store, ref, game):
    _, raw = store.object(ref['key'])
    with store.connect() as db:
        row = db.execute('SELECT game FROM objects WHERE key=?', (ref['key'],)).fetchone()
    if row != (game,) or not ref['key'].startswith(f'games/{game}/assets/') or base64.b64encode(hashlib.sha256(raw).digest()).decode() != ref['sha256'] or len(raw) != ref['size']:
        raise ValueError('Pinned scene input changed or belongs to another game')
    return raw


def probe(file):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(file)], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError('Generated video failed media verification')
    document = json.loads(result.stdout)
    videos = [s for s in document['streams'] if s.get('codec_type') == 'video']
    duration = float(document['format']['duration'])
    if len(videos) != 1 or not 0 < duration < 120 or videos[0].get('width', 0) < 100 or videos[0].get('height', 0) < 100:
        raise ValueError('Generated video has invalid duration or dimensions')
    return document


def download(url, target):
    url = v.media_url(url)
    with requests.Session() as session:
        session.trust_env = False
        with session.get(url, stream=True, timeout=(15, 120), allow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError('Generated video download is unavailable; the queue request is retained')
            data = bytearray()
            for chunk in response.iter_content(1024 * 1024):
                data.extend(chunk)
                if len(data) > 200 * 1024**2:
                    raise ValueError('Generated video exceeds supported size')
    retain(target, bytes(data))


def process(store, identity, root, fal, *, downloader=download, media_probe=probe, prompt_client=None):
    job = store.get('scene-render', identity)
    if not job or job.get('status') not in {'QUEUED', 'SUBMITTED', 'RUNNING', 'COMPOSING', 'IN_QUEUE', 'IN_PROGRESS'}:
        return False
    try:
        if not re.fullmatch(r'[a-f0-9]{64}', identity):
            raise ValueError('Invalid video job identity')
        ref = job['sceneRef']
        scene = store.get('scene-history', job['gameId'] + ':' + ref['episodeId'] + ':' + ref['sceneId'] + ':' + ref['revision'])
        if not scene or scene['record']['revision'] != ref['revision']:
            raise ValueError('Pinned scene revision was not found')
        model = job.get('model') or model_for(job)
        if model not in {'veo-3.1-fast', 'veo-3.1-fast-image-silent', 'h3-max', 'kling-3-pro'}:
            raise ValueError('Unsupported scene video model')
        endpoint = v.PROFILES[model]['endpoint']
        if not isinstance(job.get('prompt'), str) or not 1 <= len(job['prompt']) <= 4000:
            raise ValueError('Provide a scene prompt under 4000 characters')
        inputs = list(job.get('inputRefs', []))
        if job.get('mapPin'):
            inputs.append(job['mapPin'])
        for source in inputs:
            verified(store, source, job['gameId'])
        folder = root / identity
        if folder.is_symlink():
            raise ValueError('Symlinked video checkpoint rejected')
        folder.mkdir(mode=0o700, exist_ok=True)
        if not job.get('preparedPrompt') and (job.get('transcriptKeys') or job.get('contextKeys') or job.get('characterContext')):
            if job.get('status') == 'COMPOSING':
                raise RuntimeError('The previous prompt-composition outcome is unknown. Review retained responses before retrying; no paid request was repeated.')
            job.update(status='COMPOSING', message=None)
            store.put('scene-render', identity, job, job['gameId'])
            composition, evidence = video_prompt(store, job, folder, verified, prompt_client)
            job.update(preparedPrompt=composition['renderPrompt'], promptComposition={**composition, 'generation': evidence}, status='QUEUED')
            store.put('scene-render', identity, job, job['gameId'])
        if not job.get('requestId'):
            if job.get('dispatchStarted'):
                raise RuntimeError('The previous fal submission outcome is unknown. Check provider request history; no video request was repeated.')
            prompt = job.get('preparedPrompt') or job['prompt']
            shot = {'model': model, 'prompt': prompt}
            body = v.payload(shot)
            if job.get('mapPin'):
                pin = job['mapPin']
                image = verified(store, pin, job['gameId'])
                body[v.PROFILES[model]['imageField']] = 'data:' + pin['contentType'] + ';base64,' + base64.b64encode(image).decode()
                body['prompt'] = 'Treat the input image as a map. Preserve its geography, labels, framing and visual style. Animate a red dot at the initial location and red footprints following the travelers along a clear route to the destination. ' + prompt
            retain(folder / 'request.json', json.dumps({'endpoint': endpoint, 'payload': body, 'sceneRef': ref}, ensure_ascii=False).encode())
            job.update(status='RUNNING', dispatchStarted=now(), model=model, endpoint=endpoint, message=None)
            store.put('scene-render', identity, job, job['gameId'])
            try:
                result = fal.request('POST', v.QUEUE + '/' + endpoint, json=body,
                                     headers={'X-Fal-No-Retry': '1', 'X-Fal-Disable-Fallback': 'true', 'X-Fal-Request-Timeout': '300', 'X-Fal-Store-IO': '0'})
            except Exception as exc:
                raise RuntimeError('fal could not confirm the video submission. Check credentials, connectivity and provider request history; no automatic paid retry.') from exc
            retain(folder / 'submission.json', json.dumps(result).encode())
            rid = result.get('request_id')
            if not isinstance(rid, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', rid):
                raise RuntimeError('fal returned no usable request identity. No automatic paid retry.')
            # Persist request ID before validating remaining response fields.
            job.update(requestId=rid, status='SUBMITTED')
            store.put('scene-render', identity, job, job['gameId'])
            job['urls'] = {kind: v.queue_url(result[kind + '_url'], rid, endpoint, kind) for kind in ('status', 'response')}
            store.put('scene-render', identity, job, job['gameId'])
        if not job.get('urls'):
            raise RuntimeError('fal queue URLs are missing; the request identity is retained. Inspect the provider result before recovering.')
        rid = job['requestId']
        result = fal.request('GET', v.queue_url(job['urls']['status'], rid, endpoint, 'status'))
        if result.get('request_id') not in {None, rid}:
            raise ValueError('fal queue identity mismatch')
        status = result.get('status')
        if status in {'IN_QUEUE', 'IN_PROGRESS'}:
            job.update(status=status, queuePosition=result.get('queue_position'), updatedAt=time.time(), message=None)
            store.put('scene-render', identity, job, job['gameId'])
            return False
        if status != 'COMPLETED':
            raise ValueError('fal returned an unknown queue state')
        output = fal.request('GET', v.queue_url(job['urls']['response'], rid, endpoint, 'response'), completed_result=True)
        retain(folder / 'result.json', json.dumps(output).encode())
        target = folder / 'video.mp4'
        if not target.exists():
            downloader(output['video']['url'], target)
        quality = media_probe(target)
        raw = target.read_bytes()
        asset = 'video-' + identity[:32]
        key = f"games/{job['gameId']}/assets/{asset}/original/video.mp4"
        response_key = f"games/{job['gameId']}/assets/{asset}/original/provider-response.json"
        lineage = list(dict.fromkeys([r['key'] for r in inputs] + job.get('sourceKeys', [])))
        generation = fal_metadata(endpoint, rid)
        metadata = asset_metadata.defaults('video', {'kind': 'video', 'title': scene['record']['name'], 'contentType': 'video/mp4', 'sourceKeys': lineage + [response_key],
            'characterIds': job.get('characterIds', []), 'extra': {'generation': generation, 'requestId': rid, 'sceneRef': ref, 'episodeId': ref['episodeId'], 'sceneId': ref['sceneId'],
            'relationshipRole': 'finished', 'sha256': base64.b64encode(hashlib.sha256(raw).digest()).decode(), 'mediaProbe': quality}}, target.name, 'video/mp4', key)
        response_bytes = json.dumps({'provider': 'fal', 'endpoint': endpoint, 'requestId': rid, 'result': output, 'sceneRef': ref, 'sourceKeys': lineage, 'promptComposition': job.get('promptComposition')}, ensure_ascii=False).encode()
        response_metadata = asset_metadata.defaults('generation-response', {'kind': 'generation-response', 'title': scene['record']['name'], 'contentType': 'application/json', 'sourceKeys': lineage,
            'extra': {'generation': generation, 'relationshipRole': 'intermediate', 'sha256': base64.b64encode(hashlib.sha256(response_bytes).digest()).decode()}}, 'provider-response.json', 'application/json', response_key)
        storage_layout.location(key, 'video', metadata)
        storage_layout.location(response_key, 'generation-response', response_metadata)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for out_key, data, meta in ((response_key, response_bytes, response_metadata), (key, raw, metadata)):
                existing = db.execute('SELECT data FROM objects WHERE key=?', (out_key,)).fetchone()
                if existing and existing[0] != data:
                    raise ValueError('Video output collision; refusing overwrite')
                if not existing:
                    db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (out_key, job['gameId'], json.dumps(meta), data, now()))
            job.update(status='DONE', outputKey=key, responseKey=response_key, completedAt=time.time(), message=None)
            db.execute("UPDATE records SET payload=? WHERE kind='scene-render' AND id=?", (json.dumps(job), identity))
        return True
    except Exception as exc:
        # A failed GET/download can resume the known queue request without another POST.
        if job.get('requestId') and job.get('urls') and not isinstance(exc, (ValueError, v.TerminalModelRejection)):
            job.update(status='SUBMITTED', message='Video status or delivery is unavailable. The known request will be checked again; no new generation was submitted.', updatedAt=time.time())
        else:
            job.update(status='UNKNOWN' if isinstance(exc, RuntimeError) else 'FAILED', message=str(exc)[:800], updatedAt=time.time())
        store.put('scene-render', identity, job, job['gameId'])
        return False


def run(database, work_dir, *, env_file=None, once=False, fal=None):
    os.umask(0o077)
    store, root = Store(database), private_root(work_dir)
    try:
        fal = fal or Fal(env_file)
    except Exception as exc:
        store.put('service', 'video', {'status': 'BLOCKED', 'updatedAt': time.time(), 'message': str(exc)})
        raise
    with store.path.with_name(store.path.name + '.video.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stop = threading.Event()
        def pulse():
            while not stop.is_set():
                store.put('service', 'video', {'status': 'RUNNING', 'updatedAt': time.time()})
                stop.wait(10)
        thread = threading.Thread(target=pulse, daemon=True)
        thread.start()
        try:
            while True:
                for job in reversed(store.list('scene-render')):
                    process(store, job['id'], root, fal)
                if once:
                    break
                stop.wait(5)
        finally:
            stop.set()
            thread.join()
            store.put('service', 'video', {'status': 'STOPPED', 'updatedAt': time.time()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path.home() / '.local/state/panther/development.sqlite')
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    run(args.database, args.work_dir, env_file=args.env_file, once=args.once)
