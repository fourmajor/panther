"""Explicit all-local-assets cost projection migration; originals and actual costs stay intact."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'src'))
from panther_journal import cost_estimates  # noqa: E402


def candidates(store, pricing=None):
    with store.connect() as db:
        rows = db.execute('SELECT key,game,metadata,data FROM objects ORDER BY key').fetchall()
    objects = {key: (game, json.loads(metadata), raw) for key, game, metadata, raw in rows}
    for key, (game, metadata, raw) in objects.items():
        request, response = {}, {}
        prefix = key.rsplit('/', 1)[0] + '/'
        for name in ('generation-request.json', 'provider-response.json', 'generation.json', 'summary.json'):
            item = objects.get(prefix + name)
            if not item or item[0] != game:
                continue
            try:
                document = json.loads(item[2])
                if not isinstance(document, dict):
                    continue
            except (ValueError, UnicodeError):
                continue
            if name == 'generation-request.json':
                request = document
            elif name == 'provider-response.json':
                response = document
                request = document.get('request', request)
                if 'text' in document and document.get('model') == 'eleven_v3':
                    response = document.get('response', document)
            elif name == 'generation.json':
                request = document.get('providerRequest', request)
                response = document.get('providerResponse', response)
        if metadata.get('contentType') == 'application/json':
            try:
                document = json.loads(raw)
                if isinstance(document, dict) and document.get('apiResponse'):
                    response = document['apiResponse']
            except (ValueError, UnicodeError):
                pass
        # Older local fal receipts retain endpoint and payload, rather than a model profile.
        if metadata.get('extra', {}).get('generation', {}).get('provider') == 'fal':
            endpoint = request.get('endpoint') or response.get('endpoint')
            if endpoint:
                from panther_journal import video
                payload = request.get('payload', request)
                silent = payload.get('generate_audio') is False
                matches = [name for name, profile in video.PROFILES.items() if profile['endpoint'] == endpoint and name.endswith('silent') == silent]
                if len(matches) == 1:
                    request = {**request, 'model': matches[0]}
        receipt = (pricing or {}).get(request.get('model'))
        projected = cost_estimates.annotate(metadata, request, response.get('response', response), api_base=receipt.get('rate') if receipt else None)
        if receipt and projected.get('extra', {}).get('costEstimate'):
            projected['extra']['costEstimate']['evidence']['pricingApi'] = receipt
        if metadata.get('contentType', '').startswith('image/') and metadata.get('extra', {}).get('generation', {}).get('provider') == 'fal':
            job = store.get('asset-generation', metadata.get('extra', {}).get('jobId', '')) or {}
            pinned = job.get('modelContract', {})
            if job.get('gameId') == game and job.get('assetKey') == key and pinned.get('endpoint') == request.get('endpoint'):
                from PIL import Image
                from io import BytesIO
                try:
                    with Image.open(BytesIO(raw)) as image:
                        dimensions = image.size
                        image.verify()
                    measured = cost_estimates.fal_image(pinned.get('priceEstimate'), *dimensions)
                    if measured:
                        projected.setdefault('extra', {})['costEstimate'] = measured
                except (ValueError, OSError):
                    pass
        estimate = projected.get('extra', {}).get('costEstimate')
        if estimate:
            yield key, game, hashlib.sha256(raw).hexdigest(), metadata, estimate


def migrate(store, *, apply=False, pricing=None):
    plan = list(candidates(store, pricing))
    if apply:
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for key, game, checksum, metadata, estimate in plan:
                row = db.execute('SELECT metadata,data FROM objects WHERE key=?', (key,)).fetchone()
                if not row or json.loads(row[0]) != metadata or hashlib.sha256(row[1]).hexdigest() != checksum:
                    raise ValueError('Asset changed during estimate migration; no original data overwritten')
                identity = hashlib.sha256(key.encode()).hexdigest()
                record = {'schemaVersion': 1, 'assetKey': key, 'sourceSha256': checksum, 'sourceMetadata': metadata,
                          'estimate': estimate, 'rateAsOf': cost_estimates.AS_OF, 'recordedAt': datetime.now(timezone.utc).isoformat()}
                old = db.execute("SELECT payload FROM records WHERE kind='asset-cost-estimate' AND id=?", (identity,)).fetchone()
                if old:
                    previous = json.loads(old[0])
                    if previous.get('estimate') == estimate and previous.get('sourceSha256') == checksum:
                        continue
                    history_id = identity + ':' + hashlib.sha256(old[0].encode()).hexdigest()
                    db.execute("INSERT OR IGNORE INTO records VALUES ('asset-cost-estimate-history',?,?,?)", (history_id, game, old[0]))
                    db.execute("UPDATE records SET payload=? WHERE kind='asset-cost-estimate' AND id=?", (json.dumps(record), identity))
                else:
                    db.execute("INSERT INTO records VALUES ('asset-cost-estimate',?,?,?)", (identity, game, json.dumps(record)))
    return {'schemaVersion': 1, 'apply': apply, 'estimatedAssets': len(plan), 'rateAsOf': cost_estimates.AS_OF}


def overlay(store, key, metadata, raw):
    record = store.get('asset-cost-estimate', hashlib.sha256(key.encode()).hexdigest())
    if not record or record.get('sourceSha256') != hashlib.sha256(raw).hexdigest() or record.get('sourceMetadata') != metadata:
        return metadata
    projected = deepcopy(metadata)
    projected.setdefault('extra', {})['costEstimate'] = record['estimate']
    return projected


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--pricing-file', type=Path, help='Private retained read-only fal pricing receipts, keyed by exact model profile')
    args = parser.parse_args()
    from dev_server import Store
    pricing = json.loads(args.pricing_file.read_text()) if args.pricing_file else None
    print(json.dumps(migrate(Store(args.database), apply=args.apply, pricing=pricing)))
