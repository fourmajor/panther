"""Reuse complete live checkpoints without running speech recognition again."""

from datetime import datetime, timezone
from pathlib import Path
import uuid

import click

from panther_journal import recording as audio, live_transcript as live
from panther_journal.capture_audit import audit


def checkpoint_lines(folder, root, config, parts):
    raw_lines, attributed = [], []
    for part in parts:
        path = root / part.file.replace('.flac', '.json')
        if not path.is_file():
            raise click.ClickException('Live history is incomplete; resume --from-start before finalizing')
        value = live.process_part(folder, Path('/unused'), root, config, part)
        if any(line.get('kind') == 'preview-gap' for line in value['segments']):
            raise click.ClickException('Live history has recognition gaps; retain evidence and reprocess those intervals first')
        for line in value['segments']:
            source = {**line, 'sourceParts': [part.file]}
            source.pop('sourcePart', None)
            attributed.append(source)
            raw = {**source, 'playerId': None, 'attribution': 'unassigned'}
            raw.pop('speakerLabel', None)
            raw_lines.append(raw)
    return raw_lines, attributed


@click.command('finish-live')
@click.argument('preview', type=click.Path(exists=True, file_okay=False, path_type=Path))
def finish_live(preview):
    """Create local raw/attributed transcript versions from complete live checkpoints; no uploads."""
    from panther_journal.speaker_profiles import private_path
    root = private_path(preview).resolve()
    folder = root.parent.parent
    if root.parent.name != 'live-preview' or live.capture_running(folder):
        raise click.ClickException('Finish capture before finalizing its live preview')
    record = audio.verified(folder)
    config = live.read_json(root / 'preview.json')
    if config['settings']['recordingId'] != record.id or config['settings']['captureSha256'] != audio.digest(folder / 'capture.json'):
        raise click.ClickException('Live preview belongs to different capture evidence')
    raw_lines, attributed = checkpoint_lines(folder, root, config, record.parts)
    game = audio.cloud.api(audio.cloud.configuration(), 'GET', '/game', params={'gameId': record.gameId})
    ids = {p['id'] for p in game['players']}
    if any(line.get('playerId') and line['playerId'] not in ids for line in attributed):
        raise click.ClickException('An attributed player is not in this game roster')
    run_id = f'transcript-{uuid.uuid4().hex}'
    doc = {'schemaVersion': 1, 'entityType': 'PlayerTranscript', 'artifactType': 'raw-transcript',
           'id': run_id, 'gameId': record.gameId, 'sessionId': record.sessionId,
           'recordingId': record.id, 'sourceParts': [p.model_dump() for p in record.parts],
           'captureIntegrity': audit(folder), 'engine': 'whisper.cpp',
           'modelSha256': config['settings']['modelSha256'], 'createdAt': datetime.now(timezone.utc).isoformat(),
           'reviewStatus': 'unreviewed', 'speakerMethod': 'unassigned', 'players': game['players'],
           'segments': raw_lines, 'liveEvidence': {'previewId': root.name,
           'configSha256': audio.digest(root / 'preview.json'),
           'chunks': {p.file: audio.digest(root / p.file.replace('.flac', '.json')) for p in record.parts}},
           'isolation': {'method': 'completed-live-chunks', 'readingScriptUsed': False}}
    target = folder / run_id
    target.mkdir(mode=0o700)
    audio.save_transcript(target, doc)
    click.echo(str(target))
    if any(line.get('playerId') for line in attributed):
        new_id = f'transcript-{uuid.uuid4().hex}'
        derived = {**doc, 'id': new_id, 'segments': attributed, 'reviewStatus': 'provisional',
                   'sourceTranscriptId': run_id, 'sourceTranscriptSha256': audio.digest(target / f'{run_id}.json'),
                   'speakerMethod': 'provisional-enrolled-voice',
                   'speakerRecognition': config['settings'].get('speakerRecognition')}
        destination = folder / new_id
        destination.mkdir(mode=0o700)
        audio.save_transcript(destination, derived)
        click.echo(str(destination))
    click.echo('Saved locally; no inference rerun, upload or editorial trigger. Speaker labels remain provisional.')
