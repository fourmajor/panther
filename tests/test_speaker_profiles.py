import math

import click
import pytest

from panther_journal import speaker_profiles as speakers


def embedding(x=1, y=0):
    return [x, y] + [0] * 14


def test_match_requires_threshold_and_margin_not_just_nearest():
    profiles = [{'playerId': 'alex', 'embedding': embedding()},
                {'playerId': 'sam', 'embedding': embedding(0, 1)}]
    assert speakers.match(embedding(), profiles) == 'alex'
    assert speakers.match(embedding(0, 1), profiles) == 'sam'
    assert speakers.match(embedding(1, 1), profiles) is None
    assert speakers.match(embedding(-1, 0), profiles) is None
    assert speakers.match(embedding(), profiles + [{'playerId': 'lee', 'embedding': embedding()}]) is None


@pytest.mark.parametrize('value', [[0] * 16, [math.nan] * 16, [math.inf] * 16, [True] * 16, [1]])
def test_invalid_embeddings_fail_closed(value):
    with pytest.raises(click.ClickException):
        speakers.vector(value)


def test_mixed_and_overlapping_speech_never_force_a_player():
    result = {'embeddings': {'SPEAKER_00': embedding(), 'SPEAKER_01': embedding(0, 1)},
              'turns': [{'start': 0, 'end': 4, 'speaker': 'SPEAKER_00'},
                        {'start': 3, 'end': 8, 'speaker': 'SPEAKER_01'}]}
    profiles = [{'playerId': 'alex', 'embedding': embedding()},
                {'playerId': 'sam', 'embedding': embedding(0, 1)}]
    lines = [{'start': 30, 'end': 32, 'text': 'First'},
             {'start': 32, 'end': 35, 'text': 'Overlap'},
             {'start': 35, 'end': 37, 'text': 'Second'},
             {'start': 39, 'end': 40, 'text': 'Unknown'}]
    labeled = speakers.label_lines(lines, result, profiles, 30)
    assert [line['playerId'] for line in labeled] == ['alex', None, 'sam', None]
    assert labeled[0]['attribution'] == 'provisional-enrolled-voice'
    assert all('playerId' not in line for line in lines)


def test_profile_mismatch_and_duplicate_ids(tmp_path):
    import json
    model = tmp_path / 'model'
    model.mkdir()
    (model / 'weights.bin').write_bytes(b'fake')
    path = tmp_path / 'profiles.json'
    doc = {'schemaVersion': 1, 'entityType': 'SpeakerRecognitionProfiles', 'gameId': 'test-game',
           'modelFiles': speakers.model_pin(model),
           'profiles': [{'playerId': 'alex', 'identityEvidence': 'Confirmed introduction', 'embedding': embedding()}]}
    path.write_text(json.dumps(doc))
    assert speakers.load_profiles(path, 'test-game', model) == doc
    with pytest.raises(click.ClickException, match='different game'):
        speakers.load_profiles(path, 'other-game', model)
    doc['profiles'] *= 2
    path.write_text(json.dumps(doc))
    with pytest.raises(click.ClickException, match='Duplicate'):
        speakers.load_profiles(path, 'test-game', model)
    (model / 'weights.bin').write_bytes(b'changed')
    with pytest.raises(click.ClickException, match='mismatch'):
        speakers.load_profiles(path, 'test-game', model)
