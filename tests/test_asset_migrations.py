import base64
import copy
import importlib
import json
import sys
from datetime import datetime, timezone

import pytest

from test_media_api import load_media_api, response_body


@pytest.fixture
def service(monkeypatch):
    media, s3 = load_media_api(monkeypatch)
    monkeypatch.setitem(sys.modules, "index", media)
    monkeypatch.delitem(sys.modules, "asset_migrations", raising=False)
    module = importlib.import_module("asset_migrations")
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
                "tags": [], "sourceKeys": [], "extra": {"relationshipRole": "finished"}}}
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


def test_new_uploads_get_explicit_current_metadata(monkeypatch):
    from test_media_api import upload_event
    media, s3 = load_media_api(monkeypatch)
    assert media.handler(upload_event(), None)['statusCode'] == 200
    metadata = json.loads(base64.b64decode(s3.signed_requests[0][1]['Metadata']['panther']))
    assert metadata['schemaVersion'] == 1
    assert metadata['characterIds'] == [] and metadata['sourceKeys'] == []
    assert metadata['extra']['relationshipRole'] == 'finished'
