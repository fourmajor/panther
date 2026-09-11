import importlib
import json
import time

import pytest

from test_model_jobs import broker, request, unpack  # noqa: F401


@pytest.fixture
def movie(broker, monkeypatch):  # noqa: F811
    monkeypatch.setenv('MOVIE_REVIEW_TABLE', 'test-jobs')
    monkeypatch.delitem(__import__('sys').modules, 'movie_review', raising=False)
    return importlib.import_module('movie_review')


def setup(movie):
    key = 'games/test-game/assets/movie-plan/original/plan.json'
    frame = 'games/test-game/assets/frame/original/frame.png'
    plan = dict(schemaVersion=1, entityType='MovieReviewPlan', gameId='test-game',
                projectId='test-film', revisionId='v1', sessionId='session-one', title='The Gate',
                summary='A synthetic scene.', screenplay='INT. GATE — NIGHT\nThe gate opens.',
                sourceKeys=[frame], characters=[], budget=dict(capUsd='10.00', currency='USD',
                pricingCheckedAt=int(time.time())), shots=[dict(id='shot-one', title='The gate',
                description='A gate opens.', camera='Wide', continuity='Closed to open',
                model='Test model', modelReason='Synthetic fixture', durationSeconds=8,
                characterIds=[], referenceKeys=[frame], frameKey=frame, costUsd='1.00', warnings=[])])
    movie.media.s3.put_object(Bucket=movie.media.BUCKET_NAME, Key=frame, Body=b'image', ContentType='image/png')
    store(movie, key, plan)
    return key, plan


def store(movie, key, plan):
    movie.media.s3.put_object(Bucket=movie.media.BUCKET_NAME, Key=key, Body=json.dumps(plan).encode(),
                            Metadata={'kind': 'movie-review-plan'}, ContentType='application/json')


def test_durable_revision_approval_and_conflicts(movie):
    key, plan = setup(movie)
    params = dict(gameId='test-game', key=key)
    loaded = unpack(request(movie, 'GET /movie-review', query=params))
    assert loaded['review'] is None and loaded['readiness']['ready']
    body = dict(**params, sha256=loaded['sha256'], expectedReviewId=None, action='approved',
                reviewedShotIds=['shot-one'], capUsd='10.00')
    saved = unpack(request(movie, 'POST /movie-review', body))
    assert saved['generationStarted'] is False
    assert unpack(request(movie, 'GET /movie-review', query=params))['review']['id'] == saved['review']['id']
    assert request(movie, 'POST /movie-review', body)['statusCode'] == 409
    body.update(action='changes-requested', expectedReviewId=saved['review']['id'],
                comments=[dict(shotId='shot-one', text='Change the camera.')])
    assert unpack(request(movie, 'POST /movie-review', body))['review']['action'] == 'changes-requested'
    # Changed content cannot inherit the old decision, even at the same test key.
    plan['screenplay'] += ' A different ending.'
    store(movie, key, plan)
    assert unpack(request(movie, 'GET /movie-review', query=params))['review'] is None
    assert request(movie, 'POST /movie-review', body)['statusCode'] == 409


@pytest.mark.parametrize('change', ['unquoted', 'no-frame', 'stale', 'over-budget', 'warning'])
def test_blockers_cannot_be_overridden(movie, change):
    key, plan = setup(movie)
    if change == 'unquoted':
        plan['shots'][0]['costUsd'] = None
    if change == 'no-frame':
        plan['shots'][0]['frameKey'] = None
    if change == 'stale':
        plan['budget']['pricingCheckedAt'] = 1
    if change == 'over-budget':
        plan['shots'][0]['costUsd'] = '11.00'
    if change == 'warning':
        plan['shots'][0]['warnings'] = [dict(severity='blocker', message='Uncertain speaker')]
    store(movie, key, plan)
    data = unpack(request(movie, 'GET /movie-review', query=dict(gameId='test-game', key=key)))
    assert not data['readiness']['ready']
    assert request(movie, 'POST /movie-review', dict(gameId='test-game', key=key,
        sha256=data['sha256'], expectedReviewId=None, action='approved', capUsd='10.00',
        reviewedShotIds=['shot-one']))['statusCode'] == 409


def test_auth_scope_and_feedback_validation(movie):
    key, plan = setup(movie)
    params = dict(gameId='test-game', key=key)
    assert request(movie, 'GET /movie-review', query=params, actor='')['statusCode'] == 403
    assert request(movie, 'GET /movie-review', query=dict(gameId='other-game', key=key))['statusCode'] == 400
    data = unpack(request(movie, 'GET /movie-review', query=params, username='example-editor'))
    assert not data['canApprove']
    body = dict(**params, sha256=data['sha256'], expectedReviewId=None, action='approved',
                capUsd='10.00', reviewedShotIds=['shot-one'])
    assert request(movie, 'POST /movie-review', body, username='example-editor')['statusCode'] == 403
    body.update(action='changes-requested', comments=[dict(shotId='missing', text='Change')])
    assert request(movie, 'POST /movie-review', body)['statusCode'] == 400
    plan['shots'][0]['frameKey'] = 'games/other-game/assets/x/original/a.png'
    store(movie, key, plan)
    assert request(movie, 'GET /movie-review', query=params)['statusCode'] == 400
