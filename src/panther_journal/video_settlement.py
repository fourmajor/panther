"""Audited completion settlement; immutable bills replace unused project headroom."""

import json
import time

from panther_journal import video as v


def snapshot(db, project):
    plans, attempts = [], []
    for row in db.execute('SELECT id FROM plans ORDER BY id'):
        plan, _ = v.read_plan(db, row['id'])
        if plan['manifest'].get('projectId') == project:
            plans.append(row['id'])
    for row in db.execute('SELECT * FROM attempts ORDER BY id'):
        if row['plan_id'] in plans:
            attempts.append(dict(row))
    return plans, attempts


def audit(db, project):
    if not project or not db.execute("SELECT 1 FROM sqlite_master WHERE name='video_project_settlements'").fetchone():
        return None
    row = db.execute('SELECT content FROM video_project_settlements WHERE project=?', (project,)).fetchone()
    if not row:
        return None
    data = json.loads(row['content'])
    original = db.execute('SELECT content FROM narration_budgets WHERE id=?', (project,)).fetchone()
    if not original or json.loads(original['content']) != data.get('originalAllocation'):
        v.fail('Project settlement no longer matches its immutable allocation.')
    budget = data['originalAllocation']
    if (data.get('schemaVersion') != 1 or data.get('projectId') != project
            or not isinstance(data.get('ownerAuthorization'), str) or not data['ownerAuthorization'].strip()
            or type(data.get('settledAt')) is not int or data['settledAt'] <= 0
            or type(data.get('videoAllowanceCents')) is not int
            or not 0 <= data['videoAllowanceCents'] < budget['capCents']
            or not data.get('closedPlanIds') or not data.get('attempts')):
        v.fail('Invalid project settlement audit.')
    request_ids, released, billed = set(), 0, 0
    for plan_id in data['closedPlanIds']:
        plan, _ = v.read_plan(db, plan_id)
        if plan['manifest'].get('projectId') != project:
            v.fail('Settlement contains a foreign plan.')
    for prior in data['attempts']:
        current = db.execute('SELECT * FROM attempts WHERE id=?', (prior['id'],)).fetchone()
        if not current or dict(current) != prior or prior['state'] != 'COMPLETED' or prior['plan_id'] not in data['closedPlanIds']:
            v.fail('Settled attempt changed; refusing to spend.')
        content = json.loads(prior['content'])
        plan, _ = v.read_plan(db, prior['plan_id'])
        request = content.get('requestId')
        event = data['billingEvents'].get(request)
        if (not request or request in request_ids or not event
                or plan['billingAccount'] != budget['billingAccount']
                or content.get('endpoint') != plan['inputs'][prior['shot']]['endpoint']
                or event.get('endpoint') != content.get('endpoint')
                or v.number(event.get('amount')) < 0):
            v.fail('Exact same-account billing required for settlement.')
        charge = v.cents(event['amount'])
        if charge > prior['reserved_cents']:
            v.fail('Billed amount exceeds its original reservation.')
        request_ids.add(request)
        billed += charge
        released += prior['reserved_cents'] - charge
    # Closing every prior plan prevents unused approved attempts from spending released headroom.
    for current in db.execute('SELECT * FROM attempts'):
        if current['plan_id'] in data['closedPlanIds'] and current['id'] not in {r['id'] for r in data['attempts']}:
            v.fail('A closed plan acquired another attempt.')
    if data.get('releasedHeadroomCents') != released or data.get('historicalBilledCents') != billed or billed > data['videoAllowanceCents']:
        v.fail('Invalid settled billing totals.')
    held = db.execute('SELECT COALESCE(SUM(reserved_cents),0) FROM narration_attempts WHERE project=?', (project,)).fetchone()[0]
    if held + data['videoAllowanceCents'] > budget['capCents']:
        v.fail('Settlement would invade reserved narration allowance.')
    return data


def settle(project, allowance, reason, fal):
    from panther_journal import narration as n
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        v.fail('Explicit replacement authorization required.')
    with v.database() as db:
        n.schema(db)
        prior_audit = audit(db, project)
        if prior_audit:
            if prior_audit['videoAllowanceCents'] != allowance or prior_audit['ownerAuthorization'] != reason.strip():
                v.fail('Settlement already exists with different approval facts.')
            return prior_audit
        v.assert_generation_open(db, project)
        if v.has_unresolved(db):
            v.fail('Resolve outstanding submissions before settlement.')
        budget = n.budget_status(db, project)
        original = json.loads(db.execute('SELECT content FROM narration_budgets WHERE id=?', (project,)).fetchone()[0])
        if not 0 <= allowance < budget['capCents'] or allowance + budget['narrationReservedCents'] > budget['capCents']:
            v.fail('Allowance must fit the unchanged cap and existing narration reservations.')
        plans, attempts = snapshot(db, project)
        if not attempts or any(a['state'] != 'COMPLETED' for a in attempts):
            v.fail('Every prior project attempt must be completed; uncertain or failed bills stay reserved.')
    if fal.billing()['account'] != original['billingAccount']:
        v.fail('Billing account changed.')
    ids = [json.loads(a['content']).get('requestId') for a in attempts]
    if not all(ids) or len(set(ids)) != len(ids):
        v.fail('Missing or duplicate request identities.')
    events = {}
    for start in range(0, len(ids), 50):
        events.update(fal.billing_events(ids[start:start + 50]))
    billed, released = 0, 0
    for a, request in zip(attempts, ids, strict=True):
        event = events.get(request)
        content = json.loads(a['content'])
        if not event or event.get('endpoint') != content.get('endpoint') or v.number(event.get('amount')) < 0:
            v.fail('Exact billing evidence required; no headroom released.')
        charge = v.cents(event['amount'])
        billed += charge
        released += a['reserved_cents'] - charge
    data = dict(schemaVersion=1, projectId=project, originalAllocation=original,
                closedPlanIds=plans, attempts=attempts, billingEvents=events,
                historicalBilledCents=billed, releasedHeadroomCents=released,
                videoAllowanceCents=allowance, ownerAuthorization=reason.strip(), settledAt=int(time.time()))
    with v.database() as db:
        if v.has_unresolved(db) or snapshot(db, project) != (plans, attempts):
            v.fail('Project changed during billing verification.')
        db.execute('CREATE TABLE IF NOT EXISTS video_project_settlements (project TEXT PRIMARY KEY, content TEXT NOT NULL)')
        db.execute('INSERT INTO video_project_settlements VALUES (?,?)', (project, v.canonical(data)))
        return audit(db, project)
