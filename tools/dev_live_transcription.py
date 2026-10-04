"""Local durable broker; no credentials on disk, no automatic provider retries."""
import json
import sqlite3
import live_transcription as live
from dev_editorial_worker import load_key


def create(store, body, key_loader=load_key, opener=None):
    pk, sk = live.identity(body)
    if not store.get('game', body['gameId']):
        raise LookupError('Game not found')
    record = live.intent(body, 'developer')
    key = key_loader()  # Fail before checkpoint when no server key is configured.
    identity = pk + '#' + sk
    try:
        with store.connect() as db:
            db.execute("INSERT INTO records VALUES ('browser-live-session',?,?,?)", (identity, body['gameId'], json.dumps(record)))
    except sqlite3.IntegrityError:
        raise FileExistsError('Live connection was already requested. Audio is retained; it will not be repeated.') from None
    try:
        response = live.mint(key, record, opener)
    except Exception as exc:
        store.put('browser-live-session', identity, live.failure(record, exc), body['gameId'])
        raise ValueError('Live transcription could not connect. Audio is retained.') from None
    store.put('browser-live-session', identity, record, body['gameId'])
    return response


def save_events(store, body):
    pk, sk = live.identity(body)
    record = store.get('browser-live-session', pk + '#' + sk)
    if not record:
        raise LookupError('Live session not found')
    receipt = live.events(body, record)
    identity = pk + '#' + sk + '#' + body['batchId']
    with store.connect() as db:
        row = db.execute("SELECT payload FROM records WHERE kind='browser-live-events' AND id=?", (identity,)).fetchone()
        if row:
            if json.loads(row[0])['sha256'] != receipt['sha256']:
                raise FileExistsError('Live event batch changed')
        else:
            db.execute("INSERT INTO records VALUES ('browser-live-events',?,?,?)", (identity, body['gameId'], json.dumps(receipt)))
    return {'saved': True}
