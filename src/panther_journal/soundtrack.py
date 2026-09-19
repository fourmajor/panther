"""Owner-approved soundtrack finishing on a reconciled, closed production budget."""
import hashlib
import json
import math
import os
import re
import time
from decimal import Decimal
from pathlib import Path

import click
import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from panther_journal import video as v, narration as n, generation_metadata as g
from panther_journal.audio_storage import write_json

PROFILES = {
    'music': ('fal-ai/elevenlabs/music', 'minutes', Decimal('0.6')),
    'effects': ('fal-ai/elevenlabs/sound-effects/v2', 'seconds', Decimal('0.002')),
    'speech': (n.ENDPOINT, '1000 characters', Decimal('0.1')),
}


def schema(db):
    n.schema(db)
    db.execute('CREATE TABLE IF NOT EXISTS soundtrack_projects (id TEXT PRIMARY KEY, content TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS soundtrack_plans (id TEXT PRIMARY KEY, content TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0)')
    db.execute('CREATE TABLE IF NOT EXISTS soundtrack_attempts (id TEXT PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE, project TEXT NOT NULL, reserved_cents INTEGER NOT NULL CHECK(reserved_cents>0), state TEXT NOT NULL, content TEXT NOT NULL)')


def history(db, project):
    records = []
    for table, reader in [('attempts', v.read_plan), ('narration_attempts', n.read_plan)]:
        for row in db.execute(f'SELECT * FROM {table}'):
            plan, _ = reader(db, row['plan_id'])
            if plan['manifest'].get('projectId') != project:
                continue
            d = json.loads(row['content'])
            if row['state'] not in ('COMPLETED', 'FAILED', 'UNAVAILABLE') or not d.get('requestId'):
                v.fail('All prior requests need terminal states and exact billing evidence.')
            endpoint = plan['endpoint'] if table == 'narration_attempts' else plan['inputs'][row['shot']]['endpoint']
            records.append(dict(table=table, id=row['id'], planId=row['plan_id'], state=row['state'],
                                requestId=d['requestId'], endpoint=endpoint, reservedCents=row['reserved_cents']))
    return sorted(records, key=lambda r: (r['table'], r['id']))


def reconcile(project, maximum, reason, fal):
    if not reason.strip() or len(reason) > 1000 or not 0 < maximum <= 100000:
        v.fail('Explicit bounded soundtrack allowance and owner approval required.')
    with v.database() as db:
        schema(db)
        existing = db.execute('SELECT content FROM soundtrack_projects WHERE id=?', (project,)).fetchone()
        if existing:
            prior_audit=json.loads(existing['content'])
            if prior_audit['soundtrackLimitCents']!=maximum or prior_audit['ownerAuthorization']!=reason:
                v.fail('Reconciliation already exists with different approval facts; no reset supported.')
            return status(db, project)
        if v.has_unresolved(db):
            v.fail('Resolve outstanding submissions first.')
        budget = n.budget_status(db, project)
        prior = history(db, project)
    if not prior or len({r['requestId'] for r in prior}) != len(prior):
        v.fail('Missing or duplicate original request identities.')
    billing = fal.billing()
    if billing['account'] != budget['billingAccount']:
        v.fail('Billing account changed.')
    events = {}
    ids = [r['requestId'] for r in prior]
    for i in range(0, len(ids), 50):
        events.update(fal.billing_events(ids[i:i+50]))
    amount = Decimal(0)
    for record in prior:
        event = events.get(record['requestId'])
        if not event or event['endpoint'] != record['endpoint'] or v.number(event['amount']) < 0:
            v.fail('Exact billing evidence required for every original request.')
        amount += v.number(event['amount'])
    if v.cents(amount) + maximum > budget['capCents']:
        v.fail('Soundtrack allowance exceeds the original project ceiling.')
    audit = dict(schemaVersion=1, projectId=project, gameId=budget['gameId'],
                 billingAccount=billing['account'], capCents=budget['capCents'],
                 historicalBilledUsd=str(amount), soundtrackLimitCents=maximum,
                 history=prior, billingEvents=events, ownerAuthorization=reason,
                 reconciledAt=int(time.time()))
    with v.database() as db:
        schema(db)
        if v.has_unresolved(db) or history(db, project) != prior:
            v.fail('History changed during reconciliation; inspect before retrying.')
        db.execute('INSERT INTO soundtrack_projects VALUES (?,?)', (project, v.canonical(audit)))
        return status(db, project)


def status(db, project):
    row = db.execute('SELECT content FROM soundtrack_projects WHERE id=?', (project,)).fetchone()
    if not row:
        v.fail('Reconcile and close this production project before soundtrack spending.')
    b = json.loads(row['content'])
    original = n.budget_status(db, project)
    if (b['schemaVersion'] != 1 or not b['ownerAuthorization'] or history(db, project) != b['history']
            or b['capCents'] != original['capCents'] or b['billingAccount'] != original['billingAccount']
            or b['gameId'] != original['gameId']):
        v.fail('Reconciliation audit no longer matches original history.')
    total = Decimal(0)
    for r in b['history']:
        e = b['billingEvents'].get(r['requestId'])
        if not e or e['endpoint'] != r['endpoint'] or v.number(e['amount']) < 0:
            v.fail('Invalid billing reconciliation evidence.')
        total += v.number(e['amount'])
    if total != v.number(b['historicalBilledUsd']) or v.cents(total) + b['soundtrackLimitCents'] > b['capCents']:
        v.fail('Invalid reconciled allowance.')
    held = db.execute('SELECT COALESCE(SUM(reserved_cents),0) FROM soundtrack_attempts WHERE project=?', (project,)).fetchone()[0]
    return {**b, 'soundtrackReservedCents': held, 'availableCents': b['soundtrackLimitCents'] - held}


class Manifest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schemaVersion: int = 1
    projectId: str
    gameId: str
    kind: str
    title: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=4000)
    seconds: int = Field(ge=1, le=240)
    voice: str | None = None
    sourceKeys: list[str] = Field(min_length=1, max_length=4)


def validate(m):
    try:
        m = Manifest.model_validate(m).model_dump()
    except ValidationError:
        v.fail('Invalid soundtrack manifest.')
    v.identifier(m['projectId']); v.identifier(m['gameId'])
    if m['schemaVersion'] != 1 or m['kind'] not in PROFILES:
        v.fail('Unsupported soundtrack profile.')
    if any(not re.fullmatch(r'games/'+re.escape(m['gameId'])+r'/assets/[a-z0-9-]+/original/[^/?\\]+', k) or '..' in k for k in m['sourceKeys']):
        v.fail('Exact same-game asset sources required.')
    if m['kind'] == 'speech':
        if m['voice'] not in n.VOICES or len(m['text']) > 600:
            v.fail('Short stock-voice performances only; no cloning or full narrator replacement.')
    elif m['voice'] is not None:
        v.fail('Voice is only valid for speech.')
    if m['kind'] == 'effects' and m['seconds'] > 22:
        v.fail('Effects are bounded to 22 seconds.')
    return m


def payload(m):
    if m['kind'] == 'speech':
        return n.payload(m)
    if m['kind'] == 'music':
        return dict(prompt=m['text'], music_length_ms=m['seconds']*1000, force_instrumental=True, output_format='mp3_44100_128')
    return dict(text=m['text'], duration_seconds=m['seconds'], prompt_influence=0.5, output_format='mp3_44100_128', loop=False)


def quote(m, fal):
    endpoint, unit, floor = PROFILES[m['kind']]
    prices = fal.request('GET', v.PLATFORM+'/models/pricing', params={'endpoint_id':endpoint}).get('prices', [])
    matching = [p for p in prices if p.get('endpoint_id') == endpoint]
    if len(matching) != 1 or matching[0].get('currency') != 'USD' or matching[0].get('unit') != unit:
        v.fail('Unknown pricing units; no spending.')
    price = v.number(matching[0]['unit_price'])
    if price <= 0:
        v.fail('Invalid rate.')
    # fal bills music by each started output minute. Reserve that exact rounded
    # unit with 25% headroom; do not invent a fifth billed minute for a four-minute track.
    units = (Decimal(math.ceil(m['seconds']/60)) if m['kind']=='music' else
             Decimal(m['seconds']) if m['kind']=='effects' else Decimal(len(m['text'].encode()))/1000)
    return {'endpoint':endpoint, 'unit':unit, 'unitPriceUsd':str(price),
            'reserveCents':v.cents(max(price,floor)*units*Decimal('1.25'))}


def read_plan(db, pid):
    row = db.execute('SELECT * FROM soundtrack_plans WHERE id=?',(pid,)).fetchone()
    if not row:
        v.fail('Unknown soundtrack plan.')
    p = json.loads(row['content']); m = validate(p['manifest'])
    if hashlib.sha256(v.canonical(p).encode()).hexdigest()!=pid or payload(m)!=p['input'] or PROFILES[m['kind']][0]!=p['quote']['endpoint']:
        v.fail('Soundtrack plan integrity failure.')
    return p, bool(row['approved'])


def prepare(m, fal):
    m = validate(m); q = quote(m, fal); billing = fal.billing()
    p = dict(manifest=m, input=payload(m), quote=q, billingAccount=billing['account'])
    pid = hashlib.sha256(v.canonical(p).encode()).hexdigest()
    with v.database() as db:
        schema(db); b=status(db,m['projectId'])
        if b['gameId']!=m['gameId'] or b['billingAccount']!=p['billingAccount'] or q['reserveCents']>b['availableCents']:
            v.fail('Project scope or soundtrack budget mismatch.')
        db.execute('INSERT OR IGNORE INTO soundtrack_plans (id,content) VALUES (?,?)',(pid,v.canonical(p)))
    return dict(planId=pid, **p)


def attempt(row):
    return dict(attemptId=row['id'], planId=row['plan_id'], state=row['state'], reservedCents=row['reserved_cents'], **json.loads(row['content']))


def update(aid, state, extra):
    with v.database() as db:
        row=db.execute('SELECT * FROM soundtrack_attempts WHERE id=?',(aid,)).fetchone()
        d={**json.loads(row['content']),**extra}
        db.execute('UPDATE soundtrack_attempts SET state=?,content=? WHERE id=?',(state,v.canonical(d),aid))
        return attempt(db.execute('SELECT * FROM soundtrack_attempts WHERE id=?',(aid,)).fetchone())


def submit(pid, fal):
    aid=hashlib.sha256(('soundtrack:'+pid).encode()).hexdigest()
    with v.database() as db:
        schema(db)
        old=db.execute('SELECT * FROM soundtrack_attempts WHERE id=?',(aid,)).fetchone()
        if old:return attempt(old)
        p,approved=read_plan(db,pid)
        if not approved:v.fail('Explicit exact-plan audio/voice/text/budget approval required.')
    m=p['manifest']; q=quote(m,fal); billing=fal.billing()
    if q['reserveCents']>p['quote']['reserveCents'] or billing['account']!=p['billingAccount']:
        v.fail('Price increased or billing account changed.')
    with v.database() as db:
        old=db.execute('SELECT * FROM soundtrack_attempts WHERE id=?',(aid,)).fetchone()
        if old:return attempt(old)
        b=status(db,m['projectId'])
        if v.has_unresolved(db) or p['quote']['reserveCents']>b['availableCents'] or v.number(billing['balanceUsd'])*100 < b['availableCents']+500:
            v.fail('Unresolved request, insufficient project allowance or balance safety floor.')
        db.execute('INSERT INTO soundtrack_attempts VALUES (?,?,?,?,?,?)',(aid,pid,m['projectId'],p['quote']['reserveCents'],'SUBMITTING',v.canonical({'createdAt':int(time.time())})))
    endpoint=p['quote']['endpoint']
    try:
        result=fal.request('POST',v.QUEUE+'/'+endpoint,json=p['input'],headers={'X-Fal-No-Retry':'1','x-app-fal-disable-fallback':'true','X-Fal-Store-IO':'1'})
        rid=result['request_id']
        if not isinstance(rid,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}',rid):raise ValueError()
        update(aid,'UNKNOWN',{'requestId':rid})
        urls={k:v.queue_url(result[k+'_url'],rid,endpoint,k) for k in ('status','response','cancel')}
        return update(aid,'SUBMITTED',{'urls':urls})
    except (click.ClickException,KeyError,TypeError,ValueError):
        update(aid,'UNKNOWN',{})
        v.fail('Uncertain submission; reservation retained. Never resubmit a new plan.')


def poll(aid,fal):
    with v.database() as db:
        row=db.execute('SELECT * FROM soundtrack_attempts WHERE id=?',(aid,)).fetchone()
        if not row:v.fail('Unknown soundtrack attempt.')
        if row['state'] in ('COMPLETED','FAILED'):return attempt(row)
        d=json.loads(row['content']);p,_=read_plan(db,row['plan_id'])
    if not d.get('urls'):v.fail('Unknown submission; inspect before proceeding.')
    ep=p['quote']['endpoint'];rid=d['requestId']
    state=fal.request('GET',v.queue_url(d['urls']['status'],rid,ep,'status'))
    if state.get('request_id',rid)!=rid:v.fail('Mismatched request identity.')
    if state.get('status') in ('IN_QUEUE','IN_PROGRESS'):return update(aid,state['status'],{})
    if state.get('status')!='COMPLETED':v.fail('Unknown provider state.')
    try:result=fal.request('GET',v.queue_url(d['urls']['response'],rid,ep,'response'),completed_result=True)
    except v.TerminalModelRejection:return update(aid,'FAILED',{'reason':'Provider rejection; no retries.'})
    if not isinstance(result.get('audio'),dict):v.fail('Missing audio; reservation retained.')
    v.media_url(result['audio']['url'])
    return update(aid,'COMPLETED',{'result':result})


def download(aid,fal):
    with v.database() as db:
        row=db.execute('SELECT * FROM soundtrack_attempts WHERE id=?',(aid,)).fetchone()
        if not row or row['state']!='COMPLETED':v.fail('Completed audio required.')
        d=json.loads(row['content']);p,_=read_plan(db,row['plan_id'])
    folder=v.private_root()/'soundtrack-outputs';folder.mkdir(exist_ok=True,mode=0o700)
    target=folder/(aid+'.mp3')
    if not target.exists():
        # A streamed bounded download to a create-only original; incomplete bytes stay separate.
        temp=folder/(aid+'.partial')
        if temp.exists():v.fail('Partial download exists; inspect before recovery.')
        with requests.Session() as session:
            session.trust_env=False
            with session.get(v.media_url(d['result']['audio']['url']),stream=True,timeout=(10,30),allow_redirects=False) as response:
                if response.status_code!=200:v.fail('Download failed; do not regenerate.')
                size=0
                with temp.open('xb') as out:
                    os.chmod(temp,0o600)
                    for block in response.iter_content(1024*1024):
                        size+=len(block)
                        if size>32*1024**2:v.fail('Audio exceeds 32 MiB bound.')
                        out.write(block)
                    out.flush();os.fsync(out.fileno())
        head=temp.read_bytes()[:3]
        if size<100 or not(head==b'ID3' or head[0]==255 and head[1]&224==224):v.fail('Expected MP3.')
        os.link(temp,target)
    sha=hashlib.sha256(target.read_bytes()).hexdigest()
    if not d.get('sha256') and not (folder/(aid+'.partial')).exists():
        v.fail('Unrecorded original lacks its partial evidence; inspect before recovery.')
    if not d.get('sha256') and hashlib.sha256((folder/(aid+'.partial')).read_bytes()).hexdigest()!=sha:
        v.fail('Original conflicts with downloaded evidence.')
    if d.get('sha256') and d['sha256']!=sha:v.fail('Original bytes changed.')
    event=fal.billing_events([d['requestId']]).get(d['requestId'])
    billed=event['amount'] if event and event['endpoint']==p['quote']['endpoint'] else None
    m=p['manifest'];meta=dict(title=m['title'],category='creative-reimagining',sourceKeys=m['sourceKeys'],extra=dict(relationshipRole='finished',contextUse='exclude',generation=g.fal(p['quote']['endpoint'],d['requestId'],billed)))
    if m['voice']:meta['extra']['voice']=m['voice']
    mp=target.with_suffix('.metadata.json')
    if not mp.exists():write_json(mp,meta)
    provenance=target.with_suffix('.provenance.json')
    if not provenance.exists():write_json(provenance,dict(plan=p,sha256=sha,requestId=d['requestId'],billingEvent=event))
    return update(aid,'COMPLETED',dict(downloadPath=str(target),sha256=sha,metadataPath=str(mp)))


@click.group()
def soundtrack():
    """Explicit premium sound production, bounded by the original movie budget."""


@soundtrack.command('reconcile')
@click.argument('project')
@click.option('--maximum',required=True)
@click.option('--reason',required=True)
@click.option('--owner-approved',is_flag=True,required=True)
def reconcile_command(project,maximum,reason,owner_approved):
    if not owner_approved:v.fail('Owner approval required.')
    b=reconcile(project,v.cents(maximum),reason,v.Fal())
    click.echo(json.dumps({k:b[k] for k in ('capCents','historicalBilledUsd','soundtrackLimitCents','availableCents')},indent=2))


@soundtrack.command('prepare')
@click.argument('manifest',type=click.Path(exists=True,path_type=Path))
def prepare_command(manifest):
    if manifest.stat().st_size>50000:v.fail('Manifest too large.')
    click.echo(json.dumps(prepare(json.loads(manifest.read_text()),v.Fal()),indent=2))


@soundtrack.command('approve')
@click.argument('plan_id')
@click.option('--owner-approved',is_flag=True,required=True)
@click.option('--auto-topup-disabled',is_flag=True,required=True)
def approve_command(plan_id,owner_approved,auto_topup_disabled):
    if not owner_approved or not auto_topup_disabled:v.fail('Explicit rights, casting, text/model sharing and spending approval required.')
    with v.database() as db:
        p,_=read_plan(db,plan_id)
        if p['quote']['reserveCents']>status(db,p['manifest']['projectId'])['availableCents']:v.fail('Allowance exceeded.')
        db.execute('UPDATE soundtrack_plans SET approved=1 WHERE id=?',(plan_id,))
    click.echo('Approved exact soundtrack request; no generation yet.')


def command(name,func):
    @soundtrack.command(name)
    @click.argument('identity')
    def run(identity):
        result=func(identity,v.Fal())
        # Do not print signed provider URLs, complete private prompts or account details.
        click.echo(json.dumps({k:val for k,val in result.items() if k not in ('urls','result')},indent=2))
command('submit',submit)
command('poll',poll)
command('download',download)
