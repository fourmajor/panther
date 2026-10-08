import copy
import importlib
import json
import uuid

import pytest
from click.testing import CliRunner

from test_video_scenes import scenes, call, edit, unpack  # noqa: F401
from test_novel_library import library, novel, editorial, broker  # noqa: F401


def shot(key):
    return {"shotId":"arrival","description":"Four travelers enter.","camera":"Locked wide","durationSeconds":5,"frameKey":key,"narration":""}


def test_prepared_frames_are_storyboard_only_and_proposal_preserves_history(scenes,monkeypatch):  # noqa: F811
    key="games/test-game/assets/frame/original/frame.png"
    scenes.browse_index.table().put_item(Item={"pk":scenes.browse_index.partition("test-game","all"),"sk":key,"observed":1,"payload":json.dumps({"key":key,"contentType":"image/png","kind":"shot-frame","metadata":{"extra":{"relationshipRole":"intermediate"}}})})
    media=importlib.import_module("index")
    with pytest.raises(ValueError):
        scenes.map_asset(media,"test-game",key)
    assert scenes.map_asset(media,"test-game",key,storyboard=True)[0]["key"]==key
    unpack(call(scenes,body=edit()))
    original=unpack(call(scenes,"scene",edit(id="arrival",episodeId="harbor")))["record"]
    body=edit(id="arrival",episodeId="harbor",expectedRevision=original["revision"],storyboardProposalShots=[shot(key)])
    monkeypatch.setenv("MODEL_WORKERS","other-owner")
    assert call(scenes,"scene",body)["statusCode"]==403
    monkeypatch.setenv("MODEL_WORKERS","example-operator")
    new=unpack(call(scenes,"scene",body))["record"]
    assert new["storyboard"]["origin"]=="ai" and new["planningState"]=="needs-approval"
    assert new["storyboard"]["decision"] is None and new["selectedOutputKey"] is None
    assert unpack(call(scenes,"scene",body))["replayed"]
    old=unpack(call(scenes,"scene",episodeId="harbor",id="arrival",revision=original["revision"]))["record"]
    assert old==original
    conflict=copy.deepcopy(body)
    conflict["operationId"]=uuid.uuid4().hex
    assert call(scenes,"scene",conflict)["statusCode"]==409


def test_cli_proposal_cannot_approve_or_claim_human_origin(tmp_path,monkeypatch):
    from panther_journal import tv_library
    writes=[]
    monkeypatch.setattr(tv_library.cloud,"configuration",lambda:{})
    monkeypatch.setattr(tv_library.cloud,"api",lambda config,method,path,**kw: writes.append((method,path,kw["json"])) or {"record":{"planningState":"needs-approval"}})
    body={"gameId":"test-game","episodeId":"pilot","id":"arrival","name":"Arrival","expectedRevision":"a"*32,"operationId":uuid.uuid4().hex,"storyboardProposalShots":[shot(None)]}
    path=tmp_path/'proposal.json'
    path.write_text(json.dumps(body))
    result=CliRunner().invoke(tv_library.propose_storyboard,[str(path)])
    assert result.exit_code==0,result.output
    assert writes==[("POST","/scenes",body)]
    path.write_text(json.dumps({**body,"storyboardDecision":{"action":"approved"}}))
    assert CliRunner().invoke(tv_library.propose_storyboard,[str(path)]).exit_code!=0
    assert len(writes)==1
