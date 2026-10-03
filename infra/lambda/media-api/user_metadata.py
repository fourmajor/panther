"""Scoped user tag vocabulary and manuscript review metadata; no content or job writes."""
import base64
import hashlib
import json
import os
import re
import time
import uuid

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from access_policy import authorized
import browse_index


def tag_key(game, name):
    return {'pk': f'tags-v1#{game}', 'sk': hashlib.sha256(name.casefold().encode()).hexdigest()}


def tag_names(asset):
    values = asset.get('metadata', {}).get('tags', [])
    if not isinstance(values, list) or len(values) > 20 or any(not isinstance(name, str) or not 1 <= len(name) <= 96 or any(ord(c) < 32 for c in name) for name in values):
        raise ValueError('Invalid asset tags')
    return list({name.casefold(): name for name in values}.values())


def tag_operations(db_name, game, asset, encode):
    return [{'Update': {'TableName': db_name, 'Key': encode(tag_key(game, name)),
        'UpdateExpression': 'SET #name = if_not_exists(#name, :name), #v = :v',
        'ExpressionAttributeNames': {'#name': 'name', '#v': 'schemaVersion'},
        'ExpressionAttributeValues': encode({':name': name, ':v': 1})}} for name in tag_names(asset)]


def ready():
    if not browse_index.table().get_item(Key={'pk': 'tags-v1#catalog', 'sk': 'ready'}, ConsistentRead=True).get('Item'):
        raise browse_index.IndexNotReady('Tag catalog migration is incomplete; rebuild and verify every game before activation.')


def tags(game):
    ready()
    items, cursor = [], None
    for _ in range(11):
        args = {'KeyConditionExpression': Key('pk').eq(f'tags-v1#{game}'), 'ConsistentRead': True, 'Limit': 100}
        if cursor:
            args['ExclusiveStartKey'] = cursor
        result = browse_index.table().query(**args)
        items.extend(result.get('Items', []))
        cursor = result.get('LastEvaluatedKey')
        if len(items) > 1000:
            raise RuntimeError('Tag vocabulary exceeds the supported page size; pagination is required')
        if not cursor:
            return {'tags': sorted((item['name'] for item in items), key=str.casefold)}
    raise RuntimeError('Tag vocabulary read is incomplete; retry')


def chapter_reference(game, identity):
    table = browse_index.table()
    authored = table.get_item(Key={'pk': f'novel-library#chapter#{game}', 'sk': identity}, ConsistentRead=True).get('Item')
    if authored and authored.get('status') == 'DONE':
        document = json.loads(authored['payload'])
        if not document['assetKey'].startswith(f'games/{game}/assets/'):
            raise ValueError('Chapter belongs to another game')
        return {'key': document['assetKey'], 'authorship': 'human'}
    db = boto3.resource('dynamodb').Table(os.environ['EDITORIAL_TABLE'])
    job = db.get_item(Key={'pk': 'RUNS', 'sk': identity}, ConsistentRead=True).get('Item')
    task = db.get_item(Key={'pk': 'TASKS', 'sk': identity + ':novel-chapter'}, ConsistentRead=True).get('Item')
    if not job or job.get('gameId') != game or not task or task.get('status') != 'DONE':
        raise LookupError('Chapter not found')
    ref = task['output']
    if not ref['key'].startswith(f'games/{game}/assets/'):
        raise ValueError('Chapter belongs to another game')
    return {**ref, "size": int(ref["size"])}


def save_review(body, actor):
    fields = {'gameId', 'chapterId', 'status', 'comment', 'operationId', 'expectedRevision'}
    if not isinstance(body, dict) or set(body) != fields:
        raise ValueError('Expected a complete guarded review')
    game, identity, operation = body['gameId'], body['chapterId'], body['operationId']
    if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{64}', identity) or not isinstance(operation, str) or not re.fullmatch(r'[a-f0-9]{32}', operation):
        raise ValueError('Invalid review identity')
    if body['status'] not in {'approved', 'rejected'} or not isinstance(body['comment'], str) or len(body['comment']) > 4000 or any(ord(c) < 32 and c not in '\n\t' for c in body['comment']):
        raise ValueError('Choose Approved or Rejected and a comment of up to 4000 characters')
    expected = body['expectedRevision']
    if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{32}', expected)):
        raise ValueError('Invalid review revision')
    reference = chapter_reference(game, identity)
    table = browse_index.table()
    op_key = {'pk': f'novel-review-ops#{game}', 'sk': operation}
    fingerprint = hashlib.sha256(json.dumps({'body': body, 'actor': actor}, sort_keys=True).encode()).hexdigest()
    previous_op = table.get_item(Key=op_key, ConsistentRead=True).get('Item')
    if previous_op:
        if previous_op['fingerprint'] != fingerprint:
            raise FileExistsError('Operation reused with different content')
        return json.loads(previous_op['response'])
    key = {'pk': f'novel-review#{game}', 'sk': identity}
    previous_row = table.get_item(Key=key, ConsistentRead=True).get('Item')
    previous = json.loads(previous_row['payload']) if previous_row else None
    if expected != (previous['revision'] if previous else None):
        raise FileExistsError('This review changed. Reopen it before saving')
    review = {'status': body['status'], 'comment': body['comment'].strip() if body['status'] == 'rejected' else '', 'revision': uuid.uuid4().hex,
        'chapterId': identity, 'gameId': game, 'updatedAt': int(time.time())}
    response = {'review': review}
    serializer = TypeSerializer()
    def encode(value):
        return {key: serializer.serialize(item) for key, item in value.items()}
    change = {'TableName': table.name, 'Item': encode({**key, 'revision': review['revision'], 'payload': json.dumps(review)}),
              'ConditionExpression': 'revision = :previous' if previous else 'attribute_not_exists(pk)'}
    if previous:
        change['ExpressionAttributeValues'] = encode({':previous': expected})
    authored = table.get_item(Key={'pk': f'novel-library#chapter#{game}', 'sk': identity}, ConsistentRead=True).get('Item')
    if authored:
        guard = {'TableName': table.name, 'Key': encode({'pk': authored['pk'], 'sk': authored['sk']}),
            'ConditionExpression': '#status = :done AND payload = :payload',
            'ExpressionAttributeNames': {'#status': 'status'}, 'ExpressionAttributeValues': encode({':done': 'DONE', ':payload': authored['payload']})}
    else:
        guard = {'TableName': os.environ['EDITORIAL_TABLE'], 'Key': encode({'pk': 'TASKS', 'sk': identity + ':novel-chapter'}),
            'ConditionExpression': '#status = :done AND #output.#key = :key',
            'ExpressionAttributeNames': {'#status': 'status', '#output': 'output', '#key': 'key'}, 'ExpressionAttributeValues': encode({':done': 'DONE', ':key': reference['key']})}
    operations = [{'ConditionCheck': guard}, {'Put': change},
        {'Put': {'TableName': table.name, 'Item': encode({'pk': f'novel-review-history#{game}#{identity}', 'sk': review['revision'],
            'payload': json.dumps({'review': review, 'previous': previous, 'actor': actor, 'chapter': reference})}), 'ConditionExpression': 'attribute_not_exists(pk)'}},
        {'Put': {'TableName': table.name, 'Item': encode({**op_key, 'fingerprint': fingerprint, 'response': json.dumps(response)}), 'ConditionExpression': 'attribute_not_exists(pk)'}}]
    try:
        boto3.client('dynamodb').transact_write_items(TransactItems=operations)
    except ClientError as exc:
        if exc.response['Error']['Code'] != 'TransactionCanceledException':
            raise
        replay = table.get_item(Key=op_key, ConsistentRead=True).get('Item')
        if replay and replay['fingerprint'] == fingerprint:
            return json.loads(replay['response'])
        raise FileExistsError('This review changed. Reopen it before saving') from exc
    return response


def handler(event, _context):
    import index as media
    return handle(event, media)


def handle(event, media):
    route = event.get('routeKey', '')
    claims = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
    if not authorized(claims, 'MODEL_PUBLISHERS' if route.startswith('POST ') else 'CATALOG_READERS'):
        return media._response(403, {'error': 'Sign-in with the required capability is needed'})
    try:
        raw = event.get('body') or '{}'
        if event.get('isBase64Encoded'):
            raw = base64.b64decode(raw).decode()
        if len(raw) > 10000:
            raise ValueError('Metadata request is too large')
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError('Expected an object')
        query = event.get('queryStringParameters') or {}
        game = body.get('gameId') if route.startswith('POST ') else query.get('gameId')
        if not media._valid_slug(game) or len(game) > 96:
            raise ValueError('Choose a valid game')
        catalog = boto3.resource('dynamodb').Table(os.environ['CATALOG_TABLE'])
        if not catalog.get_item(Key={'pk': 'GAMES', 'sk': game}, ConsistentRead=True).get('Item'):
            raise LookupError('Game not found')
        if route == 'GET /tags':
            return media._response(200, tags(game))
        if route == 'POST /tags':
            if set(body) != {'gameId', 'name'} or not isinstance(body['name'], str) or not 1 <= len(body['name'].strip()) <= 64 or any(ord(c) < 32 for c in body['name']):
                raise ValueError('Enter a tag of up to 64 characters')
            ready()
            name = body['name'].strip()
            key = tag_key(game, name)
            try:
                browse_index.table().put_item(Item={**key, 'name': name, 'schemaVersion': 1, 'createdAt': int(time.time())}, ConditionExpression='attribute_not_exists(pk)')
            except ClientError as exc:
                if exc.response['Error']['Code'] != 'ConditionalCheckFailedException':
                    raise
                name = browse_index.table().get_item(Key=key, ConsistentRead=True)['Item']['name']
            return media._response(200, {'tag': name, **tags(game)})
        if route == 'POST /novel-review':
            return media._response(200, save_review(body, claims['sub']))
        if route == 'GET /novel-review':
            identity = query.get('chapterId', '')
            if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{64}', identity):
                raise ValueError('Invalid chapter identity')
            chapter_reference(game, identity)
            item = browse_index.table().get_item(Key={'pk': f'novel-review#{game}', 'sk': identity}, ConsistentRead=True).get('Item')
            return media._response(200, {'review': json.loads(item['payload']) if item else None})
        return media._response(404, {'error': 'Unknown metadata operation'})
    except FileExistsError as exc:
        return media._response(409, {'error': str(exc)})
    except LookupError as exc:
        return media._response(404, {'error': str(exc)})
    except (browse_index.IndexNotReady, RuntimeError) as exc:
        return media._response(503, {'error': str(exc)})
    except (ValueError, KeyError, TypeError) as exc:
        return media._response(400, {'error': str(exc)})
