"""Exact active-job reference inventory for the archive-v1 all-game migration."""
from boto3.dynamodb.conditions import Key


def rows(table):
    """Consistent base-table reads avoid an eventually consistent GSI migration gap."""
    result, cursor = [], None
    for _ in range(10):
        args = {'KeyConditionExpression': Key('pk').eq('JOBS'), 'ConsistentRead': True, 'Limit': 100}
        if cursor:
            args['ExclusiveStartKey'] = cursor
        page = table.query(**args)
        result.extend(page.get('Items', []))
        cursor = page.get('LastEvaluatedKey')
        if not cursor:
            return result
    raise RuntimeError('Job reference migration exceeds its bounded inventory; extend the migration before activation')


def job_reference(game, job, table_name, kind):
    """No filename, player, or provenance inference; only explicit stored input pins."""
    if job.get('gameId') != game:
        return None
    keys = []
    if kind == 'model-job':
        views = job.get('views', {})
        if not isinstance(views, dict):
            raise ValueError('Model job views are not structured input pins')
        keys.extend(value['key'] for value in views.values())
        keys.extend(value for key, value in job.get('appearanceSelection', {}).items() if key.endswith('Key') and value)
    elif kind == 'asset-generation':
        thumbnail = job.get('characterReference', {}).get('details', {}).get('thumbnailAssetKey')
        if thumbnail:
            keys.append(thumbnail)
    else:
        raise ValueError('Unknown source job type')
    if any(not isinstance(key, str) or not key.startswith(f'games/{game}/assets/') for key in keys):
        raise ValueError('Job source belongs to another game')
    return {'owner': kind + ':' + job['jobId'], 'keys': sorted(set(keys)),
        'active': {'table': table_name, 'pk': 'JOBS', 'sk': job['jobId']}}


def snapshot(game, model_table, generation_table):
    refs = []
    for table, kind in [(model_table, 'model-job'), (generation_table, 'asset-generation')]:
        for job in rows(table):
            ref = job_reference(game, job, table.name, kind)
            if ref:
                refs.append(ref)
    return refs
