import json
import importlib
import sys

from test_media_api import load_media_api


def setup(monkeypatch):
    media, s3 = load_media_api(monkeypatch)
    sys.modules.pop('image_delivery', None)
    module = importlib.import_module('image_delivery')
    return module, media, s3


def event(keys, user='example-operator', game='example-game'):
    return {'body':json.dumps({'gameId':game,'keys':keys}), 'requestContext':{'authorizer':{'jwt':{'claims':{'sub':'example-sub','cognito:username':user}}}}}


def test_batch_signs_unique_images_without_reading_payloads(monkeypatch):
    module, media, s3 = setup(monkeypatch)
    keys=[f'games/example-game/assets/image-{i}/original/frame.png' for i in range(30)]
    reads=[]
    def resolve(key):
        reads.append(key)
        return 'games/example-game/content/images/'+key.split('/')[3]+'/frame.png'
    monkeypatch.setattr(s3,'resolve',resolve,raising=False)
    def no_payload(**kwargs):
        raise AssertionError('No S3 payload reads permitted')
    monkeypatch.setattr(s3,'head_object',no_payload)
    monkeypatch.setattr(s3,'get_object',no_payload)
    result=module.handle(event(keys+[keys[0]]),media)
    assert result['statusCode']==200
    body=json.loads(result['body'])
    assert set(body['images'])==set(keys) and body['expiresIn']==300
    assert sorted(reads)==sorted(keys)
    assert len(s3.signed_requests)==30


def test_batch_rejects_foreign_unsafe_oversized_or_unauthorized_requests(monkeypatch):
    module, media, s3=setup(monkeypatch)
    key='games/example-game/assets/frame/original/frame.png'
    for keys in [[],[key]*61,['games/other/assets/frame/original/frame.png'],['games/example-game/content/private/frame.png'],[key.replace('png','json')],[None]]:
        assert module.handle(event(keys),media)['statusCode']==400
    assert module.handle(event([key],user='example-member'),media)['statusCode']==403
    assert not s3.signed_requests


def test_one_missing_locator_does_not_hide_other_images(monkeypatch):
    module, media, s3=setup(monkeypatch)
    from test_media_api import FakeClientError
    keys=['games/example-game/assets/good/original/frame.png','games/example-game/assets/missing/original/frame.png']
    def resolve(key):
        if '/missing/' in key:
            raise FakeClientError('NoSuchKey')
        return 'games/example-game/content/images/good/frame.png'
    monkeypatch.setattr(s3,'resolve',resolve,raising=False)
    images=json.loads(module.handle(event(keys),media)['body'])['images']
    assert images[keys[0]]['url']
    assert images[keys[1]]=={'error':'Image reference not found','retryable':False}
