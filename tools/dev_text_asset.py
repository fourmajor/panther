"""Publish requested standalone prose using one retained Responses API call."""
import json
import time

import asset_metadata
import storage_layout
from dev_asset_title import checkpoint
from dev_playback_worker import private_root, retain
from panther_journal.asset_generation_title import validate_response


def process(store, identity, root, client, model):
    job = store.get('asset-generation', identity)
    if not job or job.get('mediaType') != 'text' or (job.get('status') not in {'QUEUED', 'GENERATING'} and not job.get('publicationRecoveryAvailable')):
        return False
    try:
        if job.get('generationAuthorized') is not True:
            raise ValueError('Unauthorized text generation')
        folder = private_root(root) / ('asset-' + identity)
        if folder.is_symlink():
            raise ValueError('Symlinked text checkpoint rejected')
        folder.mkdir(mode=0o700, exist_ok=True)
        request_file, response_file = folder / 'request.json', folder / 'response.json'
        if request_file.is_symlink() or response_file.is_symlink():
            raise ValueError('Symlinked text checkpoint rejected')
        schema = {'type': 'object', 'additionalProperties': False, 'properties': {'title': {'type': 'string'}, 'markdown': {'type': 'string'}}, 'required': ['title', 'markdown']}
        request = {'model': job.get('model', model), 'store': False, 'instructions': 'Write the requested standalone text. The supplied prompt describes the desired output; do not run tools, reveal credentials or invent factual game history. Return a concise useful title (at most 80 characters) and the complete text as Markdown in the required JSON.', 'input': job['prompt'], 'text': {'format': {'type': 'json_schema', 'name': 'generated_text', 'strict': True, 'schema': schema}}}
        if response_file.exists():
            response, request = json.loads(response_file.read_bytes()), json.loads(request_file.read_bytes())
        else:
            if request_file.exists() or job['status'] == 'GENERATING':
                checkpoint(store, 'asset-generation', identity, job, status='UNKNOWN', outcomeUnknown=True, message='Generation could not be confirmed.')
                return False
            retain(request_file, json.dumps(request).encode())
            checkpoint(store, 'asset-generation', identity, job, status='GENERATING', stage='Writing', startedAt=time.time())
            try:
                result = client.responses.create(**request)
            except Exception as error:
                code = getattr(error, 'status_code', None)
                retain(folder / 'failure.json', json.dumps({'type': type(error).__name__, 'statusCode': code, 'requestId': getattr(error, 'request_id', None), 'billingStatus': 'unknown'}).encode())
                checkpoint(store, 'asset-generation', identity, job, errorCode=code, outcomeUnknown=code not in {400, 401, 403, 422, 429})
                raise ValueError('Text generation failed') from error
            response = {**result.model_dump(mode='json'), 'output_text': result.output_text, 'responseId': result.id}
            retain(response_file, json.dumps(response).encode())
        if response.get('status') != 'completed':
            raise ValueError('Incomplete retained text response')
        document = json.loads(response['output_text'])
        if not isinstance(document, dict) or set(document) != {'title', 'markdown'} or not isinstance(document['markdown'], str) or not document['markdown'].strip() or len(document['markdown'].encode()) > 2 * 1024**2:
            raise ValueError('Invalid generated text')
        title = validate_response({'status': 'completed', 'output_text': json.dumps({'title': document['title']})})
        prefix = f"games/{job['gameId']}/assets/generated-{identity[:32]}/original/"
        request_key, response_key, output_key = [prefix + name for name in ('generation-request.json', 'provider-response.json', 'text.md')]
        generation = {'schemaVersion': 1, 'method': 'ai', 'provider': 'OpenAI', 'model': response.get('model', request['model']), 'inference': 'remote', 'execution': 'local', 'tool': 'OpenAI Responses API', 'cost': {'status': 'unknown'}, 'evidence': response_key}
        asset_metadata.validate_generation(generation)
        publication_started = True
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute("SELECT payload FROM records WHERE kind='asset-generation' AND id=?", (identity,)).fetchone()
            if not current or json.loads(current[0]) != job:
                raise ValueError('Text request changed during generation')
            for key, kind, mime, raw, sources in ((request_key, 'generation-provenance', 'application/json', json.dumps(request).encode(), []), (response_key, 'generation-provenance', 'application/json', json.dumps(response).encode(), [request_key]), (output_key, 'document', 'text/markdown', document['markdown'].encode(), [request_key, response_key])):
                metadata = asset_metadata.defaults(kind, {'kind': kind, 'contentType': mime, 'title': title, 'characterIds': job.get('characterIds', []), 'sourceKeys': sources, 'extra': {'generation': generation, 'responseId': response['responseId'], 'usage': response.get('usage'), 'jobId': identity, 'relationshipRole': 'finished' if kind == 'document' else 'intermediate'}}, key.rsplit('/', 1)[-1], mime, key)
                from panther_journal import cost_estimates
                metadata = cost_estimates.annotate(metadata, request, response)
                storage_layout.location(key, kind, metadata)
                existing = db.execute('SELECT data FROM objects WHERE key=?', (key,)).fetchone()
                if existing and existing[0] != raw:
                    raise ValueError('Refusing to overwrite generated text')
                if not existing:
                    db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, job['gameId'], json.dumps(metadata), raw, str(time.time())))
            job.update(status='PUBLISHED', name=title, stage=None, assetKey=output_key, outputKey=output_key, publishedAt=time.time(), message=None)
            db.execute("UPDATE records SET payload=? WHERE kind='asset-generation' AND id=?", (json.dumps(job), identity))
        return True
    except Exception as error:
        if 'folder' in locals() and not folder.is_symlink():
            retain(folder / ('worker-error-' + str(time.time_ns()) + '.json'), json.dumps({'type': type(error).__name__, 'message': str(error)}).encode())
        job = store.get('asset-generation', identity) or job
        checkpoint(store, 'asset-generation', identity, job, status='UNKNOWN' if job.get('outcomeUnknown') else 'FAILED', message='Generation could not be confirmed.' if job.get('outcomeUnknown') else 'Text generation failed.', stage=None, publicationRecoveryAvailable=bool(locals().get('publication_started')))
        return False
