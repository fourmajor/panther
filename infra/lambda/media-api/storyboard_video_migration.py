"""Authenticated, repeatable all-game cut-selection contract migration."""
import copy
import json
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

import episode_migration as inventory_tools
import organization_records as records

VERSION = 1
AUDIT = 'storyboard-video-migration-v1'


def upgrade(scene):
    """Never infer footage-to-shot correspondence from an old scene-level take."""
    if scene.get('storyboardVideoVersion') == VERSION:
        return copy.deepcopy(scene)
    result = copy.deepcopy(scene)
    result.update(storyboardVideoVersion=VERSION, shotTakes={})
    # The original record and selection are retained in immutable migration history.
    # Re-selection is explicit; short or ambiguous footage cannot claim completion.
    result.update(selectedOutputKey=None, selectedOutputSceneRevision=None)
    return result


def inventory(media):
    db = inventory_tools.browse_index.table()
    budget, entries = [0, 0], []
    catalog = boto3.resource('dynamodb').Table(inventory_tools.os.environ['CATALOG_TABLE'])
    for game_row in inventory_tools.complete(catalog, 'GAMES', budget):
        game = game_row['sk']
        if not media._valid_slug(game):
            raise ValueError('Invalid game')
        for parent in inventory_tools.complete(db, f'{inventory_tools.PREFIX}#episode#{game}', budget):
            episode = records.decode(parent)
            for row in inventory_tools.complete(db, f"{inventory_tools.PREFIX}#scene#{episode['id']}#{game}", budget):
                scene = records.decode(row)
                if not scene or scene.get('entityType') != 'Scene' or scene.get('gameId') != game or scene.get('episodeId') != episode['id'] or scene.get('id') != row['sk'] or scene.get('revision') != row.get('revision'):
                    raise ValueError('Unresolvable scene ownership; migration blocked')
                records.revision(scene['revision'])
                historical = db.get_item(Key={'pk': f"{inventory_tools.PREFIX}-history#scene#{episode['id']}#{game}#{scene['id']}", 'sk': scene['revision']}, ConsistentRead=True).get('Item')
                if not historical or historical['payload'] != row['payload']:
                    raise ValueError('Exact scene history is unavailable; migration blocked')
                entries.append({'gameId': game, 'episodeId': episode['id'], 'id': scene['id'], 'sourceHash': inventory_tools.digest(scene), 'source': row, 'status': 'already-migrated' if scene.get('storyboardVideoVersion') == VERSION else 'ready'})
    digest = inventory_tools.digest([{key: item[key] for key in ('gameId', 'episodeId', 'id', 'sourceHash')} for item in entries])
    return db, entries, digest


def migrate(media, body, claims):
    if set(body) not in ({'schemaVersion', 'apply'}, {'schemaVersion', 'apply', 'expectedInventoryHash'}) or body.get('schemaVersion') != 2 or type(body.get('apply')) is not bool:
        raise ValueError('Use workspace schemaVersion 2 and apply false for a dry run')
    db, entries, digest = inventory(media)
    summary = [{key: item[key] for key in ('gameId', 'episodeId', 'id', 'sourceHash', 'status')} for item in entries]
    if not body['apply']:
        return media._response(200, {'schemaVersion': 2, 'inventoryHash': digest, 'scenes': summary, 'applied': False})
    if body.get('expectedInventoryHash') != digest:
        return media._response(409, {'error': 'Inventory changed; review a fresh dry run'})
    count = 0
    for item in entries:
        if item['status'] == 'already-migrated':
            continue
        old = records.decode(item['source'])
        scene = upgrade(old)
        revision = inventory_tools.digest(['storyboard-video-v1', old])[:32]
        scene.update(revision=revision, previousRevision=old['revision'], updatedAt=datetime.now(timezone.utc).isoformat(), updatedBy=claims['sub'], reason='Explicit storyboard take contract migration v1')
        payload = json.dumps(scene, separators=(',', ':'), allow_nan=False)
        source = item['source']
        writes = [
            {'Put': {'TableName': db.name, 'Item': records.encode({**source, 'revision': revision, 'payload': payload}), 'ConditionExpression': 'revision = :r AND payload = :p', 'ExpressionAttributeValues': records.encode({':r': old['revision'], ':p': source['payload']})}},
            {'Put': {'TableName': db.name, 'Item': records.encode({'pk': f"{inventory_tools.PREFIX}-history#scene#{item['episodeId']}#{item['gameId']}#{item['id']}", 'sk': revision, 'payload': payload}), 'ConditionExpression': 'attribute_not_exists(pk)'}},
            {'Put': {'TableName': db.name, 'Item': records.encode({'pk': f"{AUDIT}#{item['gameId']}", 'sk': f"{item['episodeId']}#{item['id']}", 'sourcePayload': source['payload'], 'sourceHash': item['sourceHash'], 'destinationRevision': revision, 'appliedBy': claims['sub']}), 'ConditionExpression': 'attribute_not_exists(pk)'}},
        ]
        try:
            boto3.client('dynamodb').transact_write_items(TransactItems=writes)
        except ClientError as error:
            if error.response['Error']['Code'] == 'TransactionCanceledException':
                return media._response(409, {'error': 'A scene changed; rerun dry run to resume', 'appliedCount': count})
            raise
        count += 1
    return media._response(200, {'schemaVersion': 2, 'applied': True, 'appliedCount': count, 'sceneCount': len(entries)})
