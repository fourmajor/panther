"""Versioned tag display edits preserve original asset metadata and immutable history."""
from copy import deepcopy
from datetime import datetime
import math
import re


def validate(body):
    action = body.get('action')
    fields = {'gameId', 'action', 'name', 'operationId'} | ({'newName'} if action == 'rename' else set())
    if set(body) != fields or action not in {'rename', 'delete'} or not isinstance(body.get('operationId'), str) or not re.fullmatch(r'[a-f0-9]{32}', body['operationId']):
        raise ValueError('Invalid tag change')
    for field in ('name', *(['newName'] if action == 'rename' else [])):
        value = body[field]
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 64 or any(ord(c) < 32 for c in value):
            raise ValueError('Enter a tag of up to 64 characters')
    return {**body, 'name': body['name'].strip(), **({'newName': body['newName'].strip()} if action == 'rename' else {})}


def timestamp(value):
    try:
        numeric = float(value)
        return numeric if math.isfinite(numeric) and numeric >= 0 else 0
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return 0


def project(asset, events):
    result = deepcopy(asset)
    tags = list(result.get('metadata', {}).get('tags', []))
    observed = timestamp(result.get('lastModified'))
    for event in events:
        if observed > event['at']:
            continue
        tags = [event['newName'] if name.casefold() == event['name'].casefold() and event['action'] == 'rename' else name
                for name in tags if not (name.casefold() == event['name'].casefold() and event['action'] == 'delete')]
    if 'metadata' in result:
        result['metadata']['tags'] = list({name.casefold(): name for name in tags}.values())
    return result
