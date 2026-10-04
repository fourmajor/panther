"""Durable direct-API titles for explicitly requested local generated assets."""
import json
import os

from dev_playback_worker import retain
from panther_journal.asset_generation_title import request_for, validate_response


def checkpoint(store, kind, identity, job, **changes):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT payload FROM records WHERE kind=? AND id=?', (kind, identity)).fetchone()
        if not row or json.loads(row[0]) != job:
            raise ValueError('Generation request changed while preparing its title')
        job.update(changes)
        db.execute('UPDATE records SET payload=? WHERE kind=? AND id=?', (json.dumps(job), kind, identity))


def ensure_title(store, record_kind, identity, job, folder, client):
    if job.get('name'):
        return job['name']
    request_file, response_file = folder / 'title-request.json', folder / 'title-response.json'
    if request_file.is_symlink() or response_file.is_symlink():
        raise ValueError('Symlinked title checkpoint rejected')
    request = request_for(job['type'], job['prompt'], os.environ.get('PANTHER_TITLE_MODEL', 'gpt-5-mini'))
    if request_file.exists():
        retained = json.loads(request_file.read_text())
        if retained.get('input') != request['input']:
            raise ValueError('Title request inputs changed')
        request = retained
    if response_file.exists():
        response = json.loads(response_file.read_text())
    else:
        if request_file.exists() or job.get('titlePhase') == 'GENERATING':
            checkpoint(store, record_kind, identity, job, outcomeUnknown=True, titlePhase='UNKNOWN')
            raise ValueError('Title generation could not be confirmed. No request was repeated.')
        if client is None:
            from openai import OpenAI
            from dev_editorial_worker import load_key
            client = OpenAI(api_key=load_key(env_file=os.environ.get('PANTHER_ENV_FILE')), max_retries=0, timeout=180)
        retain(request_file, json.dumps(request).encode())
        checkpoint(store, record_kind, identity, job, titlePhase='GENERATING', stage='Preparing title')
        try:
            result = client.responses.create(**request)
        except Exception as error:
            code = getattr(error, 'status_code', None)
            retain(folder / 'title-failure.json', json.dumps({'type': type(error).__name__, 'statusCode': code, 'requestId': getattr(error, 'request_id', None), 'billingStatus': 'unknown'}).encode())
            checkpoint(store, record_kind, identity, job, outcomeUnknown=code not in {400, 401, 403, 422, 429}, errorCode=code, titlePhase='FAILED')
            raise ValueError('The asset title could not be generated. No request was repeated.') from error
        response = result.model_dump(mode='json')
        response['output_text'] = result.output_text
        response['responseId'] = result.id
        retain(response_file, json.dumps(response).encode())
    title = validate_response(response)
    # Retain complete requests/receipts in private SQLite as well as checkpoints.
    store.put('asset-title', identity, {'request': request, 'response': response, 'jobId': identity}, job['gameId'])
    checkpoint(store, record_kind, identity, job, name=title.strip(), titlePhase='READY', stage=None, titleUsage=response.get('usage'),
        titleGeneration={'schemaVersion': 1, 'method': 'ai', 'provider': 'OpenAI', 'model': response.get('model', request['model']), 'inference': 'remote', 'execution': 'local', 'tool': 'OpenAI Responses API', 'cost': {'status': 'unknown'}, 'evidence': response['responseId']})
    return job['name']
