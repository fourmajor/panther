"""Character assets retain associations; official portraits are an explicit atomic action."""
import base64
import hashlib
import json
from types import SimpleNamespace

import boto3
import pytest
from test_asset_generation import generation, library, novel, editorial, broker, call, request, unpack, image_bytes  # noqa: F401
from test_dev_image_worker import worker, Images


@pytest.mark.parametrize('kind', ['image', 'portrait'])
def test_generic_character_image_preserves_official_portrait(tmp_path, kind):
    store = worker.Store(tmp_path / 'private.sqlite')
    store.put('game', 'fictional', {'id': 'fictional', 'name': 'Imaginary', 'description': '', 'visualStyle': 'watercolor'})
    store.create_character({'gameId': 'fictional', 'id': 'guide', 'name': 'Guide'})
    before = store.get('character', 'fictional:guide')
    body = {'gameId': 'fictional', 'type': kind, 'characterId': 'guide', 'name': 'Camp', 'prompt': 'A camp illustration', 'operationId': 'c' * 32}
    job = store.submit_asset_generation(body)
    assert worker.process(store, job['jobId'], worker.private_root(tmp_path / 'work'), SimpleNamespace(images=Images()), 'gpt-image-1')
    published = store.get('asset-generation', job['jobId'])
    meta, _ = store.object(published['assetKey'])
    assert meta['characterIds'] == ['guide']
    assert store.get('character', 'fictional:guide') == before
    if kind != 'portrait':
        with pytest.raises(ValueError, match='official portrait'):
            store.submit_asset_generation({**body, 'operationId': 'd' * 32, 'selectAsPortrait': True})


@pytest.mark.parametrize('select', [True, False])
@pytest.mark.parametrize('race', [True, False])
def test_hosted_official_selection_and_history_are_atomic(generation, select, race):  # noqa: F811
    catalog = boto3.resource('dynamodb').Table('narrative-games')
    old = {'pk': 'GAME#test-game', 'sk': 'CHARACTER#hero', 'gameId': 'test-game', 'id': 'hero', 'name': 'Guide', 'detailsRevision': 'a' * 32, 'detailsJson': json.dumps({'thumbnailAssetKey': None, 'backstory': 'Fictional scout'})}
    catalog.put_item(Item=old)
    import asset_archive
    previous_key = 'games/test-game/assets/old-reference/original/image.png'
    asset_archive.db().put_item(Item={'pk': 'asset-references-v1#test-game', 'sk': 'character:hero', 'keys': [previous_key], 'schemaVersion': 1})
    job = unpack(call(generation, body=request(type='portrait', characterId='hero', selectAsPortrait=select)))
    claimed = unpack(call(generation, 'POST /asset-generation/claim', username='example-worker'))
    if race:
        old = {**old, 'detailsRevision': 'b' * 32, 'name': 'Edited guide'}
        catalog.put_item(Item=old)
    key = f"games/test-game/assets/generated-{job['jobId'][:40]}/original/image.png"
    checksum = base64.b64encode(hashlib.sha256(image_bytes()).digest()).decode()
    metadata = {'title': 'Scout', 'characterIds': ['hero'], 'extra': {'assetGenerationJobId': job['jobId'], 'assetType': 'portrait', 'sha256': checksum, 'relationshipRole': 'finished', 'generation': {'provider': 'OpenAI', 'model': 'gpt-image-1', 'cost': {'status': 'unknown'}}}}
    generation.media.s3.put_object(Bucket=generation.media.BUCKET_NAME, Key=key, Body=image_bytes(), ContentType='image/png', ChecksumSHA256=checksum, ChecksumAlgorithm='SHA256', Metadata={'panther': base64.b64encode(json.dumps(metadata).encode()).decode()})
    completed = unpack(call(generation, 'POST /asset-generation/complete', body={'jobId': job['jobId'], 'lease': claimed['lease'], 'assetKey': key}, username='example-worker'))
    revised = catalog.get_item(Key={'pk': old['pk'], 'sk': old['sk']})['Item']
    assert completed['status'] == 'PUBLISHED'
    if select and not race:
        assert completed['portraitAssigned'] is True
        references = asset_archive.db().get_item(Key={'pk': 'asset-references-v1#test-game', 'sk': 'character:hero'})['Item']
        assert set(references['keys']) == {previous_key, key}
        assert json.loads(revised['detailsJson'])['thumbnailAssetKey'] == key
        history = catalog.get_item(Key={'pk': 'CHARACTER_DETAILS_HISTORY#test-game#hero', 'sk': revised['detailsRevision']})['Item']
        assert history['previousRevision'] == old['detailsRevision'] and history['previousDetailsJson'] == old['detailsJson']
    else:
        assert revised == old
        if select:
            assert completed['portraitAssigned'] is False
        else:
            assert 'portraitAssigned' not in completed


def test_character_job_page_filters_before_pagination(tmp_path):
    store = worker.Store(tmp_path / 'private.sqlite')
    store.put('game', 'fictional', {'id': 'fictional', 'name': 'Imaginary', 'description': '', 'visualStyle': 'watercolor'})
    store.create_character({'gameId': 'fictional', 'id': 'guide', 'name': 'Guide'})
    for index in range(30):
        store.put('asset-generation', str(index), {'jobId': str(index), 'gameId': 'fictional', 'type': 'portrait', 'characterId': 'guide' if index < 2 else 'other', 'status': 'PUBLISHED'}, 'fictional')
    page = store.asset_generation_page('fictional', character='guide')
    assert len(page['jobs']) == 2 and page['cursor'] is None
    with pytest.raises(ValueError, match='same-game character'):
        store.asset_generation_page('fictional', character='missing')
