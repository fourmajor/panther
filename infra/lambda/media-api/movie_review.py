"""Immutable-plan review only. No generation, workflow dispatch, or billing credentials."""
import hashlib
import json
import os
import re
import time
import uuid
from decimal import Decimal, InvalidOperation

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError
import index as media
from access_policy import authorized
from asset_library import valid_key


def money(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,5}(\.\d{1,4})?', value):
        raise ValueError('Invalid USD amount')
    return Decimal(value)


def validate(plan, game):
    if (plan.get('schemaVersion') != 1 or plan.get('entityType') != 'MovieReviewPlan'
            or plan.get('gameId') != game):
        raise ValueError('Invalid movie plan identity')
    for field in ('projectId', 'revisionId', 'sessionId'):
        if not media._valid_slug(plan.get(field)) or len(plan[field]) > 96:
            raise ValueError('Invalid movie plan identifier')
    for field in ('title', 'summary', 'screenplay'):
        if not isinstance(plan.get(field), str) or not 0 < len(plan[field]) <= 40000:
            raise ValueError('Missing or oversized movie plan text')
    sources = plan.get('sourceKeys')
    if not isinstance(sources, list) or len(sources) > 100 or not all(valid_key(media, game, k) for k in sources):
        raise ValueError('Invalid source assets')
    budget = plan['budget']
    cap = money(budget['capUsd'])
    if budget['currency'] != 'USD' or not 0 < cap <= 1000:
        raise ValueError('Invalid review budget')
    characters = plan.get('characters', [])
    if not isinstance(characters, list) or len(characters) > 30:
        raise ValueError('Invalid cast')
    ids = set()
    for character in characters:
        if not media._valid_slug(character.get('id')) or character['id'] in ids:
            raise ValueError('Invalid cast identity')
        ids.add(character['id'])
        if not isinstance(character.get('name'), str) or len(character['name']) > 150:
            raise ValueError('Invalid cast name')
        if character.get('portraitKey') and character['portraitKey'] not in sources:
            raise ValueError('Portrait must reference a source asset')
    shots = plan.get('shots')
    if not isinstance(shots, list) or not 1 <= len(shots) <= 20:
        raise ValueError('Movie plans require 1–20 shots')
    shot_ids, total, duration, blockers = set(), Decimal(0), 0, []
    for shot in shots:
        if not media._valid_slug(shot.get('id')) or shot['id'] in shot_ids:
            raise ValueError('Duplicate or invalid shot')
        shot_ids.add(shot['id'])
        for field in ('title', 'description', 'camera', 'continuity', 'model', 'modelReason'):
            if not isinstance(shot.get(field), str) or not 0 < len(shot[field]) <= 6000:
                raise ValueError('Missing shot details')
        seconds = shot['durationSeconds']
        if type(seconds) not in (float, int) or not 0 < seconds <= 30:
            raise ValueError('Invalid shot duration')
        duration += seconds
        if not isinstance(shot.get('characterIds'), list) or not set(shot['characterIds']) <= ids:
            raise ValueError('Shot cast must be explicit')
        if not isinstance(shot.get('referenceKeys'), list) or not set(shot['referenceKeys']) <= set(sources):
            raise ValueError('Invalid shot references')
        if shot.get('frameKey') and shot['frameKey'] not in sources:
            raise ValueError('Invalid starting frame')
        if not shot.get('frameKey'):
            blockers.append(f"{shot['id']}: starting composition has not been prepared")
        if shot.get('costUsd') is None:
            blockers.append(f"{shot['id']}: generation cost is not quoted")
        else:
            total += money(shot['costUsd'])
        warnings = shot.get('warnings', [])
        if not isinstance(warnings, list) or len(warnings) > 30:
            raise ValueError('Invalid shot warnings')
        for warning in warnings:
            if warning.get('severity') not in ('note', 'blocker') or not isinstance(warning.get('message'), str):
                raise ValueError('Invalid warning')
            if warning['severity'] == 'blocker':
                blockers.append(f"{shot['id']}: {warning['message']}")
    if duration > 300:
        raise ValueError('Movie exceeds review duration limit')
    if total > cap:
        blockers.append('Estimated generation cost exceeds the budget cap')
    quoted = budget.get('pricingCheckedAt')
    if type(quoted) is not int or not 0 <= time.time() - quoted <= 86400:
        blockers.append('Refresh pricing before approval (quotes must be less than 24 hours old)')
    if not sources:
        blockers.append('No source evidence is attached')
    return {'knownCostUsd': str(total), 'costComplete': all(s.get('costUsd') is not None for s in shots),
            'durationSeconds': duration, 'blockers': blockers, 'ready': not blockers}


def load(game, key):
    if not valid_key(media, game, key) or not key.endswith('.json'):
        raise ValueError('Invalid movie plan asset')
    head = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=key)
    if head.get('Metadata', {}).get('kind') != 'movie-review-plan' or not 0 < head['ContentLength'] <= 512000:
        raise ValueError('Not a supported movie review plan')
    with media.s3.get_object(Bucket=media.BUCKET_NAME, Key=key)['Body'] as body:
        raw = body.read(512001)
    if len(raw) > 512000:
        raise ValueError('Movie plan too large')
    plan = json.loads(raw)
    return plan, hashlib.sha256(raw).hexdigest(), validate(plan, game)


def handler(event, _context):
    claims = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
    if not authorized(claims, 'MODEL_PUBLISHERS'):
        return media._response(403, {'error': 'Publisher sign-in required'})
    try:
        if event.get('routeKey') not in ('GET /movie-review', 'POST /movie-review'):
            return media._response(404, {'error': 'Unknown operation'})
        post = event['routeKey'].startswith('POST')
        if post and len(event.get('body', '')) > 16000:
            raise ValueError('Review is too large')
        data = json.loads(event.get('body') or '{}') if post else event.get('queryStringParameters') or {}
        game, key = data.get('gameId'), data.get('key')
        if not media._valid_slug(game) or len(game) > 96:
            raise ValueError('Invalid game')
        plan, digest, readiness = load(game, key)
        db = boto3.resource('dynamodb').Table(os.environ['MOVIE_REVIEW_TABLE'])
        pk = f'{game}#{digest}'
        previous = db.get_item(Key={'pk': pk, 'sk': 'HEAD'}, ConsistentRead=True).get('Item')
        review = json.loads(previous['review']) if previous else None
        if not post:
            return media._response(200, dict(plan=plan, sha256=digest, readiness=readiness,
                review=review, canApprove=authorized(claims, 'MODEL_WORKERS')))
        if data.get('sha256') != digest or data.get('expectedReviewId') != (review or {}).get('id'):
            return media._response(409, {'error': 'Plan or review changed. Refresh before saving.'})
        action = data.get('action')
        if action not in ('changes-requested', 'approved'):
            raise ValueError('Invalid review action')
        if action == 'approved':
            if not authorized(claims, 'MODEL_WORKERS'):
                return media._response(403, {'error': 'Only an owner can approve the budget'})
            if (not readiness['ready'] or data.get('capUsd') != plan['budget']['capUsd']
                    or set(data.get('reviewedShotIds', [])) != {s['id'] for s in plan['shots']}):
                return media._response(409, {'error': 'Review all shots and resolve blockers before approval.'})
            for source in plan['sourceKeys']:
                asset_head = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=source)
                if source in {s['frameKey'] for s in plan['shots']} and not asset_head.get('ContentType', '').startswith('image/'):
                    raise ValueError('Starting frame is not an image')
        comments = data.get('comments', [])
        if not isinstance(comments, list) or len(comments) > 30:
            raise ValueError('Invalid review notes')
        for comment in comments:
            if (comment.get('shotId') not in [s['id'] for s in plan['shots']] + [None]
                    or not isinstance(comment.get('text'), str) or not 0 < len(comment['text'].strip()) <= 2000):
                raise ValueError('Invalid shot note')
        if action == 'changes-requested' and not comments:
            raise ValueError('Describe the requested changes')
        saved = dict(id=uuid.uuid4().hex, action=action, comments=comments,
                     createdAt=int(time.time()), actor=claims['sub'], planKey=key, planSha256=digest,
                     capUsd=plan['budget']['capUsd'], generationStarted=False)
        item = {'pk': pk, 'sk': 'HEAD', 'reviewId': saved['id'], 'review': json.dumps(saved)}
        serializer = TypeSerializer()
        def encode(value):
            return {k: serializer.serialize(v) for k, v in value.items()}
        put = dict(TableName=db.name, Item=encode(item),
                   ConditionExpression='reviewId = :old' if review else 'attribute_not_exists(pk)')
        if review:
            put['ExpressionAttributeValues'] = {':old': {'S': review['id']}}
        boto3.client('dynamodb').transact_write_items(TransactItems=[{'Put': put}, {'Put': {
            'TableName': db.name, 'Item': encode(dict(item, sk=f"REVIEW#{saved['id']}")),
            'ConditionExpression': 'attribute_not_exists(pk)'}}])
        return media._response(200, {'review': saved, 'generationStarted': False})
    except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation):
        return media._response(400, {'error': 'Invalid or incomplete movie plan/review'})
    except ClientError as exc:
        code = exc.response['Error']['Code']
        if code == 'TransactionCanceledException':
            return media._response(409, {'error': 'Another review was saved. Refresh before saving.'})
        if code in ('NoSuchKey', '404'):
            return media._response(404, {'error': 'Movie plan not found'})
        return media._response(503, {'error': 'Movie review service unavailable. Please retry.'})
