"""Small read-time projections over the existing catalog; original metadata stays intact."""
import re
import json


def options(query):
    character = query.get('characterId')
    if character and (len(character) > 96 or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', character)):
        raise ValueError('Invalid character filter')
    mime = query.get('mediaType')
    if mime not in (None, 'image', 'video', 'audio', 'text'):
        raise ValueError('Invalid media filter')
    view = query.get('view')
    if view not in (None, 'cards'):
        raise ValueError('Invalid asset view')
    try:
        limit = int(query.get('limit', 100))
    except (ValueError, TypeError):
        raise ValueError('Invalid asset page size') from None
    if not 1 <= limit <= 100:
        raise ValueError('Asset page size must be 1–100')
    return {'characterId': character, 'mediaType': mime, 'view': view, 'limit': limit}


def matches(asset, selected):
    return (not selected['characterId'] or selected['characterId'] in asset.get('metadata', {}).get('characterIds', [])) and (
        not selected['mediaType'] or asset.get('contentType', '').startswith(selected['mediaType'] + '/'))


def cover_key(asset):
    """Only explicit same-game images qualify; a video is never its own thumbnail."""
    key = asset.get('key', '')
    game = key.split('/')[1] if key.startswith('games/') else ''
    candidate = asset.get('thumbnailKey') or asset.get('metadata', {}).get('extra', {}).get('preview', {}).get('imageKey')
    if isinstance(candidate, str) and candidate.startswith(f'games/{game}/assets/') and re.search(r'\.(png|jpe?g|webp|avif|gif)$', candidate, re.I):
        import storage_layout
        if storage_layout.REFERENCE.fullmatch(candidate):
            return candidate
    return None


def card(asset):
    """Do not transfer full generation requests, lineage or manuscript fields in a list."""
    metadata = asset.get('metadata', {})
    extra = metadata.get('extra', {})
    result = {key: asset[key] for key in ('key', 'name', 'size', 'contentType', 'kind', 'lastModified',
                                         'thumbnailStatus', 'durationSeconds') if key in asset}
    thumbnail = cover_key(asset)
    if thumbnail:
        result['thumbnailKey'] = thumbnail
    result['metadata'] = {key: metadata[key] for key in ('title', 'category', 'tags', 'characterIds') if key in metadata}
    result['metadata']['extra'] = {key: extra[key] for key in ('version', 'relationshipRole', 'sceneRef',
        'storyboardShotRef', 'episodeRef', 'assetType', 'sceneAssembly') if key in extra}
    duration = extra.get('mediaProbe', {}).get('format', {}).get('duration')
    if duration is not None:
        result['metadata']['extra']['mediaProbe'] = {'format': {'duration': duration}}
    return result


def project(assets, selected):
    return [card(asset) if selected['view'] == 'cards' else asset for asset in assets if matches(asset, selected)]


def valid_keys(game, keys):
    import storage_layout
    if not isinstance(keys, list) or not 1 <= len(keys) <= 60 or any(
        not isinstance(key, str) or not storage_layout.REFERENCE.fullmatch(key)
        or not key.startswith(f'games/{game}/assets/') for key in keys
    ):
        raise ValueError('Provide 1–60 same-game asset references')
    return list(dict.fromkeys(keys))


def related(assets, key):
    """Retain the exact connected lineage, not every asset's large request metadata."""
    by_key = {asset['key']: asset for asset in assets}
    edges = {}
    videos = {}
    for asset in assets:
        if asset.get('contentType', '').startswith('video/'):
            videos.setdefault(asset['key'].rsplit('/', 1)[0], []).append(asset['key'])
    for asset in assets:
        refs = list(asset.get('sourceKeys', []))
        playback = asset.get('playback', {})
        refs.extend(playback.get(field) for field in ('recordingKey', 'audioKey') if playback.get(field))
        paired = asset['key'].rsplit('.', 1)[0] + ('.json' if asset['key'].endswith('.md') else '.md')
        if by_key.get(paired, {}).get('kind') == asset.get('kind'):
            refs.append(paired)
        directory = asset['key'].rsplit('/', 1)[0]
        for ref in refs:
            edges.setdefault(asset['key'], set()).add(ref)
            edges.setdefault(ref, set()).add(asset['key'])
        if asset.get('kind') == 'video-captions':
            for candidate in videos.get(directory, []):
                edges.setdefault(candidate, set()).add(asset['key'])
                edges.setdefault(asset['key'], set()).add(candidate)
    found, pending = set(), [key]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(edges.get(current, []))
    records = []
    for reference in sorted(found & by_key.keys()):
        original = by_key[reference]
        item = card(original)
        for field in ('sourceKeys', 'recording', 'playback', 'lineageWarning'):
            if field in original:
                item[field] = original[field]
        for field in ('sessionId', 'description'):
            if field in original.get('metadata', {}):
                item['metadata'][field] = original['metadata'][field]
        if reference == key:
            item['metadata'] = original.get('metadata', {})
        records.append(item)
    if len(json.dumps(records).encode()) > 2 * 1024**2:
        raise ValueError('Asset connections exceed the bounded response size')
    return {'assets': records, 'cursor': None}
