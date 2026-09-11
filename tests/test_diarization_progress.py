import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from click.testing import CliRunner
import pytest

from panther_journal.diarization_progress import Progress
from panther_journal.cli import main


def test_real_counters_are_stage_only_and_throttled(tmp_path):
    clock = [0.0]
    path = tmp_path / 'progress.json'
    progress = Progress(path, clock=lambda: clock[0])
    progress('embeddings', object(), total=100, completed=0, file={'secret': object()})
    first = path.read_bytes()
    progress('embeddings', object(), total=100, completed=50)
    assert path.read_bytes() == first
    clock[0] = 3
    progress('embeddings', object(), total=100, completed=85)
    value = json.loads(path.read_text())
    assert value['stagePercent'] == 85 and value['overallPercent'] is None
    assert value['completed'] == 85 and value['total'] == 100
    assert 'secret' not in path.read_text()
    progress('embeddings', object(), total=100, completed=100)
    assert json.loads(path.read_text())['stagePercent'] == 100
    progress('embeddings', object())
    value = json.loads(path.read_text())
    assert value['stage'] == 'clustering' and value['stagePercent'] is None
    assert value['overallPercent'] is None and value['completedStages'] == ['embeddings']
    progress.update('complete', state='complete', force=True)
    assert json.loads(path.read_text())['overallPercent'] == 100
    assert not list(tmp_path.glob('.progress-*.tmp'))


def test_empty_and_overshooting_batch_counts(tmp_path):
    progress = Progress(tmp_path / 'progress.json')
    progress('segmentation', total=0, completed=0)
    assert json.loads(progress.path.read_text())['stagePercent'] is None
    progress('segmentation', total=11, completed=16)
    assert json.loads(progress.path.read_text())['completed'] == 11
    with pytest.raises(ValueError):
        progress.update('embeddings', total=10, completed=float('nan'), force=True)


def test_status_handles_older_runs_without_inventing_percent(tmp_path):
    runner = CliRunner()
    missing = runner.invoke(main, ['recording', 'speaker-status', str(tmp_path)])
    assert missing.exit_code != 0 and 'unknown' in missing.output
    progress = Progress(tmp_path / 'progress.json')
    progress('embeddings', total=200, completed=100)
    result = runner.invoke(main, ['recording', 'speaker-status', str(tmp_path)])
    assert result.exit_code == 0
    assert '100/200 (50.0% of this stage)' in result.output
    assert 'Overall: unknown' in result.output
    value = runner.invoke(main, ['recording', 'speaker-status', str(tmp_path), '--json'])
    assert json.loads(value.output)['completed'] == 100


@pytest.mark.parametrize('failure', [False, True])
def test_worker_wires_hook_and_records_terminal_state(tmp_path, monkeypatch, failure):
    import sys
    from panther_journal import diarization_worker as worker
    model = tmp_path / 'model'
    model.mkdir()
    (model / 'weights.bin').write_bytes(b'synthetic')
    (tmp_path / 'recording.json').write_text(json.dumps({'id': 'synthetic-recording', 'parts': []}))
    output = tmp_path / 'diarization.json'
    monkeypatch.setattr(sys, 'argv', ['worker', '--folder', str(tmp_path), '--model', str(model), '--output', str(output)])
    monkeypatch.setitem(sys.modules, 'numpy', MagicMock())
    monkeypatch.setitem(sys.modules, 'torch', MagicMock())
    monkeypatch.setattr(worker.signal, 'signal', lambda *args: None)

    def pipeline(data, *, hook):
        hook('embeddings', object(), total=10, completed=3)
        if failure:
            raise RuntimeError('Do not leak private exception details')
        hook('embeddings', object(), total=10, completed=10)
        hook('embeddings', object())
        return SimpleNamespace(speaker_diarization=SimpleNamespace(itertracks=lambda **kwargs: []))

    monkeypatch.setitem(sys.modules, 'pyannote.audio', SimpleNamespace(Pipeline=SimpleNamespace(from_pretrained=lambda _: pipeline)))
    if failure:
        with pytest.raises(RuntimeError):
            worker.main()
    else:
        worker.main()
    saved = json.loads((tmp_path / 'progress.json').read_text())
    assert saved['state'] == ('failed' if failure else 'complete')
    assert saved['overallPercent'] == (None if failure else 100)
    if failure:
        assert saved['completed'] == 3 and saved['total'] == 10
    assert output.exists() is not failure
    assert 'private exception' not in (tmp_path / 'progress.json').read_text()
