import importlib
import json
import uuid

from test_novel_library import library  # noqa: F401
from test_novel import novel, completed  # noqa: F401
from test_editorial import editorial  # noqa: F401
from test_model_jobs import broker  # noqa: F401


def call(library, path='tags', body=None, user='example-operator', **query):  # noqa: F811
    return importlib.import_module('user_metadata').handle({
        'routeKey': ('POST ' if body is not None else 'GET ') + '/' + path,
        'body': json.dumps(body) if body is not None else None,
        'queryStringParameters': {'gameId': 'test-game', **query},
        'requestContext': {'authorizer': {'jwt': {'claims': {'sub': 'fictional-operator', 'cognito:username': user}}}},
    }, library[1].jobs.media)


def test_tags_require_verified_catalog_and_preserve_canonical_case(library):  # noqa: F811
    assert call(library)['statusCode'] == 503
    table = library[1].browse_index.table()
    table.put_item(Item={'pk': 'tags-v1#catalog', 'sk': 'ready'})
    first = call(library, body={'gameId': 'test-game', 'name': 'Campaign favorite'})
    assert first['statusCode'] == 200
    second = call(library, body={'gameId': 'test-game', 'name': 'campaign FAVORITE'})
    assert json.loads(second['body']) == {'tag': 'Campaign favorite', 'tags': ['Campaign favorite']}
    assert call(library, body={'gameId': 'missing-game', 'name': 'One'})['statusCode'] == 404
    assert call(library, body=[])['statusCode'] == 400
    assert call(library, user='unconfigured')['statusCode'] == 403


def test_asset_projection_populates_tag_vocabulary_atomically(library):  # noqa: F811
    module = importlib.import_module('user_metadata')
    table = library[1].browse_index.table()
    table.put_item(Item={'pk': 'tags-v1#catalog', 'sk': 'ready'})
    from boto3.dynamodb.types import TypeSerializer
    import boto3
    def encode(data):
        return {key: TypeSerializer().serialize(value) for key, value in data.items()}
    asset = {'metadata': {'tags': ['canonical', 'Epic battle']}}
    boto3.client('dynamodb').transact_write_items(TransactItems=module.tag_operations(table.name, 'test-game', asset, encode))
    assert json.loads(call(library)['body'])['tags'] == ['canonical', 'Epic battle']
    asset['metadata']['tags'] = ['CANONICAL']
    boto3.client('dynamodb').transact_write_items(TransactItems=module.tag_operations(table.name, 'test-game', asset, encode))
    assert json.loads(call(library)['body'])['tags'][0] == 'canonical'


def test_novel_reviews_are_guarded_idempotent_and_separate_from_chapters(library):  # noqa: F811
    job, key = completed(library[1])
    original = library[1].jobs.media.s3.get_object(Bucket=library[1].jobs.media.BUCKET_NAME, Key=key)['Body'].read()
    body = {'gameId': 'test-game', 'chapterId': job['jobId'], 'status': 'approved', 'comment': '', 'operationId': uuid.uuid4().hex, 'expectedRevision': None}
    result = call(library, 'novel-review', body=body)
    assert result['statusCode'] == 200, result
    assert call(library, 'novel-review', body=body) == result
    review = json.loads(result['body'])['review']
    assert json.loads(call(library, 'novel-review', chapterId=job['jobId'])['body'])['review'] == review
    assert call(library, 'novel-review', body={**body, 'operationId': uuid.uuid4().hex})['statusCode'] == 409
    changed = call(library, 'novel-review', body={**body, 'operationId': uuid.uuid4().hex, 'expectedRevision': review['revision'], 'status': 'rejected', 'comment': 'Revise the ending'})
    assert changed['statusCode'] == 200
    assert call(library, 'novel-review', body={**body, 'status': 'rejected'})['statusCode'] == 409
    assert library[1].jobs.media.s3.get_object(Bucket=library[1].jobs.media.BUCKET_NAME, Key=key)['Body'].read() == original
    table = library[1].browse_index.table()
    from boto3.dynamodb.conditions import Key
    history = table.query(KeyConditionExpression=Key('pk').eq('novel-review-history#test-game#' + job['jobId']))['Items']
    assert len(history) == 2


def test_review_supports_authored_chapters_and_rejects_foreign_sources(library):  # noqa: F811
    table = library[1].browse_index.table()
    identity = 'a' * 64
    key = 'games/test-game/assets/authored-chapter-one/original/chapter.json'
    table.put_item(Item={'pk': 'novel-library#chapter#test-game', 'sk': identity, 'status': 'DONE', 'payload': json.dumps({'assetKey': key})})
    body = {'gameId': 'test-game', 'chapterId': identity, 'status': 'approved', 'comment': '', 'operationId': uuid.uuid4().hex, 'expectedRevision': None}
    assert call(library, 'novel-review', body=body)['statusCode'] == 200
    assert call(library, 'novel-review', chapterId='b' * 64)['statusCode'] == 404
    job, _ = completed(library[1])
    library[1].jobs.table.update_item(Key={'pk': 'RUNS', 'sk': job['jobId']}, UpdateExpression='SET gameId=:game', ExpressionAttributeValues={':game': 'foreign-game'})
    assert call(library, 'novel-review', chapterId=job['jobId'])['statusCode'] == 404


def test_review_cannot_commit_after_source_task_changes(library, monkeypatch):  # noqa: F811
    job, _ = completed(library[1])
    module = importlib.import_module('user_metadata')
    original = module.chapter_reference
    def changing_source(game, identity):
        reference = original(game, identity)
        library[1].jobs.table.update_item(Key={'pk': 'TASKS', 'sk': identity + ':novel-chapter'}, UpdateExpression='SET #status=:status', ExpressionAttributeNames={'#status': 'status'}, ExpressionAttributeValues={':status': 'FAILED'})
        return reference
    monkeypatch.setattr(module, 'chapter_reference', changing_source)
    body = {'gameId': 'test-game', 'chapterId': job['jobId'], 'status': 'approved', 'comment': '', 'operationId': uuid.uuid4().hex, 'expectedRevision': None}
    assert call(library, 'novel-review', body=body)['statusCode'] == 409
    assert not library[1].browse_index.table().get_item(Key={'pk': 'novel-review#test-game', 'sk': job['jobId']}).get('Item')


def test_tag_rename_delete_guarded_and_projection_preserves_sources(library):  # noqa: F811
    module = importlib.import_module('tag_management')
    table = library[1].browse_index.table()
    table.put_item(Item={'pk': 'tags-v1#catalog', 'sk': 'ready'})
    assert call(library, body={'gameId': 'test-game', 'name': 'Test'})['statusCode'] == 200
    body = {'gameId': 'test-game', 'action': 'rename', 'name': 'Test', 'newName': 'Adventure', 'operationId': uuid.uuid4().hex}
    result = call(library, 'tags/manage', body=body)
    assert result['statusCode'] == 200, result
    assert json.loads(result['body'])['tags'] == ['Adventure']
    assert call(library, 'tags/manage', body=body) == result
    assert call(library, 'tags/manage', body={**body, 'newName': 'Changed'})['statusCode'] == 409
    events = importlib.import_module('user_metadata').tag_events('test-game')
    asset = {'metadata': {'tags': ['Test']}, 'lastModified': '2020-01-01T00:00:00Z'}
    assert module.project(asset, events)['metadata']['tags'] == ['Adventure']
    assert asset['metadata']['tags'] == ['Test']
    deleted = {key: value for key, value in body.items() if key != 'newName'}
    deleted.update(action='delete', name='Adventure', operationId=uuid.uuid4().hex)
    assert json.loads(call(library, 'tags/manage', body=deleted)['body'])['tags'] == []
    events = importlib.import_module('user_metadata').tag_events('test-game')
    assert module.project(asset, events)['metadata']['tags'] == []
    assert call(library, 'tags/manage', body=deleted, user='unconfigured')['statusCode'] == 403
    assert call(library, body={'gameId': 'test-game', 'name': 'Adventure'})['statusCode'] == 200
    assert module.project(asset, events)['metadata']['tags'] == []
    assert module.project({'metadata': {'tags': ['Adventure']}, 'lastModified': events[-1]['at'] + 1}, events)['metadata']['tags'] == ['Adventure']


def test_tag_history_checks_item_bytes_before_transaction(library):  # noqa: F811
    import pytest
    module = importlib.import_module('user_metadata')
    table = library[1].browse_index.table()
    table.put_item(Item={'pk': 'tags-v1#catalog', 'sk': 'ready'})
    assert call(library, body={'gameId': 'test-game', 'name': 'Test'})['statusCode'] == 200
    events = [{'schemaVersion': 1, 'name': 'Earlier', 'action': 'delete', 'at': 1,
               'padding': 'x' * (350 * 1024 - 200)}]
    table.put_item(Item={'pk': 'tags-v1#policy#test-game', 'sk': 'current',
                        'revision': 'prior', 'payload': json.dumps(events)})
    body = {'gameId': 'test-game', 'action': 'rename', 'name': 'Test',
            'newName': '星' * 64, 'operationId': uuid.uuid4().hex}
    with pytest.raises(RuntimeError, match='compaction'):
        module.manage_tag(body, 'fictional-operator')
    assert json.loads(call(library)['body'])['tags'] == ['Test']
    assert module.tag_events('test-game') == events
