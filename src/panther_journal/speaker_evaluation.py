"""Private, duration-based speaker evaluation; never converts coverage into accuracy."""

import math
from collections import Counter
from pathlib import Path

import click

from panther_journal.audio_storage import write_json
from panther_journal.speaker_profiles import private_path, vector


def intervals(rows):
    result = []
    for row in rows:
        start, end = row['start'], row['end']
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start):
            raise click.ClickException('Invalid evaluation interval')
        result.append(row)
    return result


class _PredictionSweep:
    """Visit prediction boundaries once across ordered, non-overlapping truth."""

    def __init__(self, prediction):
        self.events = sorted(
            [(p[edge], p.get('playerId'), delta)
             for p in prediction for edge, delta in (('start', 1), ('end', -1))],
            key=lambda event: event[0],
        )
        self.cursor = 0
        self.active = Counter()

    def advance(self, time):
        while self.cursor < len(self.events) and self.events[self.cursor][0] <= time:
            _, player, delta = self.events[self.cursor]
            self.active[player] += delta
            if not self.active[player]:
                del self.active[player]
            self.cursor += 1

    def pieces(self, start, end):
        self.advance(start)
        position = start
        while self.cursor < len(self.events) and self.events[self.cursor][0] < end:
            boundary = self.events[self.cursor][0]
            yield position, boundary, set(self.active)
            self.advance(boundary)
            position = boundary
        yield position, end, set(self.active)


def evaluate(reference, prediction):
    """Score only explicit named single-speaker/playback truth, not inferred ground truth."""
    reference, prediction = intervals(reference), intervals(prediction)
    ordered = sorted(reference, key=lambda r: r['start'])
    if any(a['end'] > b['start'] for a, b in zip(ordered, ordered[1:])):
        raise click.ClickException('Reference intervals overlap; score overlapping voices separately')
    totals = dict(correctSeconds=0.0, wrongSeconds=0.0, unknownSeconds=0.0,
                  playbackSeconds=0.0, playbackWronglyNamedSeconds=0.0)
    people = {}
    sweep = _PredictionSweep(prediction)
    for truth in ordered:
        if not truth.get('identityEvidence') or truth.get('confirmed') is not True:
            raise click.ClickException('Evaluation truth must be independently confirmed')
        player = truth.get('playerId')
        if not player and truth.get('context') != 'playback':
            raise click.ClickException('Unknown identity is not accuracy ground truth')
        per = people.setdefault(player, dict(correctSeconds=0.0, wrongSeconds=0.0, unknownSeconds=0.0)) if player else None
        for a, b, active in sweep.pieces(truth['start'], truth['end']):
            duration = b - a
            if not player:
                totals['playbackSeconds'] += duration
                if active - {None}:
                    totals['playbackWronglyNamedSeconds'] += duration
                continue
            # Conflicting/mixed predicted identities count wrong, never majority-vote them away.
            status = 'unknownSeconds' if not active or active == {None} else 'correctSeconds' if active == {player} else 'wrongSeconds'
            totals[status] += duration
            per[status] += duration
    seconds = sum(totals[k] for k in ('correctSeconds', 'wrongSeconds', 'unknownSeconds'))
    return {**totals, 'evaluatedPlayerSeconds': seconds,
            'correctPercent': 100 * totals['correctSeconds'] / seconds if seconds else None,
            'wrongPercent': 100 * totals['wrongSeconds'] / seconds if seconds else None,
            'unknownPercent': 100 * totals['unknownSeconds'] / seconds if seconds else None,
            'perPlayer': people, 'scope': 'Confirmed evaluation intervals only; not full-session accuracy'}


def identify(embedding, references, *, threshold, margin, minimum_references=2):
    """Open-set match against multiple distinct confirmed references; never learn from guesses."""
    if not (-1 <= threshold <= 1 and 0 <= margin <= 2 and minimum_references >= 2):
        raise click.ClickException('Invalid identity policy')
    target = vector(embedding)
    groups, pins, sources = {}, set(), []
    for ref in references:
        if (ref.get('confirmed') is not True or not ref.get('identityEvidence')
                or not ref.get('sourceSha256') or ref.get('origin') != 'confirmed-reference'):
            raise click.ClickException('Unconfirmed or automatically learned identity reference')
        pin = (ref['sourceSha256'], ref.get('start'), ref.get('end'))
        if pin in pins:
            raise click.ClickException('Duplicate reference cannot count as independent support')
        intervals([ref])
        if any(old['sourceSha256'] == ref['sourceSha256'] and old['start'] < ref['end']
               and old['end'] > ref['start'] for old in sources):
            raise click.ClickException('Overlapping references cannot count as independent support')
        pins.add(pin)
        sources.append(ref)
        v = vector(ref['embedding'])
        if len(v) != len(target):
            raise click.ClickException('Recognition model spaces differ')
        groups.setdefault(ref['playerId'], []).append(sum(a * b for a, b in zip(v, target)))
    scores = sorted(((sorted(values, reverse=True)[minimum_references - 1], person)
                     for person, values in groups.items() if len(values) >= minimum_references), reverse=True)
    if len(scores) != len(groups):
        return {'playerId': None, 'reason': 'insufficient-reference-support'}
    if not scores:
        return {'playerId': None, 'reason': 'no-reference-support'}
    best, person = scores[0]
    # Weak secondary enrollment must not hide a strong competing identity.
    runner = max((max(values) for other, values in groups.items() if other != person), default=-1)
    return {'playerId': person if best >= threshold and best - runner >= margin else None,
            'score': best, 'runnerUp': runner, 'scoreIsProbability': False}


def calibrate(references, validation, candidates):
    """Propose a policy only from disjoint confirmed holds and unknown-speaker negatives."""
    intervals(references)
    intervals(validation)
    people = {r['playerId'] for r in references}
    counts = {p: 0 for p in people}
    negatives = 0
    seen = []
    for sample in validation:
        if sample.get('confirmed') is not True or not sample.get('identityEvidence'):
            raise click.ClickException('Calibration needs confirmed held-out identity evidence')
        if sample.get('playerId') not in people | {None} or not sample.get('sourceSha256'):
            raise click.ClickException('Invalid held-out identity or source pin')
        if any(r['sourceSha256'] == sample['sourceSha256'] and r['start'] < sample['end']
               and r['end'] > sample['start'] for r in references):
            raise click.ClickException('Held-out audio overlaps enrollment')
        if any(r['sourceSha256'] == sample['sourceSha256'] and r['start'] < sample['end']
               and r['end'] > sample['start'] for r in seen):
            raise click.ClickException('Held-out samples overlap or repeat')
        seen.append(sample)
        if sample.get('playerId'):
            counts[sample['playerId']] += 1
        else:
            negatives += 1
    # This is a minimum data guard, not a statistical guarantee of a false-match rate.
    if negatives < 10 or any(n < 5 for n in counts.values()):
        return {'status': 'insufficient-independent-evidence', 'perPlayerSamples': counts,
                'negativeSamples': negatives, 'activated': False}
    reports = []
    for threshold, margin in candidates:
        correct = wrong = unknown = false_positive = 0
        for sample in validation:
            found = identify(sample['embedding'], references, threshold=threshold, margin=margin)['playerId']
            if found is not None and sample.get('playerId') is None:
                false_positive += 1
            if sample.get('playerId'):
                if found == sample['playerId']:
                    correct += 1
                elif found:
                    wrong += 1
                else:
                    unknown += 1
        reports.append(dict(threshold=threshold, margin=margin, correct=correct, wrong=wrong,
                            unknown=unknown, falsePositiveNegatives=false_positive))
    passing = [r for r in reports if not r['wrong'] and not r['falsePositiveNegatives'] and r['correct']]
    chosen = max(passing, key=lambda r: (r['correct'], r['threshold'], r['margin'])) if passing else None
    return {'status': 'candidate-requires-separate-test' if chosen else 'no-policy-passes',
            'candidate': chosen, 'evaluations': reports, 'activated': False,
            'limitation': 'Observed validation error is not a population guarantee; test on separate audio before activation.'}


@click.command('evaluate-speakers')
@click.argument('evidence', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--output', required=True, type=click.Path(path_type=Path))
def command(evidence, output):
    """Evaluate private confirmed intervals without audio upload, inference or mutation."""
    from panther_journal.live_transcript import read_json
    import hashlib
    evidence, output = private_path(evidence), private_path(output)
    data = read_json(evidence, 16 * 1024 * 1024)
    if data.get('schemaVersion') != 1 or not data.get('recordingSha256') or not data.get('modelPins'):
        raise click.ClickException('Missing pinned evaluation evidence')
    result = evaluate(data['reference'], data['prediction'])
    result.update(schemaVersion=1, evidenceSha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
                  modelPins=data['modelPins'], recordingSha256=data['recordingSha256'])
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_json(output, result)
    click.echo(str(output))
