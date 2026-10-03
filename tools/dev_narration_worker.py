# ruff: noqa: E402 -- repository modules require the explicit script import path below.
"""Explicit ElevenLabs v3 narration requests for the private local backend."""
from __future__ import annotations
import argparse
import base64
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'infra/lambda/media-api'))
sys.path.insert(0, str(ROOT / 'tools'))
import asset_metadata
import storage_layout
import requests
from dotenv import load_dotenv
from dev_server import Store
from dev_playback_worker import private_root, retain
from dev_editorial_worker import now
from dev_video_worker import verified
from dev_prompt_processor import narration_direction


class ElevenLabs:
    def __init__(self, env_file=None):
        path = Path(env_file or ROOT / '.env').expanduser()
        if path.exists():
            if path.is_symlink() or path.stat().st_mode & 0o077:
                raise ValueError('The environment file must be private (chmod 600)')
            load_dotenv(path, override=False)
        key = os.environ.get('ELEVENLABS_API_KEY', '').strip()
        if not key:
            raise ValueError('Add ELEVENLABS_API_KEY to .env and restart the narration worker')
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers['xi-api-key'] = key

    def generate(self, voice, text):
        response = self.session.post('https://api.elevenlabs.io/v1/text-to-speech/' + voice,
            params={'output_format': 'mp3_44100_128'}, json={'text': text, 'model_id': 'eleven_v3', 'voice_settings': {'stability': .5}},
            timeout=(15, 180), allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError(f'ElevenLabs returned HTTP {response.status_code}; check the API key, selected voice and project access. No automatic paid retry.')
        if len(response.content) > 100 * 1024**2:
            raise RuntimeError('Narration response exceeds supported size; inspect the retained provider request before retrying')
        return response.content, {key: response.headers[key] for key in ('request-id', 'character-cost') if key in response.headers}


def probe(file):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(file)], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError('Narration output failed audio verification')
    data = json.loads(result.stdout)
    duration = float(data.get('format', {}).get('duration', 0))
    audio = [stream for stream in data.get('streams', []) if stream.get('codec_type') == 'audio']
    if not math.isfinite(duration) or not 0 < duration <= 3600 or not audio:
        raise ValueError('Narration contains no playable audio')
    if any(stream.get('codec_name') != 'mp3' or int(stream.get('sample_rate', 0)) != 44100 or int(stream.get('channels', 0)) not in {1, 2} for stream in audio):
        raise ValueError('Narration output does not match the requested MP3 format')
    return data


def checkpoint(store, identity, job, **changes):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT payload FROM records WHERE kind='narration' AND id=?", (identity,)).fetchone()
        if not row or json.loads(row[0]) != job:
            raise ValueError('Narration request changed while processing; output remains retained')
        job.update(changes)
        db.execute("UPDATE records SET payload=? WHERE kind='narration' AND id=?", (json.dumps(job), identity))


def process(store, identity, root, client, *, media_probe=probe, direction_client=None):
    job = store.get('narration', identity)
    if not job or job.get('status') not in {'QUEUED', 'SUBMITTED', 'RUNNING'}:
        return False
    try:
        if not re.fullmatch(r'[a-f0-9]{64}', identity) or not isinstance(job.get('voiceId'), str) or not re.fullmatch(r'[a-zA-Z0-9]{10,64}', job['voiceId']):
            raise ValueError('Choose a valid narration request and stock voice')
        if not isinstance(job.get('text'), str) or not 1 <= len(job['text']) <= 5000:
            raise ValueError('Provide narration text under 5000 characters')
        recovered = bool(job.get('providerCompleted'))
        if (job.get('status') == 'RUNNING' or job.get('dispatchStarted')) and not recovered:
            raise RuntimeError('The previous narration request outcome is unknown. Review provider history before explicitly retrying; no paid request was repeated.')
        for ref in job.get('inputRefs', []):
            verified(store, ref, job['gameId'])
        folder = root / identity
        if folder.is_symlink():
            raise ValueError('Symlinked narration checkpoint rejected')
        folder.mkdir(mode=0o700, exist_ok=True)
        if recovered:
            request = json.loads((folder / 'request.json').read_text())
            audio = (folder / 'narration.mp3').read_bytes()
            evidence = json.loads((folder / 'response.json').read_text())
            if request.get('originalText') != job['text'] or request.get('voiceId') != job['voiceId'] or request.get('direction', '') != job.get('direction', '') or request.get('sourceKeys', []) != job.get('sourceKeys', []) or hashlib.sha256(audio).hexdigest() != job.get('providerAudioSha256'):
                raise ValueError('Retained narration differs from its immutable request; refusing recovery')
        else:
            checkpoint(store, identity, job, status='RUNNING', dispatchStarted=now(), message=None)
            prepared = job['text']
            performance = None
            if job.get('direction', '').strip():
                prepared, performance = narration_direction(job['text'], job['direction'], folder, direction_client)
            request = {'model': 'eleven_v3', 'voiceId': job['voiceId'], 'text': prepared, 'originalText': job['text'], 'direction': job.get('direction', ''), 'performance': performance, 'sourceKeys': job.get('sourceKeys', [])}
            retain(folder / 'request.json', json.dumps(request, ensure_ascii=False).encode())
            try:
                audio, evidence = client.generate(job['voiceId'], prepared)
            except Exception as exc:
                message = str(exc) if isinstance(exc, RuntimeError) else 'ElevenLabs narration failed or its outcome is unknown. Check connectivity and provider request history; no automatic paid retry.'
                raise RuntimeError(message) from exc
            retain(folder / 'narration.mp3', audio)
            retain(folder / 'response.json', json.dumps(evidence).encode())
            checkpoint(store, identity, job, providerCompleted=now(), providerAudioSha256=hashlib.sha256(audio).hexdigest())
        quality = media_probe(folder / 'narration.mp3')
        key = f"games/{job['gameId']}/assets/narration-{identity[:32]}/original/narration.mp3"
        response_key = key.rsplit('/', 1)[0] + '/provider-response.json'
        inputs = list(dict.fromkeys(job.get('sourceKeys', []) + [ref['key'] for ref in job.get('inputRefs', [])]))
        generation = {'schemaVersion': 1, 'method': 'ai', 'provider': 'ElevenLabs', 'model': 'Eleven v3', 'inference': 'remote', 'execution': 'local',
            'tool': 'ElevenLabs text-to-speech API', 'cost': {'status': 'unknown'}, 'evidence': evidence}
        metadata = asset_metadata.defaults('narration', {'kind': 'narration', 'title': job.get('title') or 'Narration', 'sourceKeys': inputs + [response_key], 'contentType': 'audio/mpeg',
            'extra': {'generation': generation, 'voiceId': job['voiceId'], 'relationshipRole': 'finished', 'sha256': base64.b64encode(hashlib.sha256(audio).digest()).decode(), 'mediaProbe': quality}}, 'narration.mp3', 'audio/mpeg', key)
        response_document = {**request, 'response': evidence, 'generation': generation}
        response_bytes = json.dumps(response_document, ensure_ascii=False).encode()
        response_meta = asset_metadata.defaults('generation-response', {'kind': 'generation-response', 'contentType': 'application/json', 'sourceKeys': inputs,
            'extra': {'generation': generation, 'relationshipRole': 'intermediate'}}, 'provider-response.json', 'application/json', response_key)
        storage_layout.location(key, 'narration', metadata)
        storage_layout.location(response_key, 'generation-response', response_meta)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute("SELECT payload FROM records WHERE kind='narration' AND id=?", (identity,)).fetchone()
            if not current or json.loads(current[0]) != job:
                raise ValueError('Narration request changed before publication; retained output was not published')
            for ref in job.get('inputRefs', []):
                row = db.execute('SELECT game,data FROM objects WHERE key=?', (ref['key'],)).fetchone()
                if not row or row[0] != job['gameId'] or base64.b64encode(hashlib.sha256(row[1]).digest()).decode() != ref['sha256'] or len(row[1]) != ref['size']:
                    raise ValueError('Narration source changed before publication')
            for out_key, data, meta in ((key, audio, metadata), (response_key, response_bytes, response_meta)):
                if db.execute('SELECT 1 FROM objects WHERE key=?', (out_key,)).fetchone():
                    raise ValueError('Narration output collision; refusing overwrite')
                db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (out_key, job['gameId'], json.dumps(meta), data, now()))
            job.update(status='DONE', outputKey=key, responseKey=response_key, completedAt=time.time(), message=None)
            db.execute("UPDATE records SET payload=? WHERE kind='narration' AND id=?", (json.dumps(job), identity))
        return True
    except Exception as exc:
        current = store.get('narration', identity)
        if current and (current.get('status') not in {'QUEUED', 'SUBMITTED', 'RUNNING'} or any(current.get(field) != job.get(field) for field in ('text', 'voiceId', 'direction', 'sourceKeys', 'inputRefs'))):
            return False  # Preserve a concurrent cancellation or replacement request.
        job.update(status='UNKNOWN' if isinstance(exc, RuntimeError) else 'FAILED', message=str(exc)[:800], updatedAt=time.time())
        store.put('narration', identity, job, job['gameId'])
        return False


def run(database, work_dir, *, env_file=None, once=False, client=None):
    os.umask(0o077)
    store, root = Store(database), private_root(work_dir)
    try:
        client = client or ElevenLabs(env_file)
    except Exception as exc:
        store.put('service', 'narration', {'status': 'BLOCKED', 'updatedAt': time.time(), 'message': str(exc)})
        raise
    with store.path.with_name(store.path.name + '.narration.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stop = threading.Event()
        def pulse():
            while not stop.is_set():
                store.put('service', 'narration', {'status': 'RUNNING', 'updatedAt': time.time()})
                stop.wait(10)
        thread = threading.Thread(target=pulse, daemon=True)
        thread.start()
        try:
            while True:
                for job in reversed(store.list('narration')):
                    process(store, job['id'], root, client)
                if once:
                    break
                stop.wait(3)
        finally:
            stop.set()
            thread.join()
            store.put('service', 'narration', {'status': 'STOPPED', 'updatedAt': time.time()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path.home() / '.local/state/panther/development.sqlite')
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    run(args.database, args.work_dir, env_file=args.env_file, once=args.once)
