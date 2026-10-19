"""Synthetic parity oracle and reproducible benchmark fixture; no audio or identities."""

import random

import pytest

from panther_journal.speaker_evaluation import evaluate


def scan_oracle(reference, prediction):
    """Original boundary/active-set semantics, deliberately slow and easy to inspect."""
    totals = dict(correctSeconds=0.0, wrongSeconds=0.0, unknownSeconds=0.0,
                  playbackSeconds=0.0, playbackWronglyNamedSeconds=0.0)
    people = {}
    for truth in sorted(reference, key=lambda r: r['start']):
        player = truth['playerId']
        cuts = {truth['start'], truth['end']}
        for p in prediction:
            if p['start'] < truth['end'] and p['end'] > truth['start']:
                cuts.update((max(p['start'], truth['start']), min(p['end'], truth['end'])))
        cuts = sorted(cuts)
        per = people.setdefault(player, dict(correctSeconds=0.0, wrongSeconds=0.0, unknownSeconds=0.0)) if player else None
        for a, b in zip(cuts, cuts[1:]):
            active = {p.get('playerId') for p in prediction if p['start'] < b and p['end'] > a}
            duration = b - a
            if not player:
                totals['playbackSeconds'] += duration
                if active - {None}:
                    totals['playbackWronglyNamedSeconds'] += duration
            else:
                status = 'unknownSeconds' if not active or active == {None} else 'correctSeconds' if active == {player} else 'wrongSeconds'
                totals[status] += duration
                per[status] += duration
    return totals, people


def fixture(seed, count=30):
    rng = random.Random(seed)
    reference, prediction = [], []
    for i in range(count):
        player = rng.choice(['alpha', 'beta', None])
        reference.append(dict(start=i * 4, end=i * 4 + rng.choice([1, 2, 4]),
                              playerId=player, confirmed=True, identityEvidence='Synthetic fixture',
                              context='playback' if player is None else 'speech'))
    for _ in range(count * 2):
        start = rng.randrange(count * 8) / 2
        prediction.append(dict(start=start, end=start + rng.choice([.5, 1, 8, count * 4]),
                               playerId=rng.choice(['alpha', 'beta', 'gamma', None])))
    prediction += prediction[:3]  # Duplicate same-identity intervals need reference counts.
    rng.shuffle(reference)
    rng.shuffle(prediction)
    return reference, prediction


@pytest.mark.parametrize('seed', range(100))
def test_sweep_matches_original_metrics_for_overlaps_gaps_and_playback(seed):
    reference, prediction = fixture(seed)
    expected, people = scan_oracle(reference, prediction)
    actual = evaluate(reference, prediction)
    assert {key: actual[key] for key in expected} == expected
    assert actual['perPlayer'] == people


def test_touching_boundaries_and_duplicate_overlapping_identity():
    reference = [dict(start=0, end=2, playerId='alpha', confirmed=True, identityEvidence='Fixture'),
                 dict(start=2, end=4, playerId='beta', confirmed=True, identityEvidence='Fixture')]
    prediction = [dict(start=0, end=2, playerId='alpha'), dict(start=1, end=2, playerId='alpha'),
                  dict(start=2, end=4, playerId='beta')]
    assert evaluate(reference, prediction)['correctPercent'] == 100
    assert evaluate(reference, [])['unknownPercent'] == 100
    assert evaluate([], prediction)['evaluatedPlayerSeconds'] == 0
