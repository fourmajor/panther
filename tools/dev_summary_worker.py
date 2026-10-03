# ruff: noqa: E402 -- repository modules require the explicit script import path below.
"""Source-grounded transcript summaries through the local OpenAI API worker."""
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'infra/lambda/media-api'))
sys.path.insert(0, str(ROOT / 'tools'))
import asset_metadata
import storage_layout
from dev_server import Store
from dev_playback_worker import private_root, retain
from dev_editorial_worker import load_key, now
from panther_journal.editorial import reading_transcript
from panther_journal import summary_policy

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['title', 'summary', 'segmentIndexes', 'uncertainties'],
          'properties': {'title': {'type': 'string'}, 'summary': {'type': 'string'}, 'segmentIndexes': {'type': 'array', 'items': {'type': 'integer'}},
                         'uncertainties': {'type': 'array', 'items': {'type': 'string'}}}}
LEGACY = 'Summary generation is not configured in local development.'


def process(store, identity, root, client, model='gpt-5-mini'):
    job = store.get('transcript-summary', identity)
    if not job or job.get('status') not in {'QUEUED', 'SUBMITTED', 'RUNNING'}:
        return False
    try:
        if not re.fullmatch(r'[a-f0-9]{64}', identity):
            raise ValueError('Invalid summary job identity')
        if job.get('status') == 'RUNNING':
            raise RuntimeError('Summary worker stopped during an OpenAI request. Review retained responses before explicitly retrying; no automatic paid repeat.')
        reference, doc = store.transcript_summary_source(job['gameId'], job['key'])
        if reference != job['source']:
            raise ValueError('Pinned transcript changed; summary was not generated')
        folder = root / identity
        if folder.is_symlink():
            raise ValueError('Symlinked summary checkpoint rejected')
        folder.mkdir(mode=0o700, exist_ok=True)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT payload FROM records WHERE kind='transcript-summary' AND id=?", (identity,)).fetchone()
            if not row or json.loads(row[0]) != job:
                raise ValueError('Summary request changed before generation')
            job.update(status='RUNNING', message=None, startedAt=time.time())
            db.execute("UPDATE records SET payload=? WHERE kind='transcript-summary' AND id=?", (json.dumps(job), identity))
        data = json.dumps(reading_transcript(doc), ensure_ascii=False)
        if len(data.encode()) > 900_000:
            raise ValueError('Transcript is too large for a safe summary request')
        request = {'model': model, 'store': False,
                   'instructions': summary_policy.INSTRUCTIONS,
                   'input': data, 'text': {'format': {'type': 'json_schema', 'name': 'transcript_summary', 'strict': True, 'schema': SCHEMA}}}
        retain(folder / 'request.json', json.dumps(request, ensure_ascii=False).encode())
        try:
            response = client.responses.create(**request)
        except Exception as exc:
            status = getattr(exc, 'status_code', None)
            retain(folder / 'failure.json', json.dumps({'type': type(exc).__name__, 'statusCode': status, 'requestId': getattr(exc, 'request_id', None), 'billingStatus': 'unknown'}).encode())
            message = {401: 'OpenAI rejected the API key; update .env and restart the worker.', 403: 'The OpenAI project cannot access the summary model.',
                       429: 'OpenAI reports a quota or rate limit; check project billing and limits.'}.get(status, 'The OpenAI summary request failed or its outcome is unknown.')
            raise RuntimeError(message + ' The transcript is retained; no automatic paid retry.') from exc
        result = response.model_dump(mode='json')
        retain(folder / 'response.json', json.dumps(result, ensure_ascii=False).encode())
        if result.get('status') != 'completed' or not response.output_text:
            raise RuntimeError('OpenAI returned incomplete summary output. The response is retained; no automatic retry.')
        summary = json.loads(response.output_text)
        if set(summary) != set(SCHEMA['required']) or not isinstance(summary['title'], str) or not 1 <= len(summary['title']) <= summary_policy.TITLE_LIMIT or not isinstance(summary['summary'], str) or not 1 <= len(summary['summary']) <= summary_policy.SUMMARY_LIMIT or not isinstance(summary['segmentIndexes'], list) or not summary['segmentIndexes'] or any(type(i) is not int or not 0 <= i < len(doc['segments']) for i in summary['segmentIndexes']) or not isinstance(summary['uncertainties'], list) or any(not isinstance(value, str) for value in summary['uncertainties']):
            raise ValueError('Summary output failed evidence validation; retained for inspection')
        generation = {'schemaVersion': 1, 'method': 'ai', 'provider': 'OpenAI', 'model': result.get('model', model), 'inference': 'remote',
                      'execution': 'local', 'tool': 'OpenAI Responses API', 'cost': {'status': 'unknown'}, 'evidence': {'responseId': response.id, 'usage': result.get('usage')}}
        document = {'schemaVersion': 1, 'entityType': 'TranscriptSummary', 'summaryPolicyVersion': summary_policy.VERSION, 'gameId': job['gameId'], 'jobId': identity, 'source': reference,
                    'sourceKeys': [job['key']], 'summary': summary, 'participants': job.get('participants', []), 'recordedAt': job.get('recordedAt'),
                    'generation': generation, 'reviewStatus': 'ai-generated-unverified', 'previousSummaryKey': job.get('previousSummaryKey')}
        raw = json.dumps(document, ensure_ascii=False).encode()
        key = f"games/{job['gameId']}/assets/summary-{identity[:32]}/original/summary.json"
        metadata = asset_metadata.defaults('transcript-summary', {'kind': 'transcript-summary', 'title': summary['title'], 'sourceKeys': [job['key']],
            'contentType': 'application/json', 'extra': {'generation': generation, 'sha256': base64.b64encode(hashlib.sha256(raw).digest()).decode()}}, 'summary.json', 'application/json', key)
        storage_layout.location(key, 'transcript-summary', metadata)
        pointer_id = job['gameId'] + ':' + hashlib.sha256(job['key'].encode()).hexdigest()
        processing_job = dict(job)
        job.update(summaryPolicyVersion=summary_policy.VERSION, status='READY', message=None, summary=summary, assetKey=key, completedAt=time.time())
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = db.execute("SELECT payload FROM records WHERE kind='transcript-summary' AND id=?", (identity,)).fetchone()
            if not record or json.loads(record[0]) != processing_job:
                raise ValueError('Summary request changed before publication; response remains retained')
            current = db.execute('SELECT data FROM objects WHERE key=?', (job['key'],)).fetchone()
            if not current or base64.b64encode(hashlib.sha256(current[0]).digest()).decode() != reference['sha256']:
                raise ValueError('Transcript changed during summary generation')
            previous = db.execute('SELECT data FROM objects WHERE key=?', (key,)).fetchone()
            if previous and previous[0] != raw:
                raise ValueError('Summary output collision; refusing overwrite')
            if not previous:
                db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, job['gameId'], json.dumps(metadata), raw, now()))
            pointer_row = db.execute("SELECT payload FROM records WHERE kind='summary-source' AND id=?", (pointer_id,)).fetchone()
            pointer = json.loads(pointer_row[0]) if pointer_row else {}
            if pointer.get('jobId') == identity:
                pointer['readyJobId'] = identity
                db.execute("UPDATE records SET payload=? WHERE kind='summary-source' AND id=?", (json.dumps(pointer), pointer_id))
            db.execute("UPDATE records SET payload=? WHERE kind='transcript-summary' AND id=?", (json.dumps(job), identity))
        return True
    except Exception as exc:
        current = store.get('transcript-summary', identity)
        if current and (current.get('status') not in {'QUEUED', 'SUBMITTED', 'RUNNING'} or any(current.get(field) != job.get(field) for field in ('source', 'key', 'operationId'))):
            return False
        job.update(status='ATTENTION', message=str(exc)[:800], updatedAt=time.time())
        store.put('transcript-summary', identity, job, job['gameId'])
        return False



def rebuild_policy(store, *, apply=False):
    """Explicit, idempotent replacement jobs; never overwrite ready history or retry failures."""
    records, blockers = [], []
    for pointer in store.list('summary-source'):
        current = store.get('transcript-summary', pointer.get('jobId', ''))
        if not current:
            continue
        record = {'gameId': current['gameId'], 'key': current['key'], 'previousJobId': current['jobId']}
        try:
            reference, _ = store.transcript_summary_source(current['gameId'], current['key'])
            if reference != current['source']:
                raise ValueError('Pinned transcript changed')
            if current.get('status') != 'READY':
                record['status'] = current.get('status')
                if current.get('status') not in {'QUEUED', 'SUBMITTED', 'RUNNING'} or current.get('operationId') != summary_policy.rebuild_operation(current['gameId'], current['key']):
                    blockers.append({**record, 'reason': 'Existing request needs attention; no automatic paid retry'})
            elif current.get('summaryPolicyVersion') == summary_policy.VERSION:
                record['status'] = 'READY'
            else:
                record['status'] = 'NEEDS_REBUILD'
                if apply:
                    replacement = store.submit_transcript_summary({'gameId': current['gameId'], 'key': current['key'], 'operationId': summary_policy.rebuild_operation(current['gameId'], current['key'])})
                    record.update(jobId=replacement['jobId'], status=replacement['status'])
        except (ValueError, FileNotFoundError) as exc:
            blockers.append({**record, 'reason': str(exc)})
        records.append(record)
    return {'schemaVersion': 1, 'operation': 'transcript-summary-policy-v2-rebuild', 'applied': apply, 'records': records, 'blockers': blockers}


def run(database, work_dir, *, env_file=None, model='gpt-5-mini', once=False, client=None):
    os.umask(0o077)
    store, root = Store(database), private_root(work_dir)
    if client is None:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=load_key(env_file=env_file), max_retries=0, timeout=240)
        except Exception as exc:
            store.put('service', 'summary', {'status': 'BLOCKED', 'updatedAt': time.time(), 'message': str(exc)})
            raise
    with store.path.with_name(store.path.name + '.summary.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for job in store.list('transcript-summary'):
            if job.get('status') == 'ATTENTION' and job.get('message') == LEGACY:
                store.put('development-migration', 'summary-api-v1:' + job['jobId'], {'previousRecord': job, 'migratedAt': now()}, job['gameId'])
                store.put('transcript-summary', job['jobId'], {**job, 'status': 'QUEUED', 'message': None}, job['gameId'])
        stop = threading.Event()
        def pulse():
            while not stop.is_set():
                store.put('service', 'summary', {'status': 'RUNNING', 'updatedAt': time.time(), 'model': model})
                stop.wait(10)
        thread = threading.Thread(target=pulse, daemon=True)
        thread.start()
        try:
            while True:
                for job in reversed(store.list('transcript-summary')):
                    if job.get('status') in {'QUEUED', 'SUBMITTED', 'RUNNING'}:
                        process(store, job['jobId'], root, client, model)
                if once:
                    break
                stop.wait(2)
        finally:
            stop.set()
            thread.join()
            store.put('service', 'summary', {'status': 'STOPPED', 'updatedAt': time.time(), 'model': model})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path.home() / '.local/state/panther/development.sqlite')
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--model', default='gpt-5-mini')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--rebuild-summary-policy', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.rebuild_summary_policy:
        if not args.report:
            parser.error('--rebuild-summary-policy requires --report outside the repository')
        os.umask(0o077)
        private_root(args.report.parent)
        report = rebuild_policy(Store(args.database), apply=args.apply)
        retain(args.report, json.dumps(report, ensure_ascii=False).encode())
        print(f"Summary policy inventory: {len(report['records'])} sources, {len(report['blockers'])} blockers")
        if report['blockers']:
            raise SystemExit(1)
    else:
        if args.apply or args.report:
            parser.error('--apply/--report require --rebuild-summary-policy')
        run(args.database, args.work_dir, env_file=args.env_file, model=args.model, once=args.once)
