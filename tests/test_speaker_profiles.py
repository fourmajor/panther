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


def test_empty_runtime_evidence_preserves_unknown_speech_without_weakening_enrollment():
    result = {'embeddings': {'SPEAKER_00': embedding(), 'SPEAKER_01': [0] * 16},
              'turns': [{'start': 0, 'end': 2, 'speaker': 'SPEAKER_00'},
                        {'start': 3, 'end': 5, 'speaker': 'SPEAKER_01'}]}
    profiles = [{'playerId': 'alex', 'embedding': embedding()}]
    lines = [{'start': 0, 'end': 2, 'text': 'Identified.'},
             {'start': 3, 'end': 5, 'text': 'Keep this speech.'}]
    labeled = speakers.label_lines(lines, result, profiles, 0)
    assert labeled[0]['playerId'] == 'alex'
    assert labeled[1]['playerId'] is None and labeled[1]['text'] == lines[1]['text']
    assert labeled[1]['attributionWarnings']
    assert 'attributionWarnings' not in lines[1]
    with pytest.raises(speakers.EmptySpeakerEmbedding):
        speakers.match([0] * 16, profiles)
    for invalid in [[math.nan] * 16, [1], [True] * 16]:
        with pytest.raises(click.ClickException):
            speakers.label_lines(lines, {**result, 'embeddings': {'SPEAKER_01': invalid}}, profiles, 0)
    from panther_journal.editorial import reading_transcript
    assert reading_transcript({'segments': labeled})['segments'][1]['attributionWarnings']


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
