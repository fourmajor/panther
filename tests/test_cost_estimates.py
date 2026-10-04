"""Public estimates do not relabel unknown actual invoices or mutate source assets."""
import hashlib
import json
from pathlib import Path
import sys

import pytest
from panther_journal import cost_estimates as c

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
from dev_cost_estimates import migrate, overlay
from dev_server import Store


def test_tokens_and_cached_input():
    estimate = c.openai('gpt-5-mini-2025-08-07', {'input_tokens': 1000, 'output_tokens': 1000, 'input_tokens_details': {'cached_tokens': 500}})
    assert estimate['amount'] == '0.0021375'
    assert estimate['billingStatus'] == 'not-reconciled'
    assert c.openai('unknown', {'input_tokens': 1, 'output_tokens': 1}) is None
    assert c.openai('gpt-5-mini', {'input_tokens': 1, 'output_tokens': 1, 'input_tokens_details': {'cached_tokens': 2}}) is None


@pytest.mark.parametrize('model,amount', [('gpt-image-1', '0.042'), ('gpt-image-1.5', '0.034'), ('gpt-image-1-mini', '0.011')])
def test_fixed_image_output_excludes_unreported_inputs(model, amount):
    estimate = c.openai(model, request={'size': '1024x1024', 'quality': 'medium'})
    assert estimate['amount'] == amount and estimate['scope'] == 'image-output'
    assert c.openai(model, request={'size': 'auto', 'quality': 'medium'}) is None


def test_image_actual_usage():
    estimate = c.openai('gpt-image-1', {'input_tokens_details': {'text_tokens': 1000, 'image_tokens': 1000}, 'output_tokens': 1000})
    assert estimate['amount'] == '0.055'


def test_audio_settings_and_live_price():
    payload = {'duration': '8s', 'resolution': '720p', 'generate_audio': True}
    assert c.fal('veo-3.1-fast', payload)['amount'] == '1.2'
    assert c.fal('veo-3.1-fast-image-silent', payload) is None
    assert c.fal('veo-3.1-fast-image-silent', {**payload, 'generate_audio': False})['amount'] == '0.8'
    assert c.fal('veo-3.1-fast', payload, '0.16') is None
    assert c.fal('veo-3.1-fast', {**payload, 'duration': '6s'}) is None


def test_credits_without_invented_usd():
    estimate = c.eleven({'character-cost': '42'})
    assert estimate['credits'] == 42 and 'amount' not in estimate
    assert c.eleven({}) is None
    assert c.eleven({'character-cost': '-1'}) is None


def test_annotation_preserves_actual_cost():
    original = {'extra': {'generation': {'provider': 'OpenAI', 'model': 'gpt-5-mini', 'cost': {'status': 'unknown'}}}}
    annotated = c.annotate(original, response={'usage': {'input_tokens': 100, 'output_tokens': 100}})
    assert annotated['extra']['costEstimate']['status'] == 'estimated'
    assert annotated['extra']['generation']['cost'] == {'status': 'unknown'}
    assert 'costEstimate' not in original['extra']


def test_versioned_backfill_preserves_originals_and_rejects_changed_snapshot(tmp_path):
    store = Store(tmp_path / 'private.sqlite')
    key = 'games/fictional/assets/example/original/image.png'
    metadata = {'extra': {'generation': {'provider': 'OpenAI', 'model': 'gpt-image-1', 'cost': {'status': 'unknown'}}}}
    request = {'model': 'gpt-image-1', 'quality': 'medium', 'size': '1024x1024'}
    with store.connect() as db:
        for asset_key, meta, raw in ((key, metadata, b'original'), (key.rsplit('/', 1)[0] + '/generation-request.json', {}, json.dumps(request).encode())):
            db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (asset_key, 'fictional', json.dumps(meta), raw, '0'))
    assert migrate(store)['estimatedAssets'] == 1
    assert not store.list('asset-cost-estimate')
    assert migrate(store, apply=True)['estimatedAssets'] == 1
    assert migrate(store, apply=True)['estimatedAssets'] == 1
    with store.connect() as db:
        raw_meta, raw = db.execute('SELECT metadata,data FROM objects WHERE key=?', (key,)).fetchone()
    assert json.loads(raw_meta) == metadata and raw == b'original'
    assert overlay(store, key, metadata, raw)['extra']['costEstimate']['amount'] == '0.042'
    assert overlay(store, key, metadata, b'changed') == metadata
    record = store.get('asset-cost-estimate', hashlib.sha256(key.encode()).hexdigest())
    assert record['sourceMetadata'] == metadata


def test_readonly_live_receipt_validates_currency_and_unit():
    class Client:
        def request(self, method, url, params):
            assert method == 'GET'
            return {'prices': [{'endpoint_id': params['endpoint_id'], 'currency': 'USD', 'unit': 'seconds', 'unit_price': '0.15'}]}
    receipt = c.live_fal_price(Client(), 'veo-3.1-fast')
    assert receipt['response']['prices'][0]['unit_price'] == '0.15' and receipt['checkedAt']


def test_title_string_evidence_is_not_usage():
    metadata = {'extra': {'titleGeneration': {'provider': 'OpenAI', 'model': 'gpt-5-mini', 'evidence': 'retained provider receipt'}}}
    assert c.annotate(metadata) == metadata


def test_silent_historical_video_request_selects_exact_profile(tmp_path):
    from dev_cost_estimates import candidates
    store = Store(tmp_path / 'private.sqlite')
    prefix = 'games/fictional/assets/video/original/'
    metadata = {'extra': {'generation': {'provider': 'fal', 'model': 'Veo 3.1 Fast'}}}
    receipt = {'endpoint': 'fal-ai/veo3.1/fast/image-to-video', 'request': {'endpoint': 'fal-ai/veo3.1/fast/image-to-video', 'payload': {'duration': '8s', 'resolution': '720p', 'generate_audio': False}}}
    with store.connect() as db:
        for key, meta, raw in ((prefix+'video.mp4', metadata, b'original'), (prefix+'provider-response.json', {}, json.dumps(receipt).encode())):
            db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, 'fictional', json.dumps(meta), raw, '0'))
    estimate = list(candidates(store))[0][-1]
    assert estimate['amount'] == '0.8'
    assert estimate['evidence']['inputs']['model'] == 'veo-3.1-fast-image-silent'
