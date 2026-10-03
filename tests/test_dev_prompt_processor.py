"""Prompt composition grounds selected speech and direction preserves approved words."""
import json
from types import SimpleNamespace

import pytest
from dev_prompt_processor import narration_direction, video_prompt
from dev_editorial_worker import Store, pin
from dev_video_worker import verified


class Responses:
    def __init__(self, value):
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
    assert value['renderPrompt'] == 'Travelers approach a gate.'
    assert store.object(key)[1] == raw
    assert evidence['cost']['status'] == 'unknown'


def test_video_prompt_invalid_evidence_is_rejected_before_rendering(tmp_path):
    store = Store(tmp_path / 'private.sqlite')
    response = Responses({'renderPrompt': 'Example', 'sourceFacts': [{'sourceKey': 'invented', 'segmentIndex': 0, 'fact': 'Invented'}], 'uncertainties': []})
    with pytest.raises(ValueError, match='invalid transcript'):
        video_prompt(store, {'gameId': 'fictional', 'prompt': 'Example'}, tmp_path, verified, SimpleNamespace(responses=response))
