"""Versioned, provider-sourced executable fal image contracts; read-only discovery."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

URL = 'https://api.fal.ai/v1/models'
PRICES = URL + '/pricing'
CATALOG_ID = 'fal-text-to-image-v1'
VIDEO_PRICE_ID = 'curated-video-prices-v1'
VIDEO_PRICE_ENDPOINTS = ('minimax/h3-max/text-to-video', 'minimax/h3-max/image-to-video', 'fal-ai/veo3.1/fast', 'fal-ai/veo3.1/fast/image-to-video', 'fal-ai/kling-video/v3/pro/text-to-video', 'fal-ai/kling-video/v3/pro/image-to-video')


def resolved(schema, document):
    if not isinstance(schema, dict):
        raise ValueError('Invalid model schema')
    ref = schema.get('$ref')
    if ref:
        if not re.fullmatch(r'#/components/schemas/[A-Za-z0-9_]+', ref):
            raise ValueError('Unsupported model schema reference')
        return document['components']['schemas'][ref.rsplit('/', 1)[1]]
    return schema


def contract(model):
    endpoint, metadata, document = model.get('endpoint_id'), model.get('metadata', {}), model.get('openapi', {})
    if not isinstance(endpoint, str) or not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_./-]+', endpoint) or '..' in endpoint or metadata.get('status') != 'active' or metadata.get('category') != 'text-to-image':
        raise ValueError('Not an active image generator')
    operation = document['paths']['/' + endpoint]['post']
    schema = resolved(operation['requestBody']['content']['application/json']['schema'], document)
    properties = schema.get('properties', {})
    if properties.get('prompt', {}).get('type') != 'string':
        raise ValueError('No executable prompt input')
    payload = {}
    for name in schema.get('required', []):
        if name != 'prompt':
            field = resolved(properties[name], document)
            if 'default' not in field or field['default'] is None:
                raise ValueError('Model requires additional inputs')
            payload[name] = deepcopy(field['default'])
    # Standard provider controls pin one output without weakening its safety defaults.
    for name, value in (('num_images', 1), ('num_outputs', 1), ('sync_mode', False)):
        if name in properties:
            payload[name] = value
    if 'output_format' in properties and 'png' in properties['output_format'].get('enum', []):
        payload['output_format'] = 'png'
    response_operation = document['paths']['/' + endpoint + '/requests/{request_id}']['get']
    output = resolved(response_operation['responses']['200']['content']['application/json']['schema'], document)
    output_properties = output.get('properties', {})
    if 'images' in output_properties:
        image = resolved(output_properties['images'].get('items', {}), document)
        shape = 'images'
    elif 'image' in output_properties:
        image = resolved(output_properties['image'], document)
        shape = 'image'
    else:
        raise ValueError('Model has no supported image output')
    if image.get('properties', {}).get('url', {}).get('type') != 'string':
        raise ValueError('Model has no downloadable image output')
    return {'schemaVersion': 1, 'endpoint': endpoint, 'provider': 'fal', 'name': metadata.get('display_name') or endpoint,
            'defaults': payload, 'inputSchema': schema, 'outputSchema': output, 'outputShape': shape,
            'schemaHash': hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}


def price_options(prices, checked):
    result = {}
    for item in prices.get('prices', []):
        try:
            amount = Decimal(str(item['unit_price']))
            if not amount.is_finite() or amount < 0 or item['currency'] != 'USD' or not isinstance(item['unit'], str):
                continue
            result[item['endpoint_id']] = {'schemaVersion': 1, 'status': 'estimated', 'amount': str(amount), 'currency': 'USD',
                 'unit': item['unit'], 'checkedAt': checked, 'evidence': {'source': PRICES, 'response': deepcopy(item)},
                 'billingStatus': 'not-reconciled', 'scope': 'Provider base unit rate; selected settings can affect final usage'}
        except (KeyError, TypeError, InvalidOperation):
            continue
    return result


def refresh(store, fal):
    checked = datetime.now(timezone.utc).isoformat()
    models, excluded, cursor, seen = [], [], None, set()
    for _ in range(500):
        params = {'limit': 10, 'category': 'text-to-image', 'expand': 'openapi-3.0'}
        if cursor:
            params['cursor'] = cursor
        page = fal.request('GET', URL, params=params)
        if not isinstance(page.get('models'), list) or type(page.get('has_more')) is not bool:
            raise ValueError('Incomplete image catalog response')
        for model in page['models']:
            try:
                normalized = contract(model)
                if normalized['endpoint'] not in {value['endpoint'] for value in models}:
                    models.append(normalized)
            except (ValueError, KeyError, TypeError):
                excluded.append({'endpoint': model.get('endpoint_id'), 'reason': 'Additional inputs or unsupported image response contract'})
        if not page['has_more']:
            break
        cursor = page.get('next_cursor')
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ValueError('Incomplete image catalog pagination')
        seen.add(cursor)
    else:
        raise ValueError('Image catalog exceeds supported discovery bound')
    # Rates are optional. Catalog eligibility never depends on price availability.
    prices = {}
    for offset in range(0, len(models), 50):
        try:
            response = fal.request('GET', PRICES, params={'endpoint_id': ','.join(item['endpoint'] for item in models[offset:offset + 50])})
            prices.update(price_options(response, checked))
        except Exception:
            pass
    for item in models:
        item['checkedAt'] = checked
        if item['endpoint'] in prices:
            item['priceEstimate'] = prices[item['endpoint']]
    catalog = {'schemaVersion': 1, 'complete': True, 'checkedAt': checked, 'source': URL, 'models': models, 'excluded': excluded}
    try:
        video_prices = price_options(fal.request('GET', PRICES, params={'endpoint_id': ','.join(VIDEO_PRICE_ENDPOINTS)}), checked)
        if video_prices:
            store.put('model-pricing', VIDEO_PRICE_ID, {'schemaVersion': 1, 'prices': video_prices, 'checkedAt': checked})
    except Exception:
        pass  # Price discovery must not change an executable model or erase prior evidence.
    store.put('model-catalog', CATALOG_ID, catalog)
    store.put('model-catalog-health', CATALOG_ID, {'status': 'READY', 'updatedAt': checked, 'modelCount': len(models)})
    return catalog


def available(store):
    catalog = store.get('model-catalog', CATALOG_ID) or {}
    if catalog.get('schemaVersion') != 1 or catalog.get('complete') is not True:
        return []
    return catalog.get('models', [])


def selected(store, endpoint):
    return next((deepcopy(item) for item in available(store) if item['endpoint'] == endpoint), None)
