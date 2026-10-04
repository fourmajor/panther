"""Shot conditioning uses real immutable portraits, bounded modes and no off-cast images."""
import base64
import hashlib
import json
from io import BytesIO

import pytest
from PIL import Image
from dev_editorial_worker import Store
from dev_prompt_processor import scaled_image
from dev_video_conditioning import condition
from dev_video_worker import verified
from panther_journal.video import payload


def fixture(tmp_path, selected=('hero',), frame=False):
    store = Store(tmp_path / 'private.sqlite')
    characters = []
    for identity, color in [('hero', 'blue'), ('absent', 'red')]:
        buffer = BytesIO()
        Image.new('RGB', (2000, 1000), color).save(buffer, 'PNG')
        raw = buffer.getvalue()
        key = f'games/fictional/assets/{identity}/original/portrait.png'
        pin = {'key': key, 'size': len(raw), 'sha256': base64.b64encode(hashlib.sha256(raw).digest()).decode(), 'contentType': 'image/png'}
        with store.connect() as db:
            db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, 'fictional', json.dumps({'characterIds': [identity]}), raw, 'now'))
        characters.append({'id': identity, 'name': identity.title(), 'portraitPin': pin})
    job = {'gameId': 'fictional', 'videoPromptPolicy': 2, 'characterContext': characters,
           'promptComposition': {'schemaVersion': 2, 'visibleCharacterIds': list(selected)}}
    if frame:
        job['storyboardFramePin'] = characters[0]['portraitPin']
    return store, job


@pytest.mark.parametrize('model,endpoint,field', [
    ('h3-max', 'minimax/h3-max/reference-to-video', 'reference_image_urls'),
    ('veo-3.1-fast', 'fal-ai/veo3.1/fast/reference-to-video', 'image_urls'),
])
def test_only_visible_portraits_reach_reference_provider(tmp_path, model, endpoint, field):
    store, job = fixture(tmp_path)
    result, body, refs = condition(store, job, model, payload({'model': model, 'prompt': 'Hero crosses the bridge.'}), verified)
    assert result == endpoint and len(body[field]) == 1
    assert [ref['characterId'] for ref in refs] == ['hero']
    image = Image.open(BytesIO(base64.b64decode(body[field][0].split(',')[1])))
    assert image.size == (1536, 768)  # No stretched/square-cropped portrait.
    assert image.getpixel((100, 100))[2] > 240
    assert 'Absent' not in body['prompt'] and 'Hero' in body['prompt']
    original = store.object(job['characterContext'][0]['portraitPin']['key'])[1]
    assert Image.open(BytesIO(original)).size == (2000, 1000)


def test_missing_identity_and_changed_bytes_fail_closed(tmp_path):
    store, job = fixture(tmp_path)
    job['characterContext'][0]['portraitPin']['sha256'] = 'changed'
    with pytest.raises(ValueError, match='changed'):
        condition(store, job, 'h3-max', {'prompt': 'Example'}, verified)
    job['characterContext'][0].pop('portraitPin')
    with pytest.raises(ValueError, match='official portrait'):
        condition(store, job, 'h3-max', {'prompt': 'Example'}, verified)


def test_kling_requires_real_scene_frame_not_portrait_collage(tmp_path):
    store, job = fixture(tmp_path)
    with pytest.raises(ValueError, match='starting frame'):
        condition(store, job, 'kling-3-pro', {'prompt': 'Example'}, verified)
    job['storyboardFramePin'] = job['characterContext'][0]['portraitPin']
    endpoint, body, refs = condition(store, job, 'kling-3-pro-image', {'prompt': 'Example'}, verified)
    assert endpoint.endswith('/image-to-video')
    assert len(body['elements']) == 1 and '@Element1 is Hero' in body['prompt']
    assert body['elements'][0]['frontal_image_url'].startswith('data:image/jpeg;base64,')
    assert len(refs) == 1


def test_landscape_does_not_switch_models_or_send_party(tmp_path):
    store, job = fixture(tmp_path, selected=())
    endpoint, body, refs = condition(store, job, 'veo-3.1-fast', {'prompt': 'Landscape'}, verified)
    assert endpoint == 'fal-ai/veo3.1/fast' and body == {'prompt': 'Landscape'} and refs == []


def test_no_silent_identity_drop_to_fit_reference_limit(tmp_path):
    store, job = fixture(tmp_path)
    job['characterContext'] = [{**job['characterContext'][0], 'id': str(i)} for i in range(4)]
    job['promptComposition']['visibleCharacterIds'] = [str(i) for i in range(4)]
    with pytest.raises(ValueError, match='three identity'):
        condition(store, job, 'veo-3.1-fast', {'prompt': 'Example'}, verified)


def test_malformed_image_cannot_be_provider_reference():
    with pytest.raises(Exception):
        scaled_image(b'not image bytes')
