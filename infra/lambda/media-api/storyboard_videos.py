"""Scene-owned, revision-pinned storyboard footage and exact cut selections."""
import copy
import math


def shot(scene, identity):
    board = scene.get('storyboard')
    found = next((item for item in (board or {}).get('shots', []) if item['shotId'] == identity), None)
    if not found:
        raise ValueError('Choose a shot from the current storyboard')
    return board, found


def select(scene, selection, metadata, historical):
    if not isinstance(selection, dict) or set(selection) != {'storyboardRevision', 'shotId', 'assetKey', 'startSeconds'}:
        raise ValueError('Invalid storyboard take selection')
    board, item = shot(scene, selection['shotId'])
    if selection['storyboardRevision'] != board['revision']:
        raise ValueError('The storyboard changed. Select a take for its current revision')
    existing = copy.deepcopy(scene.get('shotTakes', {}))
    if selection['assetKey'] is None:
        existing.pop(item['shotId'], None)
        return existing
    extra = metadata.get('extra', {})
    ref = extra.get('sceneRef', {})
    if not metadata.get('contentType', '').startswith('video/') or extra.get('relationshipRole') != 'finished' or ref.get('episodeId') != scene['episodeId'] or ref.get('sceneId') != scene['id']:
        raise ValueError('Choose a finished take from this scene')
    pin = extra.get('storyboardShotRef')
    expected = {'revision': board['revision'], 'shotId': item['shotId']}
    if pin != expected:
        # Explicitly selecting an older whole-scene take is safe only when its
        # immutable source scene had exactly this one storyboard shot.
        previous = (historical or {}).get('storyboard', {})
        if pin or previous.get('revision') != board['revision'] or len(previous.get('shots', [])) != 1 or previous['shots'][0]['shotId'] != item['shotId']:
            raise ValueError('This take does not belong to the selected storyboard shot')
    start = selection['startSeconds']
    duration = item['durationSeconds']
    try:
        available = float(extra['mediaProbe']['format']['duration'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('This take has no verified video duration') from None
    if type(start) not in (int, float) or not math.isfinite(start) or start < 0 or not math.isfinite(available) or start + duration > available + .001:
        raise ValueError('The take is shorter than this cut. Choose more footage or shorten the storyboard shot')
    existing[item['shotId']] = {**selection, 'durationSeconds': duration, 'generationSceneRevision': ref['revision']}
    return existing


def composition(scene):
    board = scene.get('storyboard') or {}
    takes = scene.get('shotTakes', {})
    clips, missing = [], []
    for item in board.get('shots', []):
        take = takes.get(item['shotId'])
        if not take or take['storyboardRevision'] != board['revision'] or take['durationSeconds'] != item['durationSeconds']:
            missing.append(item['shotId'])
        else:
            clips.append(copy.deepcopy(take))
    return {'schemaVersion': 1, 'entityType': 'SceneComposition', 'gameId': scene['gameId'], 'sceneRef': {'episodeId': scene['episodeId'], 'sceneId': scene['id'], 'revision': scene.get('revision')}, 'storyboardRevision': board.get('revision'), 'ready': bool(board.get('shots')) and not missing, 'missingShotIds': missing, 'clips': clips}


def validate_output(scene, metadata):
    """Only an assembly of every current selected cut can complete a planned scene."""
    if not scene.get('storyboard'):
        raise ValueError('Create a storyboard and select its shot takes before using scene footage')
    current = composition(scene)
    extra = metadata.get('extra') if isinstance(metadata, dict) else None
    if not isinstance(extra, dict):
        raise ValueError('Choose a finished scene assembly')
    assembled = extra.get('sceneAssembly') or {}
    if not isinstance(assembled, dict):
        raise ValueError('Choose a finished scene assembly')
    if not current['ready'] or assembled.get('storyboardRevision') != current['storyboardRevision'] or assembled.get('clips') != current['clips']:
        raise ValueError('Select every current storyboard take and assemble the scene first')
