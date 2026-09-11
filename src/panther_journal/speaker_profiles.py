"""Private, immutable speaker-recognition enrollment and conservative matching.

These embeddings identify speakers; they cannot synthesize their voices.
"""

import math
import json
from pathlib import Path

import click

from panther_journal import recording as audio
from panther_journal.audio_storage import write_json


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
        raise click.ClickException('Empty speaker embedding')
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


def match(embedding, profiles, threshold=0.75, margin=0.15):
    """Cosine similarity is not a probability. Never force the nearest player."""
    target = vector(embedding)
    scores = []
    for person in profiles:
        reference = vector(person['embedding'])
        if len(reference) != len(target):
            raise click.ClickException('Speaker embedding dimensions differ')
        scores.append((sum(a*b for a, b in zip(target, reference)), person['playerId']))
    scores.sort(reverse=True)
    if not scores:
        return None
    best = scores[0][0]
    second = scores[1][0] if len(scores) > 1 else -1
    return scores[0][1] if best >= threshold and best - second >= margin else None


def analyze(wav, model, runtime, attempt):
    from panther_journal.live_transcript import run_process, read_json
    output = attempt / 'speaker-result.json'
    run_process([str(runtime.absolute()), str(Path(__file__).with_name('speaker_profile_worker.py')),
                 '--audio', str(wav), '--model', str(model.resolve()), '--output', str(output)],
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


def label_lines(lines, result, profiles, offset):
    turns = [audio.SpeakerTurn(start=float(t['start']) + offset,
                              end=float(t['end']) + offset, speaker=t['speaker'])
             for t in result['turns']]
    mapping = {label: match(embedding, profiles) for label, embedding in result['embeddings'].items()}
    labeled = audio.attributed_lines(lines, turns, mapping)
    for line in labeled:
        line['attribution'] = 'provisional-enrolled-voice' if line['playerId'] else 'unassigned'
    return labeled


@click.command('enroll-speakers')
@click.argument('manifest', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--output', required=True, type=click.Path(path_type=Path))
@click.option('--runtime', default=audio.DEFAULT_RUNTIME, type=click.Path(exists=True, path_type=Path))
@click.option('--model', default=audio.DEFAULT_SPEAKER_MODEL, type=click.Path(exists=True, path_type=Path))
def enroll(manifest, output, runtime, model):
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
        result = analyze(source, model, runtime, attempt)
        if len(result['embeddings']) != 1 or sum(t['end']-t['start'] for t in result['turns']) < 10:
            raise click.ClickException('Need at least ten seconds of clean, single-speaker speech')
        if audio.digest(source) != sample['sha256']:
            raise click.ClickException('Enrollment audio changed during processing')
        profiles.append({**sample, 'embedding': vector(next(iter(result['embeddings'].values()))),
                         'analysisSha256': audio.digest(attempt / 'speaker-result.json')})
    document = {'schemaVersion': 1, 'entityType': 'SpeakerRecognitionProfiles',
                'gameId': request['gameId'], 'modelFiles': pins, 'profiles': profiles,
                'purpose': 'speaker-recognition-only', 'manifestSha256': manifest_hash}
    # Validate before publishing the immutable revision, including duplicate identities.
    if not profiles or len({p['playerId'] for p in profiles}) != len(profiles) or model_pin(model) != pins or audio.digest(manifest) != manifest_hash:
        raise click.ClickException('Empty/duplicate enrollment or changed model')
    write_json(output, document)
    click.echo(str(output))
