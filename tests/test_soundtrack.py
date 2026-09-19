import json
from decimal import Decimal
import click
import pytest
from panther_journal import soundtrack as s, narration as n, video as v


class Fal:
    def __init__(self):
        self.account='synthetic';self.posts=0;self.events={};self.uncertain=False;self.rate=None
    def billing(self):return dict(account=self.account,balanceUsd='50')
    def billing_events(self,ids):return {k:self.events[k] for k in ids if k in self.events}
    def request(self,method,url,**kw):
        if method=='GET' and url.endswith('/pricing'):
            ep=kw['params']['endpoint_id'];profile=next(p for p in s.PROFILES.values() if p[0]==ep)
            return {'prices':[dict(endpoint_id=ep,currency='USD',unit=profile[1],unit_price=str(self.rate or profile[2]))]}
        self.posts+=1
        if self.uncertain:raise click.ClickException('timeout')
        root=url+'/requests/synthetic-request'
        return dict(request_id='synthetic-request',status_url=root+'/status',response_url=root,cancel_url=root+'/cancel')


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(v,'ROOT',tmp_path/'private')
    with v.database(initialize=True):pass
    fal=Fal();n.create_budget('film','game','15','13','Owner approved',fal)
    m=dict(schemaVersion=1,projectId='film',gameId='game',purpose='audition',text='A fictional line',voice='Brian',direction='Dramatic',sourceKeys=['games/game/assets/script/original/script.json'])
    p=n.prepare(m,fal)
    with v.database() as db:
        db.execute('INSERT INTO narration_attempts VALUES (?,?,?,?,?,?,0)',('old',p['planId'],'film',1000,'COMPLETED',json.dumps({'requestId':'old-request'})))
    fal.events={'old-request':{'endpoint':n.ENDPOINT,'amount':'9.273'}}
    return fal


def manifest(kind='music'):
    return dict(schemaVersion=1,projectId='film',gameId='game',kind=kind,title='Synthetic cue',text='Original dramatic instrumental score',seconds=240 if kind=='music' else 8,sourceKeys=['games/game/assets/script/original/script.json'])


def opened(f):return s.reconcile('film',400,'Owner approved soundtrack and reconciliation',f)


def approved(f,m=None):
    p=s.prepare(m or manifest(),f)
    with v.database() as db:db.execute('UPDATE soundtrack_plans SET approved=1 WHERE id=?',(p['planId'],))
    return p


def test_reconciliation_preserves_history_and_closes_old_writers(setup):
    b=opened(setup)
    assert b['historicalBilledUsd']=='9.273' and b['availableCents']==400
    with v.database() as db:
        assert db.execute('SELECT reserved_cents FROM narration_attempts').fetchone()[0]==1000
        with pytest.raises(click.ClickException):v.assert_generation_open(db,'film')
        v.assert_generation_open(db,'other')
    assert opened(setup)==b


@pytest.mark.parametrize('case',['missing','endpoint','negative','account','unknown'])
def test_bad_evidence_blocks_reconciliation(setup,case):
    if case=='missing':setup.events={}
    if case=='endpoint':setup.events['old-request']['endpoint']='wrong'
    if case=='negative':setup.events['old-request']['amount']='-1'
    if case=='account':setup.account='different'
    if case=='unknown':
        with v.database() as db:db.execute("UPDATE narration_attempts SET state='UNKNOWN'")
    with pytest.raises(click.ClickException):opened(setup)


def test_cap_and_history_conflicts(setup):
    with pytest.raises(click.ClickException):s.reconcile('film',600,'Owner approved',setup)
    opened(setup)
    with v.database() as db:
        db.execute("UPDATE narration_attempts SET reserved_cents=999")
        with pytest.raises(click.ClickException):s.status(db,'film')


def test_rounding_and_no_automatic_retry(setup):
    opened(setup);p=approved(setup)
    assert p['quote']['reserveCents']==300
    first=s.submit(p['planId'],setup)
    assert first['state']=='SUBMITTED' and setup.posts==1
    assert s.submit(p['planId'],setup)==first and setup.posts==1
    with v.database() as db:assert v.has_unresolved(db)


def test_unknown_blocks_every_writer(setup):
    opened(setup);p=approved(setup);setup.uncertain=True
    with pytest.raises(click.ClickException):s.submit(p['planId'],setup)
    with v.database() as db:
        assert v.has_unresolved(db)
        assert s.status(db,'film')['availableCents']==100
    assert s.submit(p['planId'],setup)['state']=='UNKNOWN' and setup.posts==1


def test_price_increase_and_unapproved(setup):
    opened(setup);p=s.prepare(manifest(),setup)
    with pytest.raises(click.ClickException):s.submit(p['planId'],setup)
    p=approved(setup);setup.rate=Decimal('1')
    with pytest.raises(click.ClickException):s.submit(p['planId'],setup)
    assert setup.posts==0


@pytest.mark.parametrize('field,value',[('voice','cloned-id'),('kind','unbounded'),('seconds',241),('sourceKeys',['games/other/assets/script/original/script.json']),('extra','unknown')])
def test_strict_manifest(field,value):
    m=manifest();m[field]=value
    with pytest.raises(click.ClickException):s.validate(m)


def test_speech_is_explicit_stock_cast_not_fake_audition():
    m=manifest('speech');m['voice']='George'
    assert s.payload(s.validate(m))['voice']=='George'
    m['approvedAudition']='invented'
    with pytest.raises(click.ClickException):s.validate(m)
