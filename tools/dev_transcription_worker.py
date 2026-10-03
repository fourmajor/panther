# ruff: noqa: E402 -- repository modules require the explicit script import path below.
"""Server-side OpenAI live and final room transcription for local SQLite data."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import os
import re
from pathlib import Path
import sys
import threading
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'infra/lambda/media-api'))
sys.path.insert(0, str(ROOT / 'tools'))

import asset_metadata
import storage_layout
from dev_server import Store
from dev_playback_worker import private_root, retain
from dev_editorial_worker import load_key
from panther_journal.browser_recording import BrowserRecording

MODEL = 'gpt-4o-transcribe'
MAX_PCM = 24 * 1024**2  # Below OpenAI's 25 MB file limit, including WAV headers.


def digest(raw):
    return base64.b64encode(hashlib.sha256(raw).digest()).decode()


def source(store, ref, game):
    metadata, raw = store.object(ref['key'])
    with store.connect() as db:
        row = db.execute('SELECT game FROM objects WHERE key=?', (ref['key'],)).fetchone()
    if row != (game,) or not ref['key'].startswith(f'games/{game}/assets/') or digest(raw) != ref['sha256'] or len(raw) != ref['size']:
        raise ValueError('Transcription source identity, checksum or size changed')
    return raw


def audio_inputs(store, job):
    refs = job['inputs']
    if not refs or len(refs) > 1000:
        raise ValueError('Choose bounded recording audio')
    doc = None
    if job['mode'] == 'final':
        raw = source(store, job['recording'], job['gameId'])
        doc = BrowserRecording.model_validate_json(raw)
        if doc.status not in {'complete', 'interrupted'} or doc.gameId != job['gameId'] or doc.id != job['recordingId'] or len(doc.parts) != len(refs):
            raise ValueError('Full transcription requires an explicitly completed immutable recording')
        for ref, part in zip(refs, doc.parts, strict=True):
            if ref['sha256'] != base64.b64encode(bytes.fromhex(part.sha256)).decode() or ref['key'] != job['recording']['key'].rsplit('/', 1)[0] + '/' + part.file:
                raise ValueError('Recording audio differs from its completed manifest')
    elif job['mode'] != 'live' or len(refs) != 1:
        raise ValueError('Invalid transcription mode')
    pcm = bytearray()
    for ref in refs:
        raw = source(store, ref, job['gameId'])
        with wave.open(io.BytesIO(raw)) as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 32000, 'NONE'):
                raise ValueError('Expected lossless mono 32 kHz browser WAV')
            if abs(audio.getnframes() / 32000 - ref['duration']) > 1 / 32000:
                raise ValueError('Recording sample count differs from pinned duration')
            pcm.extend(audio.readframes(audio.getnframes()))
    return bytes(pcm), doc


def wav(pcm):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(32000)
        audio.writeframes(pcm)
    return output.getvalue()


def publish(store, job, filename, document, kind, inputs, model):
    raw = json.dumps(document, ensure_ascii=False).encode()
    key = f"games/{job['gameId']}/assets/transcription-{job['id'][:32]}/original/{filename}"
    generation = {'schemaVersion': 1, 'method': 'ai', 'provider': 'OpenAI', 'model': model, 'inference': 'remote', 'execution': 'local',
                  'tool': 'OpenAI audio transcriptions', 'cost': {'status': 'unknown'}}
    metadata = asset_metadata.defaults(kind, {'kind': kind, 'title': job.get('sessionName') or job.get('sessionId') or 'Recording',
        'sessionId': job['sessionId'], 'sourceKeys': inputs, 'contentType': 'application/json',
        'extra': {'generation': generation, 'sha256': digest(raw), 'recordingId': job['recordingId'], 'captureWarnings': job.get('captureWarnings', [])}}, filename, 'application/json', key)
    storage_layout.location(key, kind, metadata)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT payload FROM records WHERE kind='transcription' AND id=?", (job['id'],)).fetchone()
        current = json.loads(row[0]) if row else None
        if not current or current.get('status') != 'RUNNING' or any(current.get(field) != job.get(field) for field in ('inputs', 'recording', 'mode', 'gameId', 'sessionId')):
            raise ValueError('Transcription request changed; provider response remains retained')
        for ref in job['inputs'] + ([job['recording']] if job.get('recording') else []):
            source_row = db.execute('SELECT game,data FROM objects WHERE key=?', (ref['key'],)).fetchone()
            if not source_row or source_row[0] != job['gameId'] or digest(source_row[1]) != ref['sha256'] or len(source_row[1]) != ref['size']:
                raise ValueError('Transcription source changed before publication')
        old = db.execute('SELECT data FROM objects WHERE key=?', (key,)).fetchone()
        if old and old[0] != raw:
            raise ValueError('Transcription output collision; refusing overwrite')
        if not old:
            db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, job['gameId'], json.dumps(metadata), raw, datetime.now(timezone.utc).isoformat()))
    return key


def save_active_job(store, identity, job, *, allowed=('RUNNING',)):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT payload FROM records WHERE kind='transcription' AND id=?", (identity,)).fetchone()
        current = json.loads(row[0]) if row else None
        if not current or current.get('status') not in allowed or any(current.get(field) != job.get(field) for field in ('inputs', 'recording', 'mode', 'gameId', 'sessionId')):
            raise ValueError('Transcription request changed while processing')
        db.execute("UPDATE records SET payload=? WHERE kind='transcription' AND id=?", (json.dumps(job), identity))


def process(store, identity, root, client, model=MODEL):
    job = store.get('transcription', identity)
    if not job or job.get('status') not in {'SUBMITTED', 'QUEUED', 'RUNNING'}:
        return False
    try:
        if not re.fullmatch(r'[a-f0-9]{64}', identity):
            raise ValueError('Invalid transcription job identity')
        if job.get('status') == 'RUNNING':
            raise RuntimeError('The worker stopped during transcription. The request outcome may be unknown; no paid request was repeated. Review retained responses before explicitly retrying.')
        pcm, manifest = audio_inputs(store, job)
        folder = root / identity
        if folder.is_symlink():
            raise ValueError('Symlinked transcription checkpoint rejected')
        folder.mkdir(mode=0o700, exist_ok=True)
        chunks = [pcm[index:index + MAX_PCM] for index in range(0, len(pcm), MAX_PCM)]
        if not chunks:
            raise ValueError('The recording contains no audio samples')
        job.update(status='RUNNING', message=None, startedAt=time.time(), totalWindows=len(chunks), completedWindows=0)
        save_active_job(store, identity, job, allowed=('SUBMITTED', 'QUEUED'))
        segments, responses = [], []
        cursor = float(job.get('start', 0))
        for index, chunk in enumerate(chunks):
            file = folder / f'window-{index:04d}.wav'
            retain(file, wav(chunk))
            retain(folder / f'request-{index:04d}.json', json.dumps({'model': model, 'inputSha256': digest(file.read_bytes()), 'sourceKeys': [ref['key'] for ref in job['inputs']], 'startedAt': time.time()}).encode())
            try:
                with file.open('rb') as stream:
                    response = client.audio.transcriptions.create(model=model, file=stream, response_format='json')
            except Exception as exc:
                code = getattr(exc, 'status_code', None)
                request_id = getattr(exc, 'request_id', None)
                retain(folder / f'failure-{index:04d}.json', json.dumps({'statusCode': code, 'requestId': request_id, 'type': type(exc).__name__, 'billingStatus': 'unknown'}).encode())
                message = {401: 'OpenAI rejected the API key; update .env and restart the worker.',
                           403: 'The OpenAI project cannot access the transcription model; check project permissions.',
                           429: 'OpenAI reports a quota or rate limit; check project billing and limits.'}.get(code, 'OpenAI transcription failed or its outcome is unknown; check connectivity and provider request history.')
                raise RuntimeError(message + ' Audio is retained; no automatic paid retry.' + (f' Request ID: {request_id}' if request_id else '')) from exc
            document = response.model_dump(mode='json')
            retain(folder / f'response-{index:04d}.json', json.dumps(document, ensure_ascii=False).encode())
            if not isinstance(document.get('text'), str):
                raise RuntimeError('OpenAI returned invalid transcription output; the response is retained and no automatic retry was submitted.')
            response_key = publish(store, job, f'response-{index:04d}.json', document, 'transcription-response', [ref['key'] for ref in job['inputs']], model)
            end = cursor + len(chunk) / 64000
            segments.append({'start': cursor, 'end': end, 'text': document['text'], 'playerId': None})
            responses.append(response_key)
            cursor = end
            job['completedWindows'] = index + 1
            save_active_job(store, identity, job)
        source_keys = [*[ref['key'] for ref in job['inputs']], *([job['recording']['key']] if job.get('recording') else [])]
        transcript = {'schemaVersion': 1, 'entityType': 'BrowserTranscript', 'artifactType': 'raw-transcript', 'gameId': job['gameId'],
            'recordingId': job['recordingId'], 'sessionId': job['sessionId'], 'sessionName': job.get('sessionName'), 'mode': job['mode'],
            **({'recordedAt': manifest.startedAt, 'startedAt': manifest.startedAt} if manifest else {}),
            'requestedModel': model, 'reviewStatus': 'unreviewed', 'players': [], 'sourceKeys': source_keys,
            'inputArtifacts': {f'response-{i}': {'key': key} for i, key in enumerate(responses)}, 'timestampPrecision': 'window-boundary',
            'captureIntegrity': {'status': manifest.captureStatus if manifest and hasattr(manifest, 'captureStatus') else 'unverified',
                                 'warnings': list(manifest.captureWarnings) if manifest else job.get('captureWarnings', []),
                                 'coverage': 'Recorded browser PCM; hardware continuity and speaker attribution unverified.'}, 'segments': segments}
        key = publish(store, job, 'transcript.json', transcript, 'raw-transcript' if job['mode'] == 'final' else 'live-transcript', source_keys + responses, model)
        job.update(status='DONE', message=None, text='\n'.join(segment['text'] for segment in segments), start=segments[0]['start'], end=segments[-1]['end'],
                   transcriptKey=key, responseKey=responses[-1], completedAt=time.time())
        save_active_job(store, identity, job)
        if job['mode'] == 'final':
            try:
                summary = store.submit_transcript_summary({'gameId': job['gameId'], 'key': key})
                job['summaryJobId'] = summary['jobId']
            except Exception as exc:
                job['summaryMessage'] = str(exc)[:500]
            store.put('transcription', identity, job, job['gameId'])
        return True
    except Exception as exc:
        current = store.get('transcription', identity)
        if current and (current.get('status') not in {'SUBMITTED', 'QUEUED', 'RUNNING'} or any(current.get(field) != job.get(field) for field in ('inputs', 'recording', 'mode', 'gameId', 'sessionId'))):
            return False
        job.update(status='UNKNOWN' if isinstance(exc, RuntimeError) else 'FAILED', message=str(exc)[:800], updatedAt=time.time())
        store.put('transcription', identity, job, job['gameId'])
        return False


def run(database, work_dir, *, env_file=None, model=MODEL, once=False, client=None):
    os.umask(0o077)
    store, root = Store(database), private_root(work_dir)
    if client is None:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=load_key(env_file=env_file), max_retries=0, timeout=240)
        except Exception as exc:
            store.put('service', 'transcription', {'status': 'BLOCKED', 'updatedAt': time.time(), 'message': str(exc)})
            raise
    with store.path.with_name(store.path.name + '.transcription.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stop = threading.Event()
        def pulse():
            while not stop.is_set():
                store.put('service', 'transcription', {'status': 'RUNNING', 'updatedAt': time.time(), 'model': model})
                stop.wait(10)
        thread = threading.Thread(target=pulse, daemon=True)
        thread.start()
        try:
            while True:
                for job in reversed(store.list('transcription')):
                    if job.get('status') in {'SUBMITTED', 'QUEUED', 'RUNNING'}:
                        process(store, job['id'], root, client, model)
                if once:
                    break
                stop.wait(2)
        finally:
            stop.set()
            thread.join()
            store.put('service', 'transcription', {'status': 'STOPPED', 'updatedAt': time.time(), 'model': model})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path.home() / '.local/state/panther/development.sqlite')
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--model', default=MODEL)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    run(args.database, args.work_dir, env_file=args.env_file, model=args.model, once=args.once)
