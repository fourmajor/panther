import click
import pytest
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from click.testing import CliRunner

from panther_journal.speaker_evaluation import calibrate, evaluate, identify
from panther_journal.nemotron_diarization import normalize
from panther_journal import nemotron_diarization as native


def row(a, b, person=None, **extra):
    return dict(start=a, end=b, playerId=person, **extra)


def ref(person, n, v):
    return row(0, 10, person, confirmed=True, identityEvidence='Confirmed synthetic fixture',
               sourceSha256=str(n), origin='confirmed-reference', embedding=v)


X, Y = [1, 0] + [0] * 14, [0, 1] + [0] * 14


def test_duration_metrics_and_playback_separate_from_unknown():
    truth = [row(0, 10, 'alex', confirmed=True, identityEvidence='Fixture'),
             row(10, 14, confirmed=True, identityEvidence='Fixture', context='playback')]
    result = evaluate(truth, [row(0, 3, 'alex'), row(3, 5, 'sam'), row(10, 12, 'alex')])
    assert result['correctPercent'] == 30
    assert result['wrongPercent'] == 20
    assert result['unknownPercent'] == 50
    assert result['playbackWronglyNamedSeconds'] == 2


def test_conflicting_prediction_not_hidden_by_majority():
    result = evaluate([row(0, 4, 'alex', confirmed=True, identityEvidence='Fixture')],
                      [row(0, 4, 'alex'), row(1, 2, 'sam')])
    assert result['wrongSeconds'] == 1


def test_two_references_required_and_no_pseudolabels():
    refs = [ref('alex', 1, X), ref('alex', 2, X), ref('sam', 3, Y), ref('sam', 4, Y)]
    assert identify(X, refs, threshold=.75, margin=.15)['playerId'] == 'alex'
    assert identify(X, refs[:-1], threshold=.75, margin=.15)['playerId'] is None
    with pytest.raises(click.ClickException, match='automatically'):
        identify(X, [{**refs[0], 'origin': 'provisional-match'}], threshold=.75, margin=.15)
    with pytest.raises(click.ClickException, match='Duplicate'):
        identify(X, [refs[0], refs[0]], threshold=.75, margin=.15)
    with pytest.raises(click.ClickException, match='Overlapping'):
        identify(X, [refs[0], {**refs[0], 'start': 1}], threshold=.75, margin=.15)


def test_calibration_cannot_use_training_audio_or_small_evidence():
    refs = [ref('alex', 1, X), ref('alex', 2, X)]
    with pytest.raises(click.ClickException, match='overlaps enrollment'):
        calibrate(refs, [{**refs[0], 'origin': 'held-out'}], [(.75, .15)])
    held = [{**refs[0], 'sourceSha256': 'other'}]
    assert calibrate(refs, held, [(.75, .15)])['status'] == 'insufficient-independent-evidence'


def test_weak_competing_reference_does_not_hide_identity_conflict():
    refs = [ref('alex', 1, X), ref('alex', 2, X), ref('sam', 3, X), ref('sam', 4, Y)]
    assert identify(X, refs, threshold=.75, margin=.15)['playerId'] is None


def test_calibration_never_activates_and_counts_wrong_names():
    refs = [ref('alex', 1, X), ref('alex', 2, X)]
    held = [{**ref('alex', f'hold{i}', X), 'origin': 'held-out'} for i in range(5)]
    held += [{**ref(None, f'negative{i}', Y), 'origin': 'held-out'} for i in range(10)]
    result = calibrate(refs, held, [(.75, .15)])
    assert result['candidate']['correct'] == 5
    assert result['activated'] is False
    held[-1]['embedding'] = X
    assert calibrate(refs, held, [(.75, .15)])['status'] == 'no-policy-passes'


@pytest.mark.parametrize('start,end', [(2, 1), (-1, 2), (0, float('nan')), (False, 3)])
def test_invalid_intervals_rejected(start, end):
    with pytest.raises(click.ClickException):
        evaluate([row(start, end, 'alex')], [])


def test_native_labels_are_not_names_and_frame_padding_is_bounded():
    assert normalize({'segments': [{'start': 0, 'end': 12.01, 'speaker': 2}]}, 12) == [
        {'start': 0, 'end': 12, 'speaker': 'NEMOTRON_02'}]
    with pytest.raises(click.ClickException, match='exceeds'):
        normalize({'segments': [{'start': 0, 'end': 13, 'speaker': 2}]}, 12)
    with pytest.raises(click.ClickException, match='label'):
        normalize({'segments': [{'start': 0, 'end': 1, 'speaker': 'alex'}]}, 12)


def test_local_runner_pins_and_resumes_without_repeat_inference(tmp_path, monkeypatch):
    folder = tmp_path / 'recording'
    folder.mkdir()
    (folder / 'part-0000.flac').write_bytes(b'synthetic fixture')
    runtime, model = tmp_path / 'runtime', tmp_path / 'model'
    runtime.write_bytes(b'fake runtime')
    model.write_bytes(b'fake model')
    part = SimpleNamespace(file='part-0000.flac', duration=12, model_dump=lambda: {'file': 'part-0000.flac', 'duration': 12})
    record = SimpleNamespace(id='synthetic-recording', parts=[part])
    monkeypatch.setattr(native.audio, 'verified', lambda _: record)
    monkeypatch.setattr(native.audio, 'executable', lambda _: 'ffmpeg')
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[0] == 'ffmpeg':
            Path(args[-1]).write_bytes(b'local listening derivative')
        else:
            assert '--model' in args and str(model) in args and '--preset' in args
            Path(args[-1]).write_text(json.dumps({'segments': [{'start': 0, 'end': 12, 'speaker': 1}]}))
    monkeypatch.setattr(native.subprocess, 'run', run)
    root = tmp_path / 'work'
    args = [str(folder), '--runtime', str(runtime), '--runtime-sha256', hashlib.sha256(runtime.read_bytes()).hexdigest(),
            '--model', str(model), '--model-sha256', hashlib.sha256(model.read_bytes()).hexdigest(), '--work-dir', str(root)]
    runner = CliRunner()
    assert runner.invoke(native.command, args).exit_code == 0
    assert runner.invoke(native.command, args).exit_code == 0
    assert len(calls) == 2
    result = json.loads((root / 'diarization.json').read_text())
    assert result['identitiesAssigned'] is False and result['recordingId'] == record.id
    (root / 'diarization.json').write_text('{}')
    response = runner.invoke(native.command, args)
    assert response.exit_code != 0 and 'changed' in response.output


def test_repeated_validation_samples_do_not_inflate_calibration():
    refs = [ref('alex', 1, X), ref('alex', 2, X)]
    held = ref('alex', 'hold', X)
    with pytest.raises(click.ClickException, match='repeat'):
        calibrate(refs, [held, held], [(.75, .15)])
