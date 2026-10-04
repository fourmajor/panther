"""Validated, durable local assets requests for executable media processors."""
import base64
import hashlib
import json
import re
import time

IMAGE_MODELS = ('gpt-image-1', 'gpt-image-1.5', 'gpt-image-1-mini')
IMAGE_TYPES = {'image', 'map', 'blueprint', 'location', 'portrait'}
VIDEO_MODELS = ('veo-3.1-fast', 'h3-max', 'kling-3-pro', 'veo-3.1-fast-image', 'h3-max-image', 'kling-3-pro-image')


def options(store, game):
    settings = store.game(game)
    live = store.generation_capabilities()
    image_model = (store.get('service', 'images') or {}).get('model', 'gpt-image-1')
    text_model = (store.get('service', 'editorial') or {}).get('model', 'gpt-5-mini')
    styles = [{'id': item['id'], 'name': item['label']} for item in settings['visualStyles']]
    from dev_fal_image_catalog import available
    from panther_journal import cost_estimates, video
    image_models = []
    for model in dict.fromkeys((image_model, *IMAGE_MODELS)):
        estimate = cost_estimates.openai(model, request={'size': '1024x1024', 'quality': 'medium'})
        if estimate:
            estimate.update(unit='image', scope='Medium 1024×1024 image output; input tokens and title generation excluded')
        image_models.append({'id': model, 'name': model, 'provider': 'OpenAI', 'inputs': {}, 'priceEstimate': estimate})
    if (store.get('service', 'images') or {}).get('falAvailable') is True:
        image_models.extend({'id': item['endpoint'], 'name': item['name'], 'provider': 'fal', 'inputs': {}, 'priceEstimate': item.get('priceEstimate')} for item in available(store))
    types = [{'id': kind, 'name': kind.title(), 'available': live['images'], 'models': image_models, 'defaultModel': image_model, 'styles': styles, 'defaultStyle': settings['game'].get('visualStyle')} for kind in ('image', 'map', 'blueprint', 'location', 'portrait')]
    types.append({'id': 'video', 'name': 'Video', 'available': live['video'], 'models': [{'id': model, 'name': {'veo-3.1-fast': 'Veo 3.1 Fast', 'h3-max': 'MiniMax H3 Max', 'kling-3-pro': 'Kling 3 Pro'}[model.removesuffix('-image')] + (' · Image to video' if model.endswith('-image') else ''), 'inputs': {'requiresInitialImage': model.endswith('-image'), 'duration': 8, 'aspectRatio': '16:9'}, 'provider': 'fal', 'priceEstimate': cost_estimates.fal(model, video.payload({'model': model, 'prompt': 'Price estimate only'}))} for model in VIDEO_MODELS], 'defaultModel': VIDEO_MODELS[0], 'styles': styles, 'defaultStyle': settings['game'].get('visualStyle')})
    try:
        voices = store.narration_voices()['voices'] if live['narration'] else []
    except Exception:
        voices = []
    types.append({'id': 'narration', 'name': 'Speech', 'available': live['narration'] and bool(voices), 'models': [{'id': 'eleven_v3', 'name': 'ElevenLabs v3', 'provider': 'ElevenLabs', 'inputs': {'requiresVoice': True}, 'priceEstimate': {'schemaVersion': 1, 'status': 'estimated', 'credits': 1000, 'unit': 'characters', 'quantity': 1000, 'evidence': {'url': 'https://elevenlabs.io/docs/overview/models#eleven-v3'}, 'scope': '1,000 credits per 1,000 characters; USD depends on your subscription'}}], 'defaultModel': 'eleven_v3', 'styles': [], 'voices': voices})
    types.append({'id': 'text', 'name': 'Text', 'available': live['editorial'], 'models': [{'id': text_model, 'name': text_model, 'inputs': {}}], 'defaultModel': text_model, 'styles': []})
    return {'schemaVersion': 2, 'renameSupported': True, 'generationTypes': types}


def pin(store, game, key):
    if not isinstance(key, str) or not key.startswith(f'games/{game}/assets/'):
        raise ValueError('Choose an asset from this game')
    metadata, raw = store.object(key)
    with store.connect() as db:
        owner = db.execute('SELECT game FROM objects WHERE key=?', (key,)).fetchone()
    if owner != (game,):
        raise ValueError('Choose an asset from this game')
    return {'key': key, 'sha256': base64.b64encode(hashlib.sha256(raw).digest()).decode(), 'size': len(raw), 'contentType': metadata.get('contentType', 'application/octet-stream')}


def submit(store, body):
    required = {'gameId', 'type', 'prompt', 'operationId'}
    optional = {'name', 'model', 'style', 'inputs', 'characterId', 'selectAsPortrait'}
    if not isinstance(body, dict) or not required <= set(body) <= required | optional:
        raise ValueError('Choose a media type and describe what to generate')
    game, kind = body['gameId'], body['type']
    settings = store.game(game)
    if not isinstance(kind, str) or kind not in IMAGE_TYPES | {'video', 'narration', 'text'} or not isinstance(body['operationId'], str) or not re.fullmatch(r'[a-f0-9]{32}', body['operationId']):
        raise ValueError('Invalid generation type or operation')
    if not isinstance(body['prompt'], str) or not 1 <= len(body['prompt'].strip()) <= (5000 if kind == 'narration' else 4000):
        raise ValueError('Enter a prompt within the supported length')
    if 'name' in body and (not isinstance(body['name'], str) or not 1 <= len(body['name'].strip()) <= 160):
        raise ValueError('Invalid asset title')
    styles = {value['id'] for value in settings['visualStyles']}
    style = body.get('style', settings['game'].get('visualStyle'))
    if 'style' in body and (kind in {'narration', 'text'} or not isinstance(style, str) or style not in styles):
        raise ValueError('Choose a supported visual style')
    if 'selectAsPortrait' in body and (type(body['selectAsPortrait']) is not bool or kind != 'portrait' or not body.get('characterId')):
        raise ValueError('Only a character portrait can become the official portrait')
    character_record = None
    if body.get('characterId'):
        character_record = store.get('character', game + ':' + str(body['characterId']))
        if not character_record:
            raise ValueError('Choose an initialized character from this game')
    media = 'video' if kind == 'video' else 'audio' if kind == 'narration' else 'text' if kind == 'text' else 'image'
    default = 'veo-3.1-fast' if media == 'video' else 'eleven_v3' if media == 'audio' else (store.get('service', 'editorial' if media == 'text' else 'images') or {}).get('model', 'gpt-5-mini' if media == 'text' else 'gpt-image-1')
    model = body.get('model', default)
    from dev_fal_image_catalog import selected
    fal_contract = selected(store, model) if media == 'image' and isinstance(model, str) else None
    if not isinstance(model, str) or (not fal_contract and model not in (VIDEO_MODELS if media == 'video' else tuple(dict.fromkeys((default, *IMAGE_MODELS))) if media == 'image' else (default,))):
        raise ValueError('Choose an available model')
    inputs = body.get('inputs', {})
    if not isinstance(inputs, dict) or set(inputs) - ({'duration', 'aspectRatio', 'initialImageKey', 'sourceKeys', 'characterIds'} if media == 'video' else {'voiceId', 'direction'} if media == 'audio' else set()):
        raise ValueError('These inputs are not supported by the selected model')
    request = {**body, 'schemaVersion': 2}
    identity = hashlib.sha256(json.dumps({'gameId': game, 'operationId': body['operationId']}, sort_keys=True).encode()).hexdigest()
    existing = store.get('asset-generation', identity)
    if existing:
        if existing.get('request') != request:
            # Preserve exact old image requests submitted before the generic envelope.
            if 'request' in existing or any(existing.get(field) != value for field, value in body.items()):
                raise ValueError('Operation reused with a different generation request')
        return store.asset_generation_view(existing)
    job = {**body, 'schemaVersion': 2, 'request': request, 'mediaType': media, 'model': model, 'visualStyle': style if media in {'video', 'image'} else None, 'jobId': identity, 'status': 'QUEUED', 'message': None, 'createdAt': int(time.time()), 'assetKey': None, 'generationAuthorized': True, 'inputRefs': [], 'sourceKeys': []}
    if fal_contract:
        if (store.get('service', 'images') or {}).get('falAvailable') is not True:
            raise ValueError('fal image generation is unavailable')
        job.update(provider='fal', modelContract=fal_contract)
    if media == 'video':
        if inputs.get('duration', 8) != 8 or type(inputs.get('duration', 8)) is not int or inputs.get('aspectRatio', '16:9') != '16:9':
            raise ValueError('This video model supports eight seconds at 16:9')
        image = inputs.get('initialImageKey')
        if model.endswith('-image') != bool(image):
            raise ValueError('Choose an initial image for an image-to-video model only')
        if image:
            job['imagePin'] = pin(store, game, image)
            if job['imagePin']['contentType'] not in {'image/png', 'image/jpeg', 'image/webp'}:
                raise ValueError('Choose a PNG, JPEG or WebP initial image')
            from io import BytesIO
            from PIL import Image
            with Image.open(BytesIO(store.object(image)[1])) as frame:
                if abs(frame.width / frame.height - 16 / 9) > 0.02:
                    raise ValueError('Choose a 16:9 initial image for this video model')
                frame.verify()
            job['inputRefs'].append(job['imagePin'])
        keys, characters = inputs.get('sourceKeys', []), inputs.get('characterIds', [])
        if body.get('characterId') and isinstance(characters, list):
            characters = list(dict.fromkeys([body['characterId'], *characters]))
        if any(not isinstance(values, list) or len(values) > 20 or any(not isinstance(value, str) for value in values) or len(set(values)) != len(values) for values in (keys, characters)):
            raise ValueError('Choose valid sources and characters')
        for key in keys:
            store.transcript_summary_source(game, key)
            job['inputRefs'].append(pin(store, game, key))
        job.update(transcriptKeys=keys, characterIds=characters, characterContext=[])
        for character in characters:
            record = store.get('character', game + ':' + character)
            if not record:
                raise ValueError('Choose characters from this game')
            job['characterContext'].append({'id': character, 'name': record['name'], 'details': record.get('details', {}), 'revision': record['revision']})
            portrait = record.get('details', {}).get('thumbnailAssetKey')
            if portrait:
                job['inputRefs'].append(pin(store, game, portrait))
    elif media == 'audio':
        if inputs.get('voiceId') not in {voice['id'] for voice in store.narration_voices()['voices']}:
            raise ValueError('Choose an available stock voice')
        direction = inputs.get('direction', '')
        if not isinstance(direction, str) or len(direction) > 2000:
            raise ValueError('Keep performance direction under 2000 characters')
        job.update(text=body['prompt'], voiceId=inputs['voiceId'], direction=direction)
    elif kind == 'portrait':
        record = store.get('character', game + ':' + str(body.get('characterId')))
        if not record:
            raise ValueError('Choose an initialized character from this game')
        job['characterReference'] = {'characterId': record['characterId'], 'name': record['name'], 'revision': record['revision'], 'details': record['details']}
        if len(json.dumps(job['characterReference']).encode()) > 64000:
            raise ValueError('Character details exceed the portrait request limit')
    if character_record:
        job['characterIds'] = list(dict.fromkeys([body['characterId'], *job.get('characterIds', [])]))
        if media == 'image' and kind != 'portrait':
            job['characterReference'] = {'characterId': character_record['characterId'], 'name': character_record['name'], 'revision': character_record['revision'], 'details': character_record['details']}
    job['sourceKeys'] = list(dict.fromkeys(ref['key'] for ref in job['inputRefs']))
    with store.connect() as db:
        db.execute('INSERT OR IGNORE INTO records VALUES (?,?,?,?)', ('asset-generation', identity, game, json.dumps(job)))
    saved = store.get('asset-generation', identity)
    if saved['request'] != request:
        raise ValueError('Operation reused with a different generation request')
    return store.asset_generation_view(saved)
