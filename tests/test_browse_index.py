"""Synthetic catalog tests: listing never opens S3 assets."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import boto3
from botocore.exceptions import ClientError
import pytest
from moto import mock_aws


@pytest.fixture
def index(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "infra/lambda/media-api"))
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("ASSET_BROWSE_TABLE", "synthetic-browse")
    module = importlib.import_module("browse_index")
    # Older handler tests intentionally import with a stub boto3 module.
    monkeypatch.setattr(module, "boto3", boto3)
    monkeypatch.setattr(module, "ClientError", ClientError)
    with mock_aws():
        boto3.resource("dynamodb").create_table(TableName="synthetic-browse",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST")
        module.table().put_item(Item={"pk": "v5#catalog", "sk": "ready"})
        yield module


def asset(i=1, kind="video-comparison", mime="video/mp4"):
    key = f"games/example/assets/take-{i}/original/take.mp4"
    return {"key": key, "name": "take.mp4", "contentType": mime, "kind": kind,
            "metadata": {"extra": {"version": {"schemaVersion": 1, "seriesId": f"take-{i}", "number": 1}}},
            "sourceKeys": [], "lastModified": "2026-01-01", "size": 1}


def test_maintenance_conflict_rereads_and_is_bounded(index, monkeypatch):
    calls = []
    monkeypatch.setattr(index.time, 'sleep', lambda _: None)
    newest = asset(2)
    def fresh_read(media, reference, *, write):
        calls.append((media, reference, write))
        if len(calls) < 3:
            raise index.ConcurrentIndexUpdate('changed')
        return newest
    monkeypatch.setattr(index, 'refresh', fresh_read)
    assert index.refresh_for_maintenance(None, newest['key'], write=True) is newest
    assert len(calls) == 3
    calls.clear()
    def conflicting(*args, **kwargs):
        calls.append(1)
        raise index.ConcurrentIndexUpdate('still changing')
    monkeypatch.setattr(index, 'refresh', conflicting)
    with pytest.raises(index.ConcurrentIndexUpdate):
        index.refresh_for_maintenance(None, newest['key'], write=True)
    assert len(calls) == 4


def test_maintenance_does_not_retry_other_errors_or_read_only_conflicts(index, monkeypatch):
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise ValueError('invalid source')
    monkeypatch.setattr(index, 'refresh', fail)
    with pytest.raises(ValueError, match='invalid source'):
        index.refresh_for_maintenance(None, asset()['key'], write=True)
    assert len(calls) == 1
    calls.clear()
    def conflict(*args, **kwargs):
        calls.append(1)
        raise index.ConcurrentIndexUpdate('conflict')
    monkeypatch.setattr(index, 'refresh', conflict)
    with pytest.raises(index.ConcurrentIndexUpdate):
        index.refresh_for_maintenance(None, asset()['key'], write=False)
    assert len(calls) == 1


def test_indexed_query_has_no_source_reads_and_scoped_pages(index, monkeypatch):
    library = importlib.import_module("asset_library")
    current = asset()
    monkeypatch.setattr(library, "describe", lambda *_: current)
    for i in range(103):
        current = asset(i)
        index.refresh(None, current["key"])
    monkeypatch.setattr(library, "describe", lambda *_: pytest.fail("Browsing must not read S3"))
    first = index.page("example", "videos")
    assert len(first["assets"]) == 100
    assert len(index.page("example", "videos", first["cursor"])["assets"]) == 3
    assert index.page("example", "audio")["assets"] == []
    for game, section in [("other", "videos"), ("example", "all")]:
        with pytest.raises(ValueError):
            index.page(game, section, first["cursor"])
    with pytest.raises(ValueError):
        index.page("example", "videos", "broken")


def test_refresh_changes_all_memberships_and_preserves_lineage(index, monkeypatch):
    library = importlib.import_module("asset_library")
    current = asset()
    current["sourceKeys"] = ["games/example/assets/source/original/text.json"]
    monkeypatch.setattr(library, "describe", lambda *_: current)
    index.refresh(None, current["key"])
    assert index.page("example", "videos")["assets"] == [current]
    current = {**current, "name": "take.json", "contentType": "application/json", "kind": "corrected-transcript"}
    index.refresh(None, current["key"])
    assert index.page("example", "videos")["assets"] == []
    assert index.page("example", "transcripts")["assets"] == [current]
    assert index.page("example", "all")["assets"] == [current]


def test_archive_page_uses_one_consistent_batch_and_filters_tombstones(index, monkeypatch):
    archive = importlib.import_module("asset_archive")
    library = importlib.import_module("asset_library")
    for i in range(100):
        current = asset(i)
        monkeypatch.setattr(library, "describe", lambda *_, value=current: value)
        index.refresh(None, current["key"])
    index.table().put_item(Item=archive.archive_key("example", asset(4)["key"]))
    table = index.table()
    original = table.meta.client.batch_get_item
    calls = []
    def batch(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)
    monkeypatch.setattr(table.meta.client, "batch_get_item", batch)
    monkeypatch.setattr(archive, "db", lambda: table)
    monkeypatch.setattr(archive, "archived", lambda *_: pytest.fail("Per-asset archive reads"))
    page = index.page("example", "videos")
    assert len(page["assets"]) == 99
    assert asset(4)["key"] not in {a["key"] for a in page["assets"]}
    assert len(calls) == 1
    request = calls[0]["RequestItems"][table.name]
    assert request["ConsistentRead"] is True
    assert len(request["Keys"]) == 100


def test_archive_batch_retries_only_unprocessed_keys_and_fails_closed(index, monkeypatch):
    archive = importlib.import_module("asset_archive")
    table = index.table()
    pending = {table.name: {"Keys": [archive.archive_key("example", asset()["key"])], "ConsistentRead": True}}
    calls = []
    responses = iter([{"Responses": {}, "UnprocessedKeys": pending},
                      {"Responses": {table.name: [{"sk": asset()["key"]}]}}])
    def batch(**kwargs):
        calls.append(kwargs)
        return next(responses)
    monkeypatch.setattr(table.meta.client, "batch_get_item", batch)
    monkeypatch.setattr(archive, "db", lambda: table)
    monkeypatch.setattr(archive.time, "sleep", lambda _: None)
    assert archive.archived_keys("example", [asset()["key"], asset(2)["key"]]) == {asset()["key"]}
    assert calls[1]["RequestItems"] == pending
    calls.clear()
    def unavailable(**kwargs):
        calls.append(kwargs)
        return {"UnprocessedKeys": pending}
    monkeypatch.setattr(table.meta.client, "batch_get_item", unavailable)
    with pytest.raises(RuntimeError, match="incomplete"):
        archive.archived_keys("example", [asset()["key"]])
    assert len(calls) == 4
    assert archive.archived_keys("example", []) == set()
    with pytest.raises(ValueError, match="catalog page"):
        archive.archived_keys("example", [asset(i)["key"] for i in range(101)])


def test_event_uses_current_asset_and_ignores_unrelated_objects(index, monkeypatch):
    import sys
    calls = []
    media = SimpleNamespace(BUCKET_NAME="test-bucket", s3=SimpleNamespace(reference_for=lambda _: asset()["key"]))
    monkeypatch.setitem(sys.modules, "index", media)
    monkeypatch.setattr(index, "refresh", lambda m, ref: calls.append(ref))
    index.event_handler({"detail": {"bucket": {"name": "test-bucket"}, "object": {"key": "games/example/content/take.mp4"}}}, None)
    index.event_handler({"detail": {"bucket": {"name": "test-bucket"}, "object": {"key": "games/example/catalog/assets/a.json"}}}, None)
    assert calls == [asset()["key"]]


def test_backfill_dry_run_apply_verify(index, monkeypatch):
    import sys
    monkeypatch.setenv("ASSET_MIGRATORS", "example-owner")
    current = asset()
    library = importlib.import_module("asset_library")
    monkeypatch.setattr(library, "describe", lambda *_: current)
    media = SimpleNamespace(BUCKET_NAME="test-bucket", _valid_slug=lambda v: v == "example",
        _response=lambda status, body: {"statusCode": status, "body": body},
        raw_s3=SimpleNamespace(list_objects_v2=lambda **_: {"Contents": [{"Key": current["key"].replace("/assets/", "/catalog/assets/") + ".json"}]}))
    monkeypatch.setitem(sys.modules, "index", media)
    event = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "synthetic", "cognito:username": "example-owner"}}}}}
    for mode, expected in [("dry-run", "ready"), ("verify", "mismatch"), ("apply", "indexed"), ("verify", "verified")]:
        result = index.rebuild_handler({**event, "body": json.dumps({"gameId": "example", "mode": mode})}, None)
        assert result["body"]["records"][0]["status"] == expected
    assert index.rebuild_handler({"body": "{}"}, None)["statusCode"] == 403


def test_initial_cutover_fails_closed(index):
    index.table().delete_item(Key={"pk": "v5#catalog", "sk": "ready"})
    index.table().put_item(Item={"pk": "v1#catalog", "sk": "ready"})
    index.table().put_item(Item={"pk": "v2#catalog", "sk": "ready"})
    with pytest.raises(index.IndexNotReady):
        index.page("example", "videos")


def test_overlapping_source_read_cannot_replace_newer_commit(index, monkeypatch):
    library = importlib.import_module("asset_library")
    current = asset()
    updated = {**current, "kind": "corrected-transcript", "name": "x.json", "contentType": "application/json"}
    def overlap(*_):
        monkeypatch.setattr(library, "describe", lambda *_: updated)
        index.refresh(None, current["key"])
        return current
    monkeypatch.setattr(library, "describe", overlap)
    with pytest.raises(RuntimeError, match="Concurrent index update"):
        index.refresh(None, current["key"])
    assert index.page("example", "videos")["assets"] == []
    assert index.page("example", "transcripts")["assets"] == [updated]


def test_chunks_and_exports_dont_become_duplicate_listing_cards(index, monkeypatch):
    library = importlib.import_module("asset_library")
    assert index.sections({**asset(), "name": "part-0001.flac", "kind": "recording", "contentType": "audio/flac"}) == {"all"}
    current = {**asset(), "key": "games/example/assets/text/original/raw.md", "name": "raw.md", "kind": "raw-transcript", "contentType": "text/markdown"}
    monkeypatch.setattr(library, "describe", lambda *_: current)
    index.refresh(None, current["key"])
    assert len(index.page("example", "transcripts")["assets"]) == 1
    current = {**current, "key": current["key"][:-3] + ".json", "name": "raw.json", "contentType": "application/json"}
    index.refresh(None, current["key"])
    assert index.page("example", "transcripts")["assets"] == [current]


def test_sessions_dedicated_partition_hides_internal_parts(index, monkeypatch):
    library = importlib.import_module("asset_library")
    values = [
        {**asset(1), "kind": "recording", "name": "session.flac", "contentType": "audio/flac"},
        {**asset(2), "kind": "raw-transcript", "name": "raw.json", "contentType": "application/json"},
        {**asset(3), "kind": "corrected-transcript", "name": "edited.json", "contentType": "application/json"},
        {**asset(4), "kind": "recording", "name": "part-0001.flac", "contentType": "audio/flac"},
        {**asset(5), "kind": "recording-manifest", "name": "manifest.json", "contentType": "application/json"},
        {**asset(6), "kind": "editorial-correction", "name": "intermediate.json", "contentType": "application/json"},
        asset(7),
    ]
    for current in values:
        monkeypatch.setattr(library, "describe", lambda *_, value=current: value)
        index.refresh(None, current["key"])
    monkeypatch.setattr(library, "describe", lambda *_: pytest.fail("Sessions must not read source storage"))
    assert index.page("example", "sessions")["assets"] == values[:3]
    assert "sessions" in index.SECTIONS


def test_sessions_bounded_pages_keep_cursor_and_scope(index):
    import base64
    for i in range(105):
        current = {**asset(i), "kind": "raw-transcript", "contentType": "application/json"}
        for section in ('all', 'sessions'):
            index.table().put_item(Item={"pk": index.partition("example", section), "sk": f"{i:03d}", "payload": json.dumps(current)})
    first = index.page("example", "sessions")
    assert len(first["assets"]) == 100 and first["cursor"]
    assert len(index.page("example", "sessions", first["cursor"])["assets"]) == 5
    with pytest.raises(ValueError):
        index.page("example", "all", first["cursor"])
    all_cursor = index.page("example", "all")["cursor"]
    with pytest.raises(ValueError):
        index.page("example", "sessions", all_cursor)
    with pytest.raises(ValueError):
        index.page("other", "sessions", first["cursor"])
    cursor = json.loads(base64.urlsafe_b64decode(first["cursor"]))
    assert cursor["pk"] == index.partition("example", "sessions")


def test_sessions_not_hidden_by_hundreds_of_unrelated_assets(index, monkeypatch):
    library = importlib.import_module('asset_library')
    for i in range(130):
        current = asset(i, 'portrait', 'image/png')
        monkeypatch.setattr(library, 'describe', lambda *_, value=current: value)
        index.refresh(None, current['key'])
    transcript = {**asset(999), 'kind': 'raw-transcript', 'name': 'transcript.json', 'contentType': 'application/json'}
    monkeypatch.setattr(library, 'describe', lambda *_: transcript)
    index.refresh(None, transcript['key'])
    monkeypatch.setattr(library, 'describe', lambda *_: pytest.fail('No source scans on reads'))
    assert index.page('example', 'sessions')['assets'] == [transcript]
    assert index.page('example', 'sessions')['cursor'] is None


def test_sessions_suppresses_paired_transcript_export(index, monkeypatch):
    library = importlib.import_module("asset_library")
    raw = {**asset(), "key": "games/example/assets/text/original/raw.json", "name": "raw.json", "kind": "raw-transcript", "contentType": "application/json"}
    markdown = {**raw, "key": raw["key"][:-5] + ".md", "name": "raw.md", "contentType": "text/markdown"}
    for current in (raw, markdown):
        monkeypatch.setattr(library, "describe", lambda *_, value=current: value)
        index.refresh(None, current["key"])
    assert index.page("example", "sessions")["assets"] == [raw]



def test_sessions_hides_explicit_browser_wave_parts_before_manifest_exists(index, monkeypatch):
    library = importlib.import_module("asset_library")
    part = {**asset(), "name": "part-0001.wav", "kind": "recording", "contentType": "audio/wav",
        "metadata": {"extra": {"browserPart": {"chunkSetId": "synthetic-chunks", "index": 1}}}}
    monkeypatch.setattr(library, "describe", lambda *_: part)
    index.refresh(None, part["key"])
    assert index.page("example", "sessions")["assets"] == []
    assert index.page("example", "audio")["assets"] == [part]


def test_tag_backfill_verification_blocks_activation_until_all_tags_exist(index, monkeypatch):
    import sys
    import user_metadata
    monkeypatch.setenv('ASSET_MIGRATORS', 'example-owner')
    current = asset()
    current['metadata']['tags'] = ['canonical', 'Travel map']
    library = importlib.import_module('asset_library')
    monkeypatch.setattr(library, 'describe', lambda *_: current)
    def listing(**args):
        return {'CommonPrefixes': [{'Prefix': 'games/example/'}]} if args.get('Delimiter') else {'Contents': [{'Key': current['key'].replace('/assets/', '/catalog/assets/') + '.json'}]}
    media = SimpleNamespace(BUCKET_NAME='test-bucket', _valid_slug=lambda value: value == 'example',
        _response=lambda status, body: {'statusCode': status, 'body': body}, raw_s3=SimpleNamespace(list_objects_v2=listing, get_paginator=lambda _: SimpleNamespace(paginate=lambda **args: [listing(**args)])))
    monkeypatch.setitem(sys.modules, 'index', media)
    def rebuild(mode):
        return index.rebuild_handler({'body': json.dumps({'gameId': 'example', 'mode': mode}),
            'requestContext': {'authorizer': {'jwt': {'claims': {'sub': 'synthetic', 'cognito:username': 'example-owner'}}}}}, None)
    rebuild('apply')
    rebuild('verify')
    index.table().delete_item(Key=user_metadata.tag_key('example', 'Travel map'))
    assert rebuild('verify')['body']['records'][0]['status'] == 'mismatch'
    assert rebuild('activate')['statusCode'] != 200
    rebuild('apply')
    assert rebuild('verify')['body']['records'][0]['status'] == 'verified'
    assert rebuild('activate')['statusCode'] == 200
    assert user_metadata.tags('example')['tags'] == ['canonical', 'Travel map']


def test_sessions_excludes_generated_speech_and_includes_explicit_recording_playback(index, monkeypatch):
    library = importlib.import_module('asset_library')
    values = [
        {**asset(1), 'kind': 'narration', 'contentType': 'audio/mpeg', 'name': 'speech.mp3'},
        {**asset(2), 'kind': 'recording-playback', 'contentType': 'audio/mpeg', 'name': 'playback.mp3'},
        {**asset(3), 'kind': 'recording-manifest', 'contentType': 'application/json', 'name': 'recording.json', 'recording': {'partCount': 2, 'status': 'complete'}},
    ]
    for current in values:
        monkeypatch.setattr(library, 'describe', lambda *_, value=current: value)
        index.refresh(None, current['key'])
    monkeypatch.setattr(library, 'describe', lambda *_: pytest.fail('Sessions cannot read source storage'))
    assert index.page('example', 'sessions')['assets'] == values[1:]


def test_compact_filtered_pages_remain_bounded_and_cursor_bound(index, monkeypatch):
    import asset_browser
    import user_metadata
    monkeypatch.setattr(user_metadata, 'tag_events', lambda _: [])
    for number in range(30):
        item = asset(number)
        item['metadata'].update(characterIds=['hero'], title=f'Take {number}')
        item['metadata']['extra']['generation'] = {'prompt': 'large prompt ' * 1000}
        index.table().put_item(Item={'pk': index.partition('example', 'all'), 'sk': item['key'], 'payload': json.dumps(item)})
    selected = asset_browser.options({'characterId': 'hero', 'view': 'cards', 'limit': '24'})
    first = index.page('example', 'all', selection=selected)
    assert len(first['assets']) == 24
    assert first['cursor']
    assert len(json.dumps(first).encode()) < 20_000
    assert all('generation' not in row['metadata']['extra'] for row in first['assets'])
    second = index.page('example', 'all', first['cursor'], selection=selected)
    assert len(second['assets']) == 6
    with pytest.raises(ValueError):
        index.page('example', 'all', first['cursor'], selection={**selected, 'characterId': 'other'})
