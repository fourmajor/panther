"""Explicit pinned local alternative; anonymous labels are never player identities."""

import json
import time
from pathlib import Path
import subprocess

import click

from panther_journal import recording as audio
from panther_journal.audio_storage import lock, write_json
from panther_journal.speaker_profiles import private_path


def normalize(value, duration):
    from panther_journal.speaker_evaluation import intervals
    turns = []
    for segment in value['segments']:
        intervals([segment])
        # Native runtime may pad the final frame by 10 ms; never expand source duration.
        if segment['end'] > duration + .05 or segment['start'] >= duration:
            raise click.ClickException('Diarization exceeds verified source audio')
        label = segment['speaker']
        if type(label) is not int or not 0 <= label <= 8:
            raise click.ClickException('Invalid Nemotron anonymous speaker label')
        turns.append(dict(start=segment['start'], end=min(segment['end'], duration),
                          speaker=f'NEMOTRON_{label:02}'))
    return turns


@click.command('diarize-nemotron')
@click.argument('folder', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option('--runtime', required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--runtime-sha256', required=True)
@click.option('--model', required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--model-sha256', required=True)
@click.option('--work-dir', required=True, type=click.Path(path_type=Path))
def command(folder, runtime, runtime_sha256, model, model_sha256, work_dir):
    """Run a reviewed native runtime offline; no downloads, ASR, names or publication."""
    record = audio.verified(folder)
    root = private_path(work_dir)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    pins = dict(recordingId=record.id, sourceParts=[p.model_dump() for p in record.parts],
                runtimeSha256=runtime_sha256, modelSha256=model_sha256,
                engine='nvidia/Nemotron-3-Diarization', preset='v3-offline', device='cpu')
    def check():
        if audio.digest(runtime) != runtime_sha256 or audio.digest(model) != model_sha256:
            raise click.ClickException('Reviewed runtime/model checksum differs')
        if audio.verified(folder) != record:
            raise click.ClickException('Verified source audio changed')
    check()
    with lock(root, 'nemotron.lock'):
        pin_path = root / 'inputs.json'
        if pin_path.exists():
            if json.loads(pin_path.read_text()) != pins:
                raise click.ClickException('Analysis inputs changed; use a new work directory')
        else:
            write_json(pin_path, pins)
        result_path = root / 'result.json'
        if result_path.exists():
            result = json.loads(result_path.read_text())
            if (result.get('inputs') != pins
                    or audio.digest(root / 'diarization.json') != result['outputSha256']
                    or audio.digest(root / 'native-output.json') != result['nativeSha256']):
                raise click.ClickException('Saved diarization evidence changed')
            click.echo(str(root / 'diarization.json'))
            return
        if (root / 'native-output.json').exists():
            raise click.ClickException('Partial native result requires inspection; never overwrite it')
        manifest, wave = root / 'concat.txt', root / 'listening-input.wav'
        if manifest.exists() or wave.exists():
            raise click.ClickException('Partial input preparation requires inspection')
        with manifest.open('x') as stream:
            for p in record.parts:
                path = str((folder / p.file).resolve()).replace("'", "'\\''")
                stream.write(f"file '{path}'\n")
        started = time.monotonic()
        subprocess.run([audio.executable('ffmpeg'), '-v', 'error', '-nostdin', '-n', '-f', 'concat',
                        '-safe', '0', '-i', str(manifest), '-ac', '1', '-ar', '16000',
                        '-c:a', 'pcm_s16le', str(wave)], check=True, timeout=3600)
        phase = time.monotonic()
        # A reviewed local file path cannot trigger the runtime's automatic model download.
        with (root / 'native.log').open('x') as log:
            subprocess.run([str(runtime.resolve()), 'diarize', str(wave), '--model', str(model.resolve()),
                            '--device', 'cpu', '--preset', 'v3-offline', '--format', 'json',
                            '--output', str(root / 'native-output.json')], check=True, timeout=24 * 3600,
                           stdout=log, stderr=log)
        check()
        native = json.loads((root / 'native-output.json').read_text())
        output = dict(schemaVersion=1, entityType='SpeakerDiarization', recordingId=record.id,
                      sourceParts=pins['sourceParts'], engine=pins['engine'], modelSha256=model_sha256,
                      runtimeSha256=runtime_sha256, inferenceLocation='local-cpu',
                      turns=normalize(native, sum(p.duration for p in record.parts)),
                      identitiesAssigned=False)
        write_json(root / 'diarization.json', output)
        write_json(result_path, dict(inputs=pins, outputSha256=audio.digest(root / 'diarization.json'),
                                     nativeSha256=audio.digest(root / 'native-output.json'),
                                     inferenceSeconds=time.monotonic() - phase,
                                     elapsedSeconds=time.monotonic() - started,
                                     billedCost=0, costStatus='not-applicable-local-inference'))
        click.echo(str(root / 'diarization.json'))
