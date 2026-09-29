import base64
import copy
import hashlib
import json
from types import SimpleNamespace

import click
from click.testing import CliRunner
import jsonschema
import pytest

from panther_journal import illustration_planning as planner
from panther_journal.cli import main


CHAPTER = 'a' * 64
KEY = 'games/test-game/assets/chapter/original/chapter.json'
PORTRAIT = 'games/test-game/assets/hero/original/portrait.png'


def inputs():
    return {'schemaVersion': 1, 'entityType': 'ChapterIllustrationInputs',
            'gameId': 'test-game', 'chapterId': CHAPTER,
            'chapterReference': {'key': KEY, 'size': 2, 'sha256': base64.b64encode(hashlib.sha256(b'{}').digest()).decode()},
            'chapter': 'The captain paused at the harbor.',
            'chapterReview': {}, 'visualStyle': {'id': 'anime', 'prompt': 'Anime'},
            'appearances': {'hero': {'name': 'Synthetic Captain', 'appearance': {'id': 'ordinary'},
                                   'selection': {'portraitKey': PORTRAIT}}},
            'inputArtifacts': {KEY: {'key': KEY}, PORTRAIT: {'key': PORTRAIT}}}


def candidate():
    return {'title': 'Harbor composition', 'rationale': 'One illustration supports the opening.',
            'uncertainties': ['Historical appearance timing is unknown.'], 'illustrations': [{
                'id': 'harbor', 'title': 'At the harbor', 'placement': 'before-chapter',
                'sourceExcerpt': 'The captain paused at the harbor.', 'characterIds': ['hero'],
                'referenceKeys': [KEY, PORTRAIT], 'composition': 'Medium wide framing.',
                'lighting': 'Diffuse light.', 'palette': 'Muted blues.', 'altText': 'Captain at harbor.',
                'caption': 'Illustrative adaptation.', 'continuityNotes': ['Retain selected costume.'],
                'adaptationNotes': ['Lighting and composition are illustrative choices.'],
                'missingReferences': []}]}


@pytest.mark.parametrize('change', ['excerpt', 'character', 'reference', 'portrait', 'chapter', 'duplicate', 'adaptation', 'placement', 'alt', 'duplicate-character', 'duplicate-reference'])
def test_invalid_proposals_fail_closed(change):
    value = candidate()
    entry = value['illustrations'][0]
    if change == 'excerpt':
        entry['sourceExcerpt'] = 'Invented scene.'
    if change == 'character':
        entry['characterIds'] = ['unknown']
    if change == 'reference':
        entry['referenceKeys'].append('games/other/assets/private/original/portrait.png')
    if change == 'portrait':
        entry['referenceKeys'].remove(PORTRAIT)
    if change == 'chapter':
        entry['referenceKeys'].remove(KEY)
    if change == 'duplicate':
        value['illustrations'] *= 2
    if change == 'adaptation':
        entry['adaptationNotes'] = []
    if change == 'placement':
        entry['placement'] = 'in-prose'
    if change == 'alt':
        entry['altText'] = 'a' * 1001
    if change == 'duplicate-character':
        entry['characterIds'] *= 2
    if change == 'duplicate-reference':
        entry['referenceKeys'] *= 2
    with pytest.raises((ValueError, jsonschema.ValidationError)):
        planner.validate(value, inputs())


def test_empty_plan_and_explicitly_missing_art_are_valid():
    value = candidate()
    value['illustrations'] = []
    planner.validate(value, inputs())
    data = inputs()
    data['appearances']['hero']['selection'] = None
    value = candidate()
    with pytest.raises(ValueError, match='Missing character artwork'):
        planner.validate(value, data)
    value['illustrations'][0]['missingReferences'] = ['No selected portrait for hero.']
    planner.validate(value, data)


def test_independent_review_drives_actual_revisions_and_honest_drafts(tmp_path, monkeypatch):
    calls = []

    def agent(folder, role, data, _schema):
        calls.append((role, copy.deepcopy(data)))
        if role == 'planner':
            value = candidate()
            value['title'] = 'Revised ' + str(len(calls))
            return value
        return {'passed': False, 'issues': ['Check chronology.']}

    monkeypatch.setattr(planner, 'agent', agent)
    value, history, status = planner.plan(inputs(), tmp_path)
    assert len(calls) == 6 and len(history) == 3 and status == 'accepted-with-notes'
    assert calls[2][1]['feedback']['passed'] is False
    assert calls[2][1]['candidate']['title'] != value['title']
    assert history[-1]['review']['passed'] is False
    assert len(list(tmp_path.glob('attempt-*'))) == 3


def test_invalid_outputs_never_become_accepted_working_drafts(tmp_path, monkeypatch):
    monkeypatch.setattr(planner, 'agent', lambda *_: {'invalid': True})
    with pytest.raises(planner.model_workflow.Deferred):
        planner.plan(inputs(), tmp_path)
    assert len(list(tmp_path.glob('attempt-*/history.json'))) == 3


def setup_cli(monkeypatch):
    monkeypatch.setattr(planner.model_workflow, 'codex_base', lambda: ['codex'])
    monkeypatch.setattr(planner.subprocess, 'run', lambda *_args, **_kw: SimpleNamespace(
        returncode=0, stdout='Logged in using ChatGPT', stderr=''))
    monkeypatch.setattr(planner.cloud, 'configuration', lambda: {})


def test_command_pins_snapshot_and_reuses_completed_plan_without_calls(tmp_path, monkeypatch):
    setup_cli(monkeypatch)

    def snapshot(_config, _game, _chapter, folder):
        (folder / 'chapter.json').write_bytes(b'{}')
        return inputs()

    monkeypatch.setattr(planner, 'snapshot', snapshot)
    monkeypatch.setattr(planner, 'plan', lambda *_: (candidate(), [], 'accepted'))
    args = ['novels', 'plan-illustrations', '--game', 'test-game', '--id', CHAPTER,
            '--work-dir', str(tmp_path)]
    first = CliRunner().invoke(main, args)
    assert first.exit_code == 0, first.output
    file = tmp_path / CHAPTER / 'illustration-plan.json'
    output = json.loads(file.read_text())
    assert output['imageGenerationAuthorized'] is False
    assert output['generation']['inference'] == 'remote'
    assert output['reviewCoverage'] == 'text-and-pinned-metadata-only'
    monkeypatch.setattr(planner, 'snapshot', lambda *_: pytest.fail('Must not repin appearances'))
    monkeypatch.setattr(planner, 'plan', lambda *_: pytest.fail('Must not run more inference'))
    assert CliRunner().invoke(main, args).exit_code == 0
    path = tmp_path / CHAPTER / 'inputs.json'
    path.write_text(path.read_text() + '\n')
    changed = CliRunner().invoke(main, args)
    assert changed.exit_code != 0 and 'snapshot has changed' in changed.output


def test_api_key_authentication_is_refused_before_reading_private_data(tmp_path, monkeypatch):
    setup_cli(monkeypatch)
    monkeypatch.setattr(planner.subprocess, 'run', lambda *_args, **_kw: SimpleNamespace(
        returncode=0, stdout='Logged in using an API key', stderr=''))
    monkeypatch.setattr(planner, 'snapshot', lambda *_: pytest.fail('Must not read private data'))
    result = CliRunner().invoke(main, ['novels', 'plan-illustrations', '--game', 'test-game',
                                     '--id', CHAPTER, '--work-dir', str(tmp_path)])
    assert result.exit_code != 0 and 'subscription authentication is required' in result.output


@pytest.mark.parametrize('record', [{'size': 4}, {'size': True, 'sha256': 'invalid'},
                                  {'size': 10000, 'sha256': base64.b64encode(b'x' * 32).decode()}])
def test_source_pins_require_real_bounded_checksums(monkeypatch, record):
    monkeypatch.setattr(planner.cloud, 'api', lambda *_args, **_kw: record)
    with pytest.raises(click.ClickException):
        planner.reference({}, 'test-game', KEY, 100)


def test_agent_is_tool_free_subscription_only_and_keeps_sources_untrusted(tmp_path, monkeypatch):
    monkeypatch.setattr(planner.model_workflow, 'codex_base', lambda: ['codex', 'forced-chatgpt'])
    calls = []

    def run(command, **kw):
        calls.append((command, kw))
        (tmp_path / 'agent-result.json').write_text(json.dumps(candidate()))
        return 0

    monkeypatch.setattr(planner.model_workflow, 'run_process', run)
    planner.agent(tmp_path, 'planner', {'sources': inputs()}, planner.schema(inputs()))
    command, arguments = calls[0]
    assert command[:2] == ['codex', 'forced-chatgpt']
    assert '--ephemeral' in command and 'read-only' in command
    for feature in ['shell_tool', 'unified_exec', 'apps', 'multi_agent', 'image_generation']:
        assert command[command.index(feature) - 1] == '--disable'
    assert 'web_search="disabled"' in command
    assert 'UNTRUSTED DATA' in arguments['stdin'] and 'not claim to have visually inspected' in arguments['stdin']


def test_snapshot_uses_completed_bytes_style_and_exact_selection_without_rosters(tmp_path, monkeypatch):
    source = {'entityType': 'EditorialArtifact', 'stage': 'novel-chapter',
              'gameId': 'test-game', 'jobId': CHAPTER, 'publicationStatus': 'accepted-with-notes',
              'payload': {'chapter': inputs()['chapter'], 'review': {'uncertainties': ['Timing uncertain.']}}}
    content = json.dumps(source).encode()
    pin = {'key': KEY, 'size': len(content), 'sha256': base64.b64encode(hashlib.sha256(content).digest()).decode()}
    calls = []

    def api(_config, _method, endpoint, *, params):
        calls.append(endpoint)
        if endpoint == '/novel-chapter':
            return {'id': CHAPTER, 'gameId': 'test-game', 'details': {'artifact': pin}}
        if endpoint == '/game':
            return {'game': {'id': 'test-game', 'visualStyle': 'anime'},
                    'visualStyles': [{'id': 'anime', 'prompt': 'Cel-shaded illustration.'}],
                    'characters': [{'id': 'hero', 'name': 'Synthetic Captain'}],
                    'players': [{'id': 'synthetic-player', 'name': 'Do not send roster'}]}
        if endpoint == '/character-versions':
            return {'schemaVersion': 2, 'current': 'edition',
                    'selections': [{'id': 'edition', 'appearanceId': 'ordinary', 'portraitKey': PORTRAIT}],
                    'appearances': [{'id': 'ordinary', 'story': {'date': None}}]}
        if endpoint == '/character':
            return {'selection': {'id': 'edition', 'appearanceId': 'ordinary', 'portraitKey': PORTRAIT},
                    'appearance': {'id': 'ordinary', 'story': {'date': None}}}
        if endpoint == '/object-url':
            return pin if params['key'] == KEY else {'size': 10, 'sha256': pin['sha256'], 'url': 'PRIVATE-URL'}
        pytest.fail(endpoint)

    monkeypatch.setattr(planner.cloud, 'api', api)
    monkeypatch.setattr(planner.model_workflow, 'download', lambda _config, _ref, path: path.write_bytes(content))
    result = planner.snapshot({}, 'test-game', CHAPTER, tmp_path)
    assert result['chapter'] == source['payload']['chapter']
    assert result['visualStyle']['id'] == 'anime'
    assert result['appearances']['hero']['selection']['id'] == 'edition'
    assert result['inputArtifacts'][PORTRAIT]['key'] == PORTRAIT
    assert 'PRIVATE-URL' not in json.dumps(result) and 'Do not send roster' not in json.dumps(result)
    assert all(e in ['/novel-chapter', '/game', '/character-versions', '/character', '/object-url'] for e in calls)


def test_git_work_directories_are_rejected(tmp_path, monkeypatch):
    setup_cli(monkeypatch)
    (tmp_path / '.git').mkdir()
    result = CliRunner().invoke(main, ['novels', 'plan-illustrations', '--game', 'test-game',
                                     '--id', CHAPTER, '--work-dir', str(tmp_path / 'private')])
    assert result.exit_code != 0 and 'outside Git' in result.output


@pytest.mark.parametrize('change', ['chapter', 'seal', 'lock-link'])
def test_checkpoint_guards_fail_before_further_inference(tmp_path, monkeypatch, change):
    setup_cli(monkeypatch)

    def snapshot(_config, _game, _chapter, folder):
        (folder / 'chapter.json').write_bytes(b'{}')
        return inputs()

    monkeypatch.setattr(planner, 'snapshot', snapshot)
    monkeypatch.setattr(planner, 'plan', lambda *_: (candidate(), [], 'accepted'))
    args = ['novels', 'plan-illustrations', '--game', 'test-game', '--id', CHAPTER,
            '--work-dir', str(tmp_path)]
    assert CliRunner().invoke(main, args).exit_code == 0
    folder = tmp_path / CHAPTER
    if change == 'chapter':
        (folder / 'chapter.json').write_bytes(b'changed')
    elif change == 'seal':
        (folder / 'inputs-seal.json').unlink()
    else:
        (folder / 'planner.lock').unlink()
        (folder / 'planner.lock').symlink_to(folder / 'chapter.json')
    monkeypatch.setattr(planner, 'plan', lambda *_: pytest.fail('Must not run further inference'))
    result = CliRunner().invoke(main, args)
    assert result.exit_code != 0
    assert any(message in result.output for message in ['checkpoint has changed', 'without an input seal', 'symbolic-link'])
