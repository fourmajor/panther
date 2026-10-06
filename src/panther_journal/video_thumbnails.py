"""Authenticated, resumable, local video cover preparation. Never runs on a page view."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import uuid
from contextlib import redirect_stdout
from urllib.parse import urlparse

import click
import requests
from PIL import Image, ImageStat

from panther_journal import cloud, generation_metadata


def extract(source, folder):
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-protocol_whitelist', 'file,pipe', '-i', str(source),
                    '-t', '10', '-vf', 'fps=2,scale=640:-2', '-frames:v', '20',
                    '-q:v', '3', str(folder / 'frame-%03d.jpg')],
                   check=True, timeout=90, capture_output=True)
    frames = sorted(folder.glob('frame-*.jpg'))
    if not frames:
        raise ValueError('Video has no decodable frame')
    for index, frame in enumerate(frames):
        with Image.open(frame) as image:
            stats = ImageStat.Stat(image.convert('L'))
            if 8 < stats.mean[0] < 247 or stats.stddev[0] > 8:
                return frame, (index + .5) / 2
    return frames[0], .25


def download(asset, destination):
    target = urlparse(asset['url'])
    if target.scheme != 'https' or not (target.hostname or '').endswith('.amazonaws.com'):
        raise ValueError('Invalid video download destination')
    if not 0 < asset['size'] <= 1024**3 or not asset.get('versionId'):
        raise ValueError('Video requires a pinned version and a size below 1 GiB')
    digest, size = hashlib.sha256(), 0
    with requests.get(asset['url'], stream=True, timeout=(15, 300), allow_redirects=False) as response:
        response.raise_for_status()
        with destination.open('xb') as output:
            for chunk in response.iter_content(1024 * 1024):
                size += len(chunk)
                if size > asset['size']:
                    raise ValueError('Video size changed')
                digest.update(chunk)
                output.write(chunk)
    if size != asset['size'] or asset.get('sha256') and base64.b64encode(digest.digest()).decode() != asset['sha256']:
        raise ValueError('Video checksum or size changed')
    return digest.hexdigest()


def prepare(config, game, asset, root):
    """Upload an immutable image, then link it with a version-guarded metadata migration."""
    key = asset['key']
    signed = cloud.api(config, 'GET', '/object-url', params={'key': key})
    folder = root / hashlib.sha256((key + ':' + signed['versionId']).encode()).hexdigest()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    source = folder / ('source' + Path(key).suffix)
    # Keep failed transfers for inspection. A subsequent run uses a new transfer filename.
    if source.exists():
        source = folder / ('source-' + uuid.uuid4().hex + Path(key).suffix)
    checksum = download(signed, source)
    current = cloud.api(config, 'GET', '/object-url', params={'key': key})
    if current.get('versionId') != signed['versionId']:
        raise ValueError('Video changed during cover preparation')
    frame, timestamp = extract(source, folder)
    identity = 'video-thumbnail-' + hashlib.sha256((key + ':' + checksum).encode()).hexdigest()[:40]
    receipt = folder / 'upload.json'
    if receipt.exists():
        uploaded = json.loads(receipt.read_text())
    else:
        metadata = {'title': asset.get('metadata', {}).get('title') or Path(key).stem,
                    'characterIds': asset.get('metadata', {}).get('characterIds', []), 'sourceKeys': [key],
                    'extra': {'relationshipRole': 'intermediate', 'generation': generation_metadata.local('FFmpeg'),
                              'videoThumbnail': {'schemaVersion': 1, 'sourceVersionId': signed['versionId'],
                                                 'sourceSha256': checksum, 'timestampSeconds': timestamp}}}
        metadata_file = folder / 'metadata.json'
        metadata_file.write_text(json.dumps(metadata))
        result = io.StringIO()
        with redirect_stdout(result):
            cloud.upload.callback(file=frame, game=game, asset=identity, kind='video-thumbnail', metadata=metadata_file, new_version_of=None, as_json=True)
        uploaded = json.loads(result.getvalue())
        receipt.write_text(json.dumps(uploaded))
    details = copy.deepcopy(current['metadata'])
    details.setdefault('extra', {}).setdefault('preview', {}).update(schemaVersion=1, imageKey=uploaded['key'])
    request = {'schemaVersion': 1, 'key': key, 'expectedVersionId': current['versionId'],
               'kind': current['kind'], 'metadata': details,
               'reason': 'Video cover v1: sampled frame from exact immutable source', 'dryRun': False}
    (folder / 'migration.json').write_text(json.dumps(request))
    result = cloud.api(config, 'POST', '/asset-migrations', json=request)
    (folder / 'result.json').write_text(json.dumps(result))
    return result


def command(game, all_games, work_dir, apply):
    import os
    os.umask(0o077)
    config = cloud.configuration()
    games = cloud.api(config, 'GET', '/games')['games'] if all_games else [{'id': cloud.slug(game)}]
    work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    for entry in games:
        cursor, seen = None, set()
        while True:
            page = cloud.api(config, 'GET', '/assets', params={'gameId': entry['id'], 'section': 'videos', 'cursor': cursor})
            for asset in page['assets']:
                if not asset.get('contentType', '').startswith('video/') or asset.get('thumbnailKey') or asset.get('metadata', {}).get('extra', {}).get('preview', {}).get('imageKey'):
                    continue
                if not apply:
                    click.echo(f"Missing cover: {asset['key']}")
                else:
                    result = prepare(config, entry['id'], asset, work_dir)
                    click.echo(f"{result['status']}: {asset['key']}")
            cursor = page.get('cursor')
            if not cursor:
                break
            if cursor in seen:
                raise click.ClickException('Repeated catalog cursor')
            seen.add(cursor)
