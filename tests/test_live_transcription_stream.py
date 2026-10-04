"""No provider calls: schema, credential redaction, immutable event receipts, ambiguity."""
import json
from pathlib import Path
import sys
import time
from unittest.mock import Mock
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
sys.path.insert(0, str(Path(__file__).parents[1] / 'infra/lambda/media-api'))
import live_transcription as live
import dev_live_transcription as local
from dev_server import Store
from test_browser_transcription import browser  # noqa:F401
from test_model_jobs import request, unpack, broker  # noqa:F401


def body(**extra):
    return {'gameId': 'imaginary', 'recordingId': 'recording-' + 'a' * 32, 'operationId': 'b' * 32, **extra}


def response():
    mock = Mock()
    mock.__enter__ = Mock(return_value=mock)
    mock.__exit__ = Mock(return_value=None)
    mock.read.return_value = json.dumps({'value': 'ek_synthetic', 'expires_at': int(time.time()) + 60,
        'session': {'type': 'transcription', 'id': 'provider-session', 'client_secret': {'value': 'ek_synthetic'}}}).encode()
    return mock


def test_schema_and_ephemeral_secret_never_saved():
    record = live.intent(body(), 'fictional-actor')
    opener = Mock(return_value=response())
    result = live.mint('synthetic-key', record, opener)
    assert result['clientSecret'] == 'ek_synthetic'
    assert 'ek_synthetic' not in json.dumps(record)
    assert record['response']['session']['id'] == 'provider-session'
    payload = json.loads(opener.call_args.args[0].data)
    assert payload['expires_after']['seconds'] == 60
    config = payload['session']['audio']['input']
    assert config['format'] == {'type': 'audio/pcm', 'rate': 24000}
    assert config['turn_detection'] is None
    assert config['noise_reduction']['type'] == 'far_field'
    assert config['transcription'] == {'model': 'gpt-live-transcribe', 'languages': ['en'], 'delay': 'low'}
    assert 'synthetic-key' not in json.dumps(record)


def test_local_ambiguous_session_is_not_reissued(tmp_path):
    store = Store(tmp_path / 'db.sqlite')
    store.put('game', 'imaginary', {'id': 'imaginary'})
    opener = Mock(side_effect=TimeoutError('private diagnostic'))
    with pytest.raises(ValueError, match='Audio is retained'):
        local.create(store, body(), lambda: 'synthetic-key', opener)
    with pytest.raises(FileExistsError):
        local.create(store, body(), lambda: 'synthetic-key', opener)
    assert opener.call_count == 1
    record = store.list('browser-live-session')[0]
    assert record['status'] == 'UNKNOWN' and record['cost']['status'] == 'unknown'
    assert 'private diagnostic' not in json.dumps(record)


def test_events_idempotent_bounded_and_credential_free(tmp_path):
    store = Store(tmp_path / 'db.sqlite')
    store.put('game', 'imaginary', {'id': 'imaginary'})
    result = local.create(store, body(), lambda: 'synthetic-key', Mock(return_value=response()))
    batch = body(sessionId=result['sessionId'], batchId='c' * 32, events=[{
        'type': 'conversation.item.input_audio_transcription.delta', 'item_id': 'item-one', 'delta': 'Actual words'}])
    assert local.save_events(store, batch) == local.save_events(store, batch)
    assert len(store.list('browser-live-events')) == 1
    with pytest.raises(FileExistsError):
        local.save_events(store, {**batch, 'events': [{**batch['events'][0], 'delta': 'Changed'}]})
    with pytest.raises(ValueError):
        local.save_events(store, {**batch, 'events': [{'type': 'session.created', 'client_secret': {'value': 'ek_bad'}}]})
    with pytest.raises(LookupError):
        local.save_events(store, {**batch, 'gameId': 'foreign'})


def test_hosted_auth_idempotency_and_actor_guard(browser, monkeypatch):  # noqa:F811
    secret = Mock()
    secret.get_secret_value.return_value = {'SecretString': 'synthetic-key'}
    monkeypatch.setattr(browser.boto3, 'client', lambda _: secret)
    opener = Mock(return_value=response())
    monkeypatch.setattr(live.urllib.request, 'urlopen', opener)
    assert request(browser, 'POST /browser-recording/live-session', body(), username='outsider')['statusCode'] == 403
    first = request(browser, 'POST /browser-recording/live-session', body())
    assert first['statusCode'] == 200
    assert request(browser, 'POST /browser-recording/live-session', body())['statusCode'] == 409
    assert opener.call_count == 1
    historical = request(browser, 'GET /browser-transcriptions', query={'gameId': 'imaginary', 'recordingId': body()['recordingId'], 'mode': 'live'})
    assert historical['statusCode'] == 200 and unpack(historical)['jobs'] == []
    batch = body(sessionId=unpack(first)['sessionId'], batchId='c' * 32, events=[{'type': 'error', 'error': {'code': 'synthetic'}}])
    assert request(browser, 'POST /browser-recording/live-events', batch, actor='foreign')['statusCode'] == 403
    assert request(browser, 'POST /browser-recording/live-events', batch)['statusCode'] == 200
    assert 'ek_synthetic' not in json.dumps(browser.TABLE.scan()['Items'], default=str)


def test_definitive_rejection_receipt_is_redacted_and_not_zero_cost():
    import io
    import urllib.error
    record = live.intent(body(), 'fictional-actor')
    exc = urllib.error.HTTPError(live.ENDPOINT, 401, 'Unauthorized', {'x-request-id': 'req-synthetic'},
        io.BytesIO(json.dumps({'error': {'message': 'Invalid sk-synthetic_private_key', 'code': 'invalid_api_key'}}).encode()))
    live.failure(record, exc)
    assert record['status'] == 'FAILED' and record['providerRequestId'] == 'req-synthetic'
    assert record['errorResponse']['error']['code'] == 'invalid_api_key'
    assert 'sk-synthetic' not in json.dumps(record)
    assert record['cost']['status'] == 'unknown'


def test_provider_session_identity_and_turn_order_are_actual_receipts():
    record = live.intent(body(), 'fictional-actor')
    live.mint('synthetic-key', record, Mock(return_value=response()))
    receipt = live.events(body(sessionId=record['sessionId'], batchId='c' * 32, events=[
        {'type': 'session.created', 'session': {'id': 'sess_actual', 'type': 'transcription'}},
        {'type': 'input_audio_buffer.committed', 'item_id': 'turn-two', 'previous_item_id': 'turn-one'}]), record)
    assert receipt['providerSessionIds'] == ['sess_actual']
    assert receipt['events'][1]['previous_item_id'] == 'turn-one'
