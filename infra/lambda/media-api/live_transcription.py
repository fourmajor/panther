"""Bounded Realtime transcription credentials and immutable provider event receipts.

The main API key and ephemeral values are never persisted. Creation is deliberately
one-shot: an ambiguous provider response cannot cause a second billed session.
"""
import hashlib
import json
import re
import time
import urllib.error
import urllib.request

MODEL = 'gpt-live-transcribe'
ENDPOINT = 'https://api.openai.com/v1/realtime/client_secrets'


def session():
    return {'type': 'transcription', 'audio': {'input': {
        'format': {'type': 'audio/pcm', 'rate': 24000},
        'transcription': {'model': MODEL, 'languages': ['en'], 'delay': 'low'},
        'turn_detection': None, 'noise_reduction': {'type': 'far_field'},
    }}}


def identity(body):
    game, recording, operation = (body.get(k) for k in ('gameId', 'recordingId', 'operationId'))
    if not isinstance(game, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', game):
        raise ValueError('Invalid game')
    if not isinstance(recording, str) or not re.fullmatch(r'recording-[a-f0-9]{32}', recording):
        raise ValueError('Invalid recording')
    if not isinstance(operation, str) or not re.fullmatch(r'[a-f0-9]{32}', operation):
        raise ValueError('Invalid live operation')
    return game + '#' + recording, 'REALTIME#' + operation


def intent(body, actor):
    identity(body)
    return {'schemaVersion': 1, 'gameId': body['gameId'], 'recordingId': body['recordingId'],
            'operationId': body['operationId'], 'actor': actor, 'status': 'REQUESTED',
            'createdAt': int(time.time()), 'model': MODEL, 'request': {
                'expires_after': {'anchor': 'created_at', 'seconds': 60}, 'session': session()},
            'cost': {'status': 'unknown'}}


def redacted(value):
    if isinstance(value, dict):
        return {k: redacted(v) for k, v in value.items()
                if k.lower() not in {'value', 'client_secret', 'clientsecret', 'authorization', 'api_key'}}
    if isinstance(value, list):
        return [redacted(v) for v in value]
    if isinstance(value, str) and (re.search(r'(?:ek_|sk-)[A-Za-z0-9_-]{3,}', value) or 'Bearer ' in value):
        return '[redacted]'
    return value


def mint(key, record, opener=None):
    if not isinstance(key, str) or not key.strip() or any(c in key for c in '\r\n'):
        raise ValueError('Live transcription is not configured')
    request = urllib.request.Request(ENDPOINT, data=json.dumps(record['request']).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key,
                 'OpenAI-Safety-Identifier': hashlib.sha256(record['actor'].encode()).hexdigest()}, method='POST')
    with (opener or urllib.request.urlopen)(request, timeout=25) as response:
        raw = response.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise ValueError('Invalid live credential response')
    payload = json.loads(raw)
    secret, expiry = payload.get('value'), payload.get('expires_at')
    if not isinstance(secret, str) or not re.fullmatch(r'ek_[A-Za-z0-9_-]+', secret):
        raise ValueError('Invalid live credential response')
    if not isinstance(expiry, int) or not time.time() < expiry <= time.time() + 90:
        raise ValueError('Invalid live credential expiry')
    record.update(status='ISSUED', expiresAt=expiry, response=redacted(payload),
                  sessionId=record['operationId'], sessionCorrelationId=record['operationId'],
                  providerSessionId=(payload.get('session') or {}).get('id'), issuedAt=int(time.time()))
    return {'clientSecret': secret, 'expiresAt': expiry, 'sessionId': record['sessionId'],
            'model': MODEL, 'session': session()}


def failure(record, exc):
    if isinstance(exc, urllib.error.HTTPError):
        record['providerRequestId'] = exc.headers.get('x-request-id') if exc.headers else None
        try:
            raw = exc.read(128 * 1024)
            record['errorResponse'] = redacted(json.loads(raw))
        except (ValueError, AttributeError, OSError):
            pass
    record.update(status='FAILED' if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500 else 'UNKNOWN',
                  errorType=type(exc).__name__, errorCode=exc.code if isinstance(exc, urllib.error.HTTPError) else None)
    return record


def events(body, record):
    identity(body)
    if record.get('status') != 'ISSUED' or body.get('sessionId') != record['sessionId']:
        raise ValueError('Live session does not match')
    batch = body.get('batchId')
    if not isinstance(batch, str) or not re.fullmatch(r'[a-f0-9]{32}', batch):
        raise ValueError('Invalid event batch')
    items = body.get('events')
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError('Invalid event batch')
    allowed = {'conversation.item.input_audio_transcription.delta', 'conversation.item.input_audio_transcription.completed',
               'conversation.item.input_audio_transcription.failed', 'error', 'session.created', 'session.updated',
               'input_audio_buffer.committed'}
    if any(not isinstance(e, dict) or e.get('type') not in allowed for e in items):
        raise ValueError('Unsupported live event')
    cleaned = redacted(items)
    if cleaned != items or len(json.dumps(items).encode()) > 100 * 1024:
        raise ValueError('Invalid live event data')
    return {'schemaVersion': 1, 'events': cleaned, 'receivedAt': int(time.time()),
            'providerSessionIds': list(dict.fromkeys(e['session']['id'] for e in items
                if e['type'] in {'session.created', 'session.updated'} and isinstance(e.get('session'), dict)
                and isinstance(e['session'].get('id'), str))),
            'sha256': hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()}
