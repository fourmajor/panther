import json
from click.testing import CliRunner
from panther_journal.asset_migrations import assets
from panther_journal import video_thumbnails as covers
import pytest


def test_cover_audit_is_read_only_and_paging_is_off_browser(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(covers.cloud, 'configuration', lambda: {})
    def api(config, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {'assets': [{'key': 'games/example/assets/video/original/take.mp4', 'contentType': 'video/mp4'}], 'cursor': None}
    monkeypatch.setattr(covers.cloud, 'api', api)
    result = CliRunner().invoke(assets, ['video-covers', '--game', 'example', '--work-dir', str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert 'Missing cover:' in result.output
    assert [(method, path) for method, path, _ in calls] == [('GET', '/assets')]


def test_cover_link_migration_pins_source_version_and_preserves_metadata(monkeypatch, tmp_path):
    asset = {'key': 'games/example/assets/video/original/take.mp4', 'contentType': 'video/mp4', 'metadata': {'title': 'Video'}}
    signed = {**asset, 'versionId': 'source-version', 'kind': 'video', 'metadata': {'title': 'Video', 'sourceKeys': ['games/example/assets/input/original/source.json'], 'extra': {'generation': {'prompt': 'preserved'}}}}
    requests = []
    def api(config, method, path, **kwargs):
        if path == '/object-url':
            return signed
        requests.append(kwargs['json'])
        return {'status': 'applied'}
    monkeypatch.setattr(covers.cloud, 'api', api)
    monkeypatch.setattr(covers, 'download', lambda *_: 'a'*64)
    frame = tmp_path / 'frame.jpg'
    frame.write_bytes(b'image')
    monkeypatch.setattr(covers, 'extract', lambda *_: (frame, .25))
    def upload(**kwargs):
        assert json.loads(kwargs['metadata'].read_text())['sourceKeys'] == [asset['key']]
        print(json.dumps({'key': 'games/example/assets/cover/original/frame.jpg'}))
    monkeypatch.setattr(covers.cloud.upload, 'callback', upload)
    assert covers.prepare({}, 'example', asset, tmp_path)['status'] == 'applied'
    request = requests[0]
    assert request['expectedVersionId'] == 'source-version'
    assert request['metadata']['sourceKeys'] == signed['metadata']['sourceKeys']
    assert request['metadata']['extra']['generation'] == {'prompt': 'preserved'}
    assert request['metadata']['extra']['preview']['imageKey'].endswith('frame.jpg')


def test_cover_download_rejects_foreign_urls_and_unpinned_sources(tmp_path):
    with pytest.raises(ValueError, match='destination'):
        covers.download({'url': 'https://example.test/video'}, tmp_path / 'source')
    with pytest.raises(ValueError, match='pinned'):
        covers.download({'url': 'https://bucket.s3.amazonaws.com/video', 'size': 1}, tmp_path / 'source')
