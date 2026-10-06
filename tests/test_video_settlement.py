import copy
import json

import click
from click.testing import CliRunner
import pytest

from panther_journal import narration as n, video as v, video_settlement as s
from panther_journal.cli import main
from test_video import setup, manifest  # noqa: F401


def completed(fal, monkeypatch):
    n.create_budget('test-film', 'synthetic-game', '10', '5.50', 'Original approval', fal)
    m = manifest()
    m['projectId'] = 'test-film'
    pid = v.prepare(m, fal)['planId']
    result = CliRunner().invoke(main, ['video', 'approve', pid, '--models-and-rights-approved', '--auto-topup-disabled'])
    assert result.exit_code == 0, result.output
    a = v.submit(pid, 'scene-veo', 1, '', fal)
    v.update_attempt(a['attemptId'], 'COMPLETED', {})
    monkeypatch.setattr(fal, 'billing_events', lambda ids: {'synthetic-request': {'endpoint': v.PROFILES['veo-3.1-fast']['endpoint'], 'amount': '0.504'}}, raising=False)
    return pid, a


def test_settlement_preserves_originals_closes_old_plan_and_protects_total(setup, monkeypatch):  # noqa: F811
    pid, a = completed(setup, monkeypatch)
    with v.database() as db:
        original = dict(db.execute('SELECT * FROM attempts').fetchone())
        allocation = db.execute('SELECT content FROM narration_budgets').fetchone()[0]
    audit = s.settle('test-film', 999, 'Owner approved replacement', setup)
    assert audit['historicalBilledCents'] == 51
    assert s.settle('test-film', 999, 'Owner approved replacement', setup) == audit
    with v.database() as db:
        assert dict(db.execute('SELECT * FROM attempts').fetchone()) == original
        assert db.execute('SELECT content FROM narration_budgets').fetchone()[0] == allocation
        assert v.reserved_for(db, 'test-film') == 51
        assert v.totals(db)['reservationCents'] == 0
        budget = n.budget_status(db, 'test-film')
        assert budget['capCents'] == 1000 and budget['availableNarrationCents'] == 1
        with pytest.raises(click.ClickException, match='closed'):
            v.check_budget(db, v.read_plan(db, pid)[0], 1)
        changed = copy.deepcopy(v.read_plan(db, pid)[0])
        changed['manifest']['shots'][0]['prompt'] += ' New approved composition.'
        v.check_budget(db, changed, 948)
        with pytest.raises(click.ClickException, match='allowance'):
            v.check_budget(db, changed, 949)
    assert v.submit(pid, 'scene-veo', 1, '', setup)['attemptId'] == a['attemptId']
    with pytest.raises(click.ClickException, match='closed'):
        v.submit(pid, 'scene-veo', 2, 'Would retry closed plan', setup)
    assert len(setup.posts) == 1


@pytest.mark.parametrize('failure', ['missing', 'foreign', 'negative', 'overcharge', 'account', 'unresolved', 'cap'])
def test_settlement_fails_closed_without_releasing_headroom(setup, monkeypatch, failure):  # noqa: F811
    _, a = completed(setup, monkeypatch)
    allowance = 999
    if failure == 'missing':
        monkeypatch.setattr(setup, 'billing_events', lambda ids: {})
    elif failure in {'foreign', 'negative', 'overcharge'}:
        event = {'endpoint': 'wrong' if failure == 'foreign' else v.PROFILES['veo-3.1-fast']['endpoint'], 'amount': '-1' if failure == 'negative' else '9' if failure == 'overcharge' else '0.5'}
        monkeypatch.setattr(setup, 'billing_events', lambda ids: {'synthetic-request': event})
    elif failure == 'account':
        setup.account = 'another-account'
    elif failure == 'unresolved':
        v.update_attempt(a['attemptId'], 'UNKNOWN', {})
    elif failure == 'cap':
        allowance = 1001
    with pytest.raises(click.ClickException):
        s.settle('test-film', allowance, 'Owner approved replacement', setup)
    with v.database() as db:
        assert s.audit(db, 'test-film') is None
        assert v.reserved_for(db, 'test-film') == 150


def test_settlement_detects_changed_evidence_and_allocation(setup, monkeypatch):  # noqa: F811
    _, a = completed(setup, monkeypatch)
    s.settle('test-film', 999, 'Owner approved replacement', setup)
    with v.database() as db:
        value = json.loads(db.execute('SELECT content FROM attempts WHERE id=?', (a['attemptId'],)).fetchone()[0])
        value['requestId'] = 'changed'
        db.execute('UPDATE attempts SET content=? WHERE id=?', (json.dumps(value), a['attemptId']))
        with pytest.raises(click.ClickException, match='changed'):
            v.reserved_for(db, 'test-film')
