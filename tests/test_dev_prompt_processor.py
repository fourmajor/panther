"""Prompt composition grounds selected speech and direction preserves approved words."""
import json
from types import SimpleNamespace

import pytest
from dev_prompt_processor import narration_direction, video_prompt
from dev_editorial_worker import Store, pin
from dev_video_worker import verified


class Responses:
    def __init__(self, value):
        if 'renderPrompt' in value:
            action = value.pop('renderPrompt')
            value.update(direction={field: action if field == 'action' else '' for field in ('setting', 'lighting', 'mood', 'blocking', 'action', 'camera', 'sound')}, visibleCharacterIds=value.get('visibleCharacterIds', []), renderable=True, frameCompatible=True, portraitsCompatible=True, reason='')
        self.value, self.calls = value, []
    def create(self, **request):
        self.calls.append(request)
        return SimpleNamespace(id='response-example', output_text=json.dumps(self.value), model_dump=lambda **kw: {'id': 'response-example', 'status': 'completed', 'model': 'example-model', 'usage': {'input_tokens': 10}})


def test_narration_direction_adds_performance_cues_without_changing_words(tmp_path):
    responses = Responses({'insertions': [{'position': 0, 'tag': 'whispers'}, {'position': 6, 'tag': 'short pause'}]})
    text, evidence = narration_direction('Hello traveler.', 'Quiet, with a pause after hello', tmp_path, SimpleNamespace(responses=responses))
    assert text == '[whispers] Hello [short pause] traveler.'
    assert evidence['generation']['responseId'] == 'response-example'
    assert json.loads((tmp_path / 'narration_direction-request.json').read_text())['input']


def test_direction_rejects_word_splitting_or_unsupported_tags(tmp_path):
    response = Responses({'insertions': [{'position': 2, 'tag': 'whispers'}]})
    with pytest.raises(ValueError, match='splits a spoken word'):
        narration_direction('Hello.', 'Quiet', tmp_path, SimpleNamespace(responses=response))


def test_video_prompt_extracts_selected_transcript_facts_and_preserves_bytes(tmp_path):
    store = Store(tmp_path / 'private.sqlite')
    key = 'games/fictional/assets/transcript-example/original/raw.json'
    raw = json.dumps({'entityType': 'PlayerTranscript', 'gameId': 'fictional', 'segments': [{'text': 'The travelers reach the gate.', 'start': 0, 'end': 2, 'playerId': None}]}).encode()
    with store.connect() as db:
        db.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (key, 'fictional', '{}', raw, 'now'))
    job = {'gameId': 'fictional', 'prompt': 'Show the gate', 'transcriptKeys': [key], 'inputRefs': [pin(store, key, 'fictional')]}
    response = Responses({'renderPrompt': 'Travelers approach a gate.', 'sourceFacts': [{'sourceKey': key, 'segmentIndex': 0, 'fact': 'Travelers reach the gate.'}], 'uncertainties': []})
    value, evidence = video_prompt(store, job, tmp_path, verified, SimpleNamespace(responses=response))
    assert 'Action: Travelers approach a gate.' in value['renderPrompt']
    assert store.object(key)[1] == raw
    assert evidence['cost']['status'] == 'unknown'


def test_video_prompt_invalid_evidence_is_rejected_before_rendering(tmp_path):
    store = Store(tmp_path / 'private.sqlite')
    response = Responses({'renderPrompt': 'Example', 'sourceFacts': [{'sourceKey': 'invented', 'segmentIndex': 0, 'fact': 'Invented'}], 'uncertainties': []})
    with pytest.raises(ValueError, match='invalid transcript'):
        video_prompt(store, {'gameId': 'fictional', 'prompt': 'Example'}, tmp_path, verified, SimpleNamespace(responses=response))


def test_video_handoff_keeps_exact_appearance_when_composer_omits_it(tmp_path):
    store = Store(tmp_path / 'private.sqlite')
    character = {'id': 'cleric', 'name': 'Example cleric', 'details': {'overview': 'Dark skin, cropped silver hair, rust-red cloak.', 'subtitle': 'Human cleric'}}
    scene = {'name': 'Token handoff', 'game': {'ruleset': 'Pathfinder'}, 'shots': [{'description': 'A six-notched copper token in a goblin palm.'}]}
    response = Responses({'renderPrompt': 'Push in on the token.', 'visibleCharacterIds': ['cleric'], 'sourceFacts': [], 'uncertainties': []})
    value, _ = video_prompt(store, {'gameId': 'fictional', 'prompt': 'Token handoff', 'characterContext': [character], 'sceneContext': scene}, tmp_path, verified, SimpleNamespace(responses=response))
    assert character['details']['overview'] in value['renderPrompt']
    assert scene['shots'][0]['description'] in value['renderPrompt']
    assert 'Continuity facts' not in value['renderPrompt']
    assert len(value['renderPrompt']) <= 4000
    assert json.loads(response.calls[0]['input'])['scene'] == scene


def test_overlarge_continuity_fails_without_truncating_original(tmp_path):
    store = Store(tmp_path / 'private.sqlite')
    response = Responses({'renderPrompt': 'Example', 'visibleCharacterIds': ['example'], 'sourceFacts': [], 'uncertainties': []})
    with pytest.raises(ValueError, match='provider limit'):
        video_prompt(store, {'gameId': 'fictional', 'prompt': 'Example', 'characterContext': [{'id': 'example', 'name': 'Example', 'details': {'overview': 'x' * 4000}}]}, tmp_path, verified, SimpleNamespace(responses=response))
    assert json.loads(response.calls[0]['input'])['characters'][0]['details']['overview'] == 'x' * 4000
    assert len(response.calls) == 1


def test_insert_uses_only_visible_cast_and_keeps_game_style(tmp_path):
    store = Store(tmp_path / 'private.sqlite')
    characters = [{'id': 'hero', 'name': 'Hero', 'details': {'overview': 'Copper skin, blue cloak.'}},
                  {'id': 'absent', 'name': 'Absent', 'details': {'overview': 'Red armor.'}}]
    response = Responses({'renderPrompt': 'Hero lifts the six-notched token.', 'visibleCharacterIds': ['hero'], 'sourceFacts': [], 'uncertainties': []})
    value, _ = video_prompt(store, {'gameId': 'fictional', 'prompt': 'Token insert', 'characterContext': characters,
        'sceneContext': {'game': {'visualStyle': 'photorealistic'}, 'shots': [{'description': 'Hero lifts the six-notched copper token.', 'camera': 'Locked close-up'}]}},
        tmp_path, verified, SimpleNamespace(responses=response))
    assert 'Photorealistic live-action' in value['renderPrompt']
    assert 'Absent' not in value['renderPrompt'] and 'Red armor' not in value['renderPrompt']
    assert 'Camera: Locked close-up' in value['renderPrompt']
    assert value['schemaVersion'] == 2 and value['visibleCharacterIds'] == ['hero']


def test_unknown_cast_and_unrenderable_actions_fail_before_video(tmp_path):
    store = Store(tmp_path / 'private.sqlite')
    response = Responses({'renderPrompt': 'Example', 'visibleCharacterIds': ['invented'], 'sourceFacts': [], 'uncertainties': []})
    with pytest.raises(ValueError, match='unselected character'):
        video_prompt(store, {'gameId': 'fictional', 'prompt': 'Example'}, tmp_path, verified, SimpleNamespace(responses=response))
    response.value.update(visibleCharacterIds=[], renderable=False, reason='Use separate shots for the chase and handoff.')
    with pytest.raises(ValueError, match='Split.*chase'):
        video_prompt(store, {'gameId': 'fictional', 'prompt': 'Example'}, tmp_path, verified, SimpleNamespace(responses=response))


def test_visual_analysis_gets_scaled_pixels_and_rejects_incompatible_frame(tmp_path):
    from test_dev_video_conditioning import fixture
    store, references = fixture(tmp_path / 'references', frame=True)
    response = Responses({'renderPrompt': 'Hero walks.', 'visibleCharacterIds': ['hero'], 'sourceFacts': [], 'uncertainties': []})
    response.value.update(frameCompatible=False, reason='The frame shows a different costume.')
    job = {**references, 'prompt': 'Hero walks', 'sceneContext': {'game': {'visualStyle': 'photorealistic'}}}
    with pytest.raises(ValueError, match='matching starting frame.*costume'):
        video_prompt(store, job, tmp_path, verified, SimpleNamespace(responses=response))
    content = response.calls[0]['input'][0]['content']
    assert sum(item['type'] == 'input_image' for item in content) == 3
    assert all(item['image_url'].startswith('data:image/jpeg;base64,') for item in content if item['type'] == 'input_image')
    response.value.update(frameCompatible=True, portraitsCompatible=False, reason='The portrait has different ancestry.')
    with pytest.raises(ValueError, match='matching official portraits.*ancestry'):
        video_prompt(store, job, tmp_path, verified, SimpleNamespace(responses=response))


def test_map_treatment_does_not_force_cartography_into_live_action(tmp_path):
    store = Store(tmp_path / 'private.sqlite')
    response = Responses({'renderPrompt': 'Track along the existing river.', 'sourceFacts': [], 'uncertainties': []})
    value, _ = video_prompt(store, {'gameId': 'fictional', 'prompt': 'Follow the river', 'sceneType': 'map',
        'sceneContext': {'game': {'visualStyle': 'photorealistic'}}}, tmp_path, verified, SimpleNamespace(responses=response))
    assert 'cartographic map in its existing visual style' in value['renderPrompt']
    assert 'Photorealistic live-action imagery' not in value['renderPrompt']
    assert value['visualStyle'] == 'photorealistic'  # Preserve the actual game snapshot.
