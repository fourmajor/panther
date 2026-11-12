"""Private, immutable speaker-recognition enrollment and conservative matching.

These embeddings identify speakers; they cannot synthesize their voices.
"""

import math
import json
from pathlib import Path

import click

from panther_journal import recording as audio
from panther_journal.audio_storage import write_json


class EmptySpeakerEmbedding(click.ClickException):
    """The analyzer detected a turn without usable identity evidence."""


def model_pin(model):
    files = {str(p.relative_to(model)): audio.digest(p) for p in sorted(model.rglob('*'))
             if p.is_file() and p.suffix in {'.bin', '.npz', '.yaml'}}
    if not files:
        raise click.ClickException('Local speaker model weights are missing')
    return files


def private_path(path):
    path = path.expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or any((p / '.git').exists() for p in (path, *path.parents)):
        raise click.ClickException('Voice data must be private and outside Git')
    return path


def vector(value):
    if not isinstance(value, list) or not 16 <= len(value) <= 4096 or any(
        type(x) not in (int, float) or not math.isfinite(x) for x in value
    ):
        raise click.ClickException('Invalid speaker embedding')
    norm = math.sqrt(sum(x*x for x in value))
    if norm < 1e-8:
        raise EmptySpeakerEmbedding('Empty speaker embedding')
    return [x / norm for x in value]


def load_profiles(path, game_id, model):
    from panther_journal.live_transcript import read_json
    value = read_json(private_path(path), 4 * 1024 * 1024)
    if value.get('schemaVersion') != 1 or value.get('entityType') != 'SpeakerRecognitionProfiles' or value.get('gameId') != game_id:
        raise click.ClickException('Speaker profiles belong to a different game or schema')
    if value.get('modelFiles') != model_pin(model):
        raise click.ClickException('Speaker profile/model mismatch; enroll with these weights')
    people = value.get('profiles')
    if not isinstance(people, list) or not 1 <= len(people) <= 20:
        raise click.ClickException('Invalid speaker profile roster')
    ids, dimensions = set(), set()
    for person in people:
        audio.cloud.slug(person['playerId'])
        if person['playerId'] in ids or not person.get('identityEvidence'):
            raise click.ClickException('Duplicate or unconfirmed player enrollment')
        ids.add(person['playerId'])
        dimensions.add(len(vector(person['embedding'])))
    if len(dimensions) != 1:
        raise click.ClickException('Speaker embedding dimensions differ')
    return value


def identity_scores(embedding, profiles, threshold=0.75, margin=0.15):
    """Cosine similarity is not a probability. Never force the nearest player."""
    target = vector(embedding)
    scores = []
    for person in profiles:
        reference = vector(person['embedding'])
        if len(reference) != len(target):
            raise click.ClickException('Speaker embedding dimensions differ')
        scores.append((sum(a * b for a, b in zip(target, reference)), person['playerId']))
    scores.sort(reverse=True)
    best = scores[0][0] if scores else None
    second = scores[1][0] if len(scores) > 1 else None
    player = None
    if scores and best >= threshold and best - (second if second is not None else -1) >= margin:
        player = scores[0][1]
    return player, best, second


MATCH_COSINE = 0.75
MATCH_MARGIN = 0.1
REENROLL_HINT = (
    'Absolute speaker scores are low. Re-enroll profiles from clean single-speaker samples.'
)


def _accepted(score, runner_up):
    """A clear lead, or a strong cosine. An exact tie is not a person."""
    if runner_up is not None and score - runner_up <= 1e-6:
        return False
    if score >= MATCH_COSINE:
        return True
    return runner_up is not None and score - runner_up >= MATCH_MARGIN


def _minimize(cost):
    """Column chosen for each row of a square cost matrix."""
    n = len(cost)
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [float('inf')] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float('inf')
            j1 = 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    assignment = [-1] * n
    for j in range(1, n + 1):
        if p[j]:
            assignment[p[j] - 1] = j - 1
    return assignment


def _assign_players(rows):
    """One player per speaker. rows are (label, scores highest first)."""
    players = []
    seen = set()
    for _label, scores in rows:
        for _score, player in scores:
            if player not in seen:
                seen.add(player)
                players.append(player)
    if not rows or not players:
        return {label: None for label, _scores in rows}
    n = max(len(rows), len(players))
    cost = [[0.0] * n for _ in range(n)]
    index = {player: column for column, player in enumerate(players)}
    for row, (_label, scores) in enumerate(rows):
        for score, player in scores:
            cost[row][index[player]] = -score
    chosen = _minimize(cost)
    assigned = {}
    for row, (_label, scores) in enumerate(rows):
        column = chosen[row]
        if column < 0 or column >= len(players):
            assigned[rows[row][0]] = None
            continue
        player = players[column]
        assigned[rows[row][0]] = (player, next(score for score, name in scores if name == player))
    return assigned


def match(embedding, profiles, threshold=0.75, margin=0.15):
    """Cosine similarity is not a probability. Never force the nearest player."""
    player, _best, _second = identity_scores(embedding, profiles, threshold, margin)
    return player


def analyze(wav, model, runtime, attempt, *, reference=False):
    from panther_journal.live_transcript import run_process, read_json
    output = attempt / 'speaker-result.json'
    run_process([str(runtime.absolute()), str(Path(__file__).with_name('speaker_profile_worker.py')),
                 '--audio', str(wav), '--model', str(model.resolve()), '--output', str(output),
                 *(['--reference'] if reference else [])],
                attempt, 'speaker.log', timeout=180)
    return read_json(output, 4 * 1024 * 1024)


class SpeakerWorker:
    """One resident, low-priority process per live preview; no listening socket or credentials."""

    def __init__(self, root, model, runtime):
        self.root, self.model, self.runtime = root, model, runtime
        self.child = self.log = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        import os
        import signal
        import subprocess
        if self.child is not None and self.child.poll() is None:
            os.killpg(self.child.pid, signal.SIGTERM)
            try:
                self.child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(self.child.pid, signal.SIGKILL)
                self.child.wait()
        if self.child is not None and self.child.stdin:
            self.child.stdin.close()
        if self.log:
            self.log.close()
        self.child = self.log = None

    def analyze(self, wav, attempt):
        import subprocess
        import time
        import uuid
        from panther_journal.live_transcript import read_json
        from panther_journal.model_workflow import clean_environment
        if self.child is None:
            self.log = (self.root / f'speaker-worker-{uuid.uuid4().hex}.log').open('xb')
            self.child = subprocess.Popen([audio.executable('nice'), '-n', '15', str(self.runtime.absolute()),
                str(Path(__file__).with_name('speaker_profile_worker.py')), '--serve', '--model', str(self.model.resolve())],
                stdin=subprocess.PIPE, stdout=self.log, stderr=self.log, start_new_session=True,
                env={**clean_environment(), 'OMP_NUM_THREADS': '2', 'VECLIB_MAXIMUM_THREADS': '2'}, text=True)
        output = attempt / 'speaker-result.json'
        if output.exists():
            raise click.ClickException('Speaker output already exists')
        started = time.monotonic()
        try:
            self.child.stdin.write(json.dumps({'audio': str(wav), 'output': str(output)}) + '\n')
            self.child.stdin.flush()
            while not output.exists():
                if self.child.poll() is not None or time.monotonic() - started > 180:
                    raise click.ClickException('Local speaker worker failed or timed out')
                time.sleep(0.1)
            return read_json(output, 4 * 1024 * 1024)
        except BaseException:
            self.close()
            raise


def map_speakers(result, profiles):
    """Match enrolled voices. Unavailable or empty embeddings stay unknown for that label only."""
    mapping, unavailable, reports = {}, set(), []
    pending = []
    embeddings = result.get('embeddings')
    if not isinstance(embeddings, dict):
        raise click.ClickException('Session-wide speaker embeddings are missing; rerun the separate speaker pass')
    for label, embedding in embeddings.items():
        evidence = result.get('unavailableEmbeddings', {}).get(label, {})
        report = {
            'speaker': label,
            'playerId': None,
            'bestCosine': None,
            'runnerUpCosine': None,
            'unavailable': False,
        }
        if embedding is None:
            reason = evidence.get('reason')
            if reason == 'non-finite-runtime-output':
                values = evidence.get('values')
                if not isinstance(values, list) or not 16 <= len(values) <= 4096 or not any(
                    x in ('nan', 'inf', '-inf') for x in values
                ):
                    raise click.ClickException('Invalid unavailable speaker evidence')
            elif reason not in {
                'insufficient-exclusive-speech',
                'reference-extraction-failed',
                'malformed-reference-embedding',
                'empty-embedding',
            }:
                raise click.ClickException('Invalid unavailable speaker evidence')
            mapping[label] = None
            unavailable.add(label)
            report.update(unavailable=True, reason=reason)
            reports.append(report)
            continue
        try:
            candidate = vector(embedding)
        except EmptySpeakerEmbedding:
            # Very short/contaminated turns can produce an all-zero runtime
            # vector. Keep speech and the original result; never force identity.
            mapping[label] = None
            unavailable.add(label)
            report.update(unavailable=True, reason='empty-embedding')
            reports.append(report)
            continue
        scores = []
        for person in profiles:
            reference = vector(person['embedding'])
            if len(reference) != len(candidate):
                raise click.ClickException('Speaker embedding dimensions differ')
            scores.append((sum(a * b for a, b in zip(candidate, reference)), person['playerId']))
        scores.sort(key=lambda item: item[0], reverse=True)
        pending.append((label, scores, report))
    assigned = _assign_players([(label, scores) for label, scores, _report in pending])
    for label, scores, report in pending:
        pair = assigned.get(label)
        player = None
        matched = None
        if pair:
            matched_player, matched = pair
            others = [score for score, name in scores if name != matched_player]
            runner_up = max(others) if others else None
            if _accepted(matched, runner_up):
                player = matched_player
        mapping[label] = player
        report.update(
            playerId=player,
            bestCosine=scores[0][0] if scores else None,
            runnerUpCosine=scores[1][0] if len(scores) > 1 else None,
        )
        if player and matched is not None and matched < MATCH_COSINE:
            report['reenroll'] = True
        reports.append(report)
    return mapping, unavailable, reports


def label_lines(lines, result, profiles, offset):
    turns = [audio.SpeakerTurn(start=float(t['start']) + offset,
                              end=float(t['end']) + offset, speaker=t['speaker'])
             for t in result['turns']]
    mapping, unavailable, _reports = map_speakers(result, profiles)
    labeled = audio.attributed_lines(lines, turns, mapping)
    for line in labeled:
        line['attribution'] = 'provisional-enrolled-voice' if line['playerId'] else 'unassigned'
        if any(t.speaker in unavailable and t.start < line['end'] and t.end > line['start'] for t in turns):
            line['attributionWarnings'] = ['Detected speech has no usable speaker embedding; identity remains unassigned.']
    return labeled


@click.command('enroll-speakers')
@click.argument('manifest', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--output', required=True, type=click.Path(path_type=Path))
@click.option('--runtime', default=audio.DEFAULT_RUNTIME, type=click.Path(exists=True, path_type=Path))
@click.option('--model', default=audio.DEFAULT_SPEAKER_MODEL, type=click.Path(exists=True, path_type=Path))
@click.option('--minimum-speech-seconds', default=10.0, type=click.FloatRange(3, 120),
              help='Explicitly accept shorter confirmed samples (lower evidence quality); default 10 seconds.')
def enroll(manifest, output, runtime, model, minimum_speech_seconds):
    """Enroll explicitly identified, clean single-speaker WAV samples from a private manifest."""
    from panther_journal.live_transcript import read_json
    import os
    import uuid
    os.umask(0o077)
    output = private_path(output)
    if output.exists():
        raise click.ClickException('Profile revision already exists; choose a new output')
    request = read_json(private_path(manifest))
    manifest_hash = audio.digest(manifest)
    if not isinstance(request.get('samples'), list) or not 1 <= len(request['samples']) <= 20:
        raise click.ClickException('Enroll between one and twenty players')
    game = audio.cloud.api(audio.cloud.configuration(), 'GET', '/game', params={'gameId': request['gameId']})
    roster = {p['id'] for p in game['players']}
    pins = model_pin(model)
    profiles = []
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for sample in request['samples']:
        if sample['playerId'] not in roster or not sample.get('identityEvidence') or sample.get('confirmedSingleSpeaker') is not True:
            raise click.ClickException('Confirm the player identity and clean single-speaker sample first')
        source = private_path(Path(sample['file']))
        if audio.digest(source) != sample['sha256']:
            raise click.ClickException('Enrollment source checksum changed')
        attempt = output.parent / f'enrollment-{uuid.uuid4().hex}'
        attempt.mkdir(mode=0o700)
        result = analyze(source, model, runtime, attempt, reference=True)
        speech_seconds = sum(t['end']-t['start'] for t in result['turns'])
        if len(result['embeddings']) != 1 or speech_seconds < minimum_speech_seconds:
            raise click.ClickException(f'Need at least {minimum_speech_seconds:g} seconds of clean, single-speaker speech')
        if audio.digest(source) != sample['sha256']:
            raise click.ClickException('Enrollment audio changed during processing')
        if result.get('referenceEmbeddingMethod') != 'community-1-confirmed-full-waveform-v1':
            raise click.ClickException('Confirmed reference extraction evidence is missing')
        profiles.append({**sample, 'embedding': vector(result['referenceEmbedding']),
                         'embeddingMethod': result['referenceEmbeddingMethod'],
                         'analysisSha256': audio.digest(attempt / 'speaker-result.json'),
                         'detectedSpeechSeconds': speech_seconds,
                         'sampleQuality': 'short-confirmed-reference' if speech_seconds < 10 else 'standard-reference'})
    document = {'schemaVersion': 1, 'entityType': 'SpeakerRecognitionProfiles',
                'gameId': request['gameId'], 'modelFiles': pins, 'profiles': profiles,
                'purpose': 'speaker-recognition-only', 'manifestSha256': manifest_hash}
    # Validate before publishing the immutable revision, including duplicate identities.
    if not profiles or len({p['playerId'] for p in profiles}) != len(profiles) or model_pin(model) != pins or audio.digest(manifest) != manifest_hash:
        raise click.ClickException('Empty/duplicate enrollment or changed model')
    if any(match(p['embedding'], profiles) != p['playerId'] for p in profiles):
        raise click.ClickException('Confirmed references are ambiguous against the enrolled roster')
    write_json(output, document)
    click.echo(str(output))
