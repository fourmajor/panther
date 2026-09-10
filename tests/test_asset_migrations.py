import base64
import copy
import importlib
import json
import sys
from contextlib import nullcontext
from datetime import datetime, timezone

import pytest

from test_media_api import load_media_api, response_body


@pytest.fixture
def service(monkeypatch):
    media, s3 = load_media_api(monkeypatch)
    monkeypatch.setitem(sys.modules, "index", media)
    monkeypatch.delitem(sys.modules, "asset_migrations", raising=False)
    module = importlib.import_module("asset_migrations")
    monkeypatch.setattr(module, "exclusive", lambda: nullcontext({"complete": False}))
    key = "games/example-game/assets/example-model/derived/web/model.glb"
    s3.objects[key]["VersionId"] = "version-one"
    s3.objects[key]["Metadata"] = {"uploaded-by": "original-actor"}
    head = s3.head_object
    s3.head_object = lambda **args: {**head(**args), "VersionId": s3.objects[args['Key']].get("VersionId"), "ETag": '"unchanged-content"', "LastModified": datetime(2020, 1, 1, tzinfo=timezone.utc)}
    s3.copies, s3.history = [], []

    def copy_object(**args):
        s3.copies.append(args)
        s3.history.append(copy.deepcopy(s3.objects[args["Key"]]))
        s3.objects[args["Key"]]["Metadata"] = args["Metadata"]
        s3.objects[args["Key"]]["VersionId"] = "version-two"
        return {"VersionId": "version-two"}

    s3.copy_object = copy_object
    body = {"schemaVersion": 1, "key": key, "expectedVersionId": "version-one", "kind": "model-3d",
            "reason": "Bring metadata to the current standard", "metadata": {
                "schemaVersion": 1, "title": "Example model", "category": "reference", "characterIds": [],
                "tags": [], "sourceKeys": [], "extra": {"relationshipRole": "finished",
                "generation": {"schemaVersion": 1, "method": "unknown", "cost": {"status": "unknown"}}}}}
    import storage_layout
    s3.resolve = lambda _key: storage_layout.location(key, body["kind"], body["metadata"])
    return module, s3, body


def call(service, body=None, username="stu"):
    module, _, default = service
    return module.handler({"body": json.dumps(default if body is None else body),
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "owner-id", "cognito:username": username}}}}}, None)


def test_dry_run_and_version_pinned_copy_preserve_bytes_history_and_original_actor(service):
    _, s3, body = service
    before = copy.deepcopy(s3.objects[body['key']])
    assert response_body(call(service))["status"] == "ready"
    assert not s3.copies
    result = response_body(call(service, {**body, "dryRun": False}))
    assert result['status'] == 'migrated'
    assert result['previousVersionId'] == 'version-one'
    assert s3.history == [before]
    assert s3.objects[body['key']]['Body'] == before['Body']
    args = s3.copies[0]
    assert args['CopySource']['VersionId'] == 'version-one'
    assert args['CopySource']['Key'] == args['Key']
    assert args['MetadataDirective'] == 'REPLACE' and args['TaggingDirective'] == 'COPY'
    assert args['ChecksumAlgorithm'] == 'SHA256'
    assert args['Metadata']['uploaded-by'] == 'original-actor'
    assert args['Metadata']['migration-actor'] == 'owner-id'
    assert args['Metadata']['asset-created-at'] == '2020-01-01T00:00:00+00:00'
    assert response_body(call(service, {**body, "dryRun": False}))['status'] == 'already-applied'
    assert len(s3.copies) == 1


@pytest.mark.parametrize('change', [
    {'expectedVersionId': 'stale'}, {'key': 'games/other/characters/person/profile.json'},
    {'body': 'replacement bytes'}, {'metadata': {}}, {'schemaVersion': 9},
    {'dryRun': 'false'}, {'kind': '../bad'}, {'reason': ''},
])
def test_invalid_or_conflicted_plans_cannot_write(service, change):
    _, s3, body = service
    assert call(service, {**body, **change, 'dryRun': change.get('dryRun', False)})['statusCode'] in (400, 409)
    assert not s3.copies


def test_owner_only_versioning_required_and_lineage_cannot_be_dropped(service):
    _, s3, body = service
    assert call(service, username='other_stu')['statusCode'] == 403
    s3.objects[body['key']]['VersionId'] = 'null'
    assert call(service)['statusCode'] == 400
    s3.objects[body['key']]['VersionId'] = 'version-one'
    s3.objects[body['key']]['Metadata']['panther'] = base64.b64encode(json.dumps({'sourceKeys': ['games/example-game/assets/source/original/a.png']}).encode()).decode()
    assert call(service, {**body, 'dryRun': False})['statusCode'] == 400
    assert not s3.copies


def test_handler_releases_only_definite_results_and_never_locks_for_nonowner(service, monkeypatch):
    module, _, _ = service
    state = {"complete": False}
    monkeypatch.setattr(module, "exclusive", lambda: nullcontext(state))
    assert call(service)["statusCode"] == 200
    assert state["complete"]
    state["complete"] = False
    monkeypatch.setattr(module, "_handle", lambda *_: {"statusCode": 503})
    assert call(service)["statusCode"] == 503
    assert not state["complete"]
    monkeypatch.setattr(module, "exclusive", lambda: pytest.fail("Unauthorized lock attempt"))
    assert call(service, username="other_stu")["statusCode"] == 403


def test_new_uploads_get_explicit_current_metadata(monkeypatch):
    from test_media_api import upload_event
    media, s3 = load_media_api(monkeypatch)
    assert media.handler(upload_event(), None)['statusCode'] == 200
    metadata = json.loads(base64.b64decode(s3.signed_requests[0][1]['Metadata']['panther']))
    assert metadata['schemaVersion'] == 1
    assert metadata['characterIds'] == [] and metadata['sourceKeys'] == []
    assert metadata['extra']['relationshipRole'] == 'finished'


def test_indexed_upload_is_routed_server_side_and_old_worker_reference_remains_stable(monkeypatch):
    from test_media_api import upload_event
    monkeypatch.delitem(sys.modules, "asset_storage", raising=False)
    media, s3 = load_media_api(monkeypatch, real_storage=True)
    result = media.handler(upload_event(), None)
    assert result["statusCode"] == 200, result
    result = response_body(result)
    assert "/assets/" in result["key"] and "/original/" in result["key"]
    assert "/content/" in result["storageKey"] and "/original/" not in result["storageKey"]
    assert s3.signed_requests[0][1]["Key"] == result["storageKey"]
    assert s3.signed_requests[0][1]["IfNoneMatch"] == "*"
    assert any("/catalog/assets/" in key for key in s3.objects)


def test_retired_environment_flag_cannot_bypass_indexed_storage(monkeypatch):
    from test_media_api import upload_event
    monkeypatch.setenv("ASSET_STORAGE_MODE", "prepare")
    media, s3 = load_media_api(monkeypatch, real_storage=True)
    result = response_body(media.handler(upload_event(), None))
    assert "/content/" in result["storageKey"]
    assert s3.signed_requests[0][1]["Key"] == result["storageKey"]
