import importlib
from pathlib import Path
import pytest


@pytest.fixture
def browser(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'infra/lambda/media-api'))
    return importlib.import_module('asset_browser')


def test_only_explicit_same_game_images_can_be_video_covers(browser):
    video = {'key': 'games/example/assets/video/original/movie.mp4', 'contentType': 'video/mp4',
             'metadata': {'extra': {'preview': {'imageKey': 'games/example/assets/cover/original/frame.jpg'}}}}
    assert browser.card(video)['thumbnailKey'].endswith('frame.jpg')
    for candidate in ['games/other/assets/cover/original/frame.jpg', video['key'], 'https://example.test/frame.jpg']:
        video['metadata']['extra']['preview']['imageKey'] = candidate
        assert browser.cover_key(video) is None


def test_connections_exclude_unrelated_catalog_and_large_requests(browser):
    source = {'key': 'games/example/assets/source/original/transcript.json', 'kind': 'transcript', 'metadata': {}}
    derived = {'key': 'games/example/assets/video/original/movie.mp4', 'kind': 'video', 'contentType': 'video/mp4',
               'sourceKeys': [source['key']], 'metadata': {'extra': {'generation': {'prompt': 'x'*100000}}}}
    unrelated = {'key': 'games/example/assets/unrelated/original/image.png', 'metadata': {}}
    result = browser.related([source, derived, unrelated], source['key'])
    assert {row['key'] for row in result['assets']} == {source['key'], derived['key']}
    assert len(str(result)) < 1000
    assert result['assets'][1]['sourceKeys'] == [source['key']]


def test_lookup_keys_cannot_cross_games_or_be_unbounded(browser):
    with pytest.raises(ValueError):
        browser.valid_keys('example', ['games/other/assets/video/original/movie.mp4'])
    with pytest.raises(ValueError):
        browser.valid_keys('example', ['games/example/assets/video/original/movie.mp4']*61)
