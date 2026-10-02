import importlib
import json
import uuid

import pytest

from test_novel_library import library, novel, editorial, broker  # noqa: F401


@pytest.fixture
def scenes(library, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CATALOG_READERS", "example-operator,example-reader")
    return importlib.import_module("video_scenes")


def call(scenes, kind="episode", body=None, username="example-operator", **query):
    return scenes.handler(
        {
            "routeKey": ("POST " if body is not None else "GET ")
            + "/"
            + ("scenes" if kind == "scene" else "episodes"),
            "body": json.dumps(body) if body is not None else None,
            "queryStringParameters": {"gameId": "test-game", **query},
            "requestContext": {
                "authorizer": {
                    "jwt": {
                        "claims": {
                            "sub": "fictional-operator",
                            "cognito:username": username,
                        }
                    }
                }
            },
        },
        None,
    )


def edit(**changes):
    return {
        "gameId": "test-game",
        "id": "harbor",
        "name": "Arrival at the harbor",
        "expectedRevision": None,
        "operationId": uuid.uuid4().hex,
        **changes,
    }


def unpack(response):
    assert response["statusCode"] == 200, response
    return json.loads(response["body"])


def test_title_only_episode_scene_and_read_permissions(scenes):
    episode = unpack(call(scenes, body=edit()))["record"]
    body = edit(id="arrival", episodeId=episode["id"])
    scene = unpack(call(scenes, "scene", body))["record"]
    assert scene["description"] == "" and scene["type"] == "general"
    assert scene["episodeId"] == episode["id"]
    assert "updatedBy" not in scene
    assert unpack(call(scenes, username="example-reader"))["records"] == [episode]
    assert unpack(call(scenes, "scene", episodeId="harbor", username="example-reader"))[
        "records"
    ] == [scene]
    assert call(scenes, body=edit(id="second"), username="example-reader")["statusCode"] == 403
    assert call(scenes, username="outsider")["statusCode"] == 403
    assert unpack(call(scenes, "scene", episodeId="other"))["records"] == []


def test_scene_revision_pins_survive_edits_and_exact_retries(scenes):
    unpack(call(scenes, body=edit()))
    body = edit(
        id="arrival",
        episodeId="harbor",
        type="travel",
        description="The party travels.\nMap: the harbor road.",
    )
    first = unpack(call(scenes, "scene", body))["record"]
    assert unpack(call(scenes, "scene", body))["replayed"]
    update = {
        **body,
        "expectedRevision": first["revision"],
        "operationId": uuid.uuid4().hex,
        "name": "A changed arrival",
        "type": "action",
    }
    second = unpack(call(scenes, "scene", update))["record"]
    assert second["previousRevision"] == first["revision"]
    assert second["position"] == first["position"] and second["createdAt"] == first["createdAt"]
    ref = {"episodeId": "harbor", "sceneId": "arrival", "revision": first["revision"]}
    assert scenes.pin_scene("test-game", ref) == first
    assert (
        unpack(call(scenes, "scene", episodeId="harbor", id="arrival", revision=first["revision"]))[
            "record"
        ]
        == first
    )
    assert unpack(call(scenes, "scene", body))["record"] == second
    assert call(scenes, "scene", {**update, "operationId": uuid.uuid4().hex})["statusCode"] == 409
    assert call(scenes, "scene", {**body, "name": "Different arguments"})["statusCode"] == 409
    for game, bad in [
        ("other-game", ref),
        ("test-game", {**ref, "episodeId": "other"}),
        ("test-game", {**ref, "revision": "f" * 32}),
    ]:
        with pytest.raises(ValueError):
            scenes.pin_scene(game, bad)


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"name": "x" * 161},
        {"description": "x" * 4001},
        {"type": "unknown"},
        {"episodeId": "missing"},
        {"gameId": "missing"},
        {"episodeId": "../harbor"},
        {"expectedRevision": "bad"},
        {"operationId": "bad"},
        {"clipKeys": []},
        {"name": "bad\u0000title"},
    ],
)
def test_invalid_scene_definitions_do_not_write(scenes, changes):
    unpack(call(scenes, body=edit()))
    assert (
        call(scenes, "scene", edit(**{"id": "arrival", "episodeId": "harbor", **changes}))[
            "statusCode"
        ]
        == 400
    )
    assert unpack(call(scenes, "scene", episodeId="harbor"))["records"] == []


def test_scene_ownership_is_scoped_to_episode_not_shared(scenes):
    for episode in ("harbor", "forest"):
        unpack(call(scenes, body=edit(id=episode)))
    harbor = unpack(call(scenes, "scene", edit(id="arrival", episodeId="harbor")))["record"]
    body = edit(id="arrival", episodeId="forest", expectedRevision=harbor["revision"])
    assert call(scenes, "scene", body)["statusCode"] == 409
    assert unpack(call(scenes, "scene", episodeId="forest"))["records"] == []
    forest = unpack(call(scenes, "scene", {**body, "expectedRevision": None}))["record"]
    assert forest["revision"] != harbor["revision"]


def test_missing_records_and_cursor_scope(scenes):
    assert call(scenes, id="missing")["statusCode"] == 404
    assert call(scenes, cursor="invalid")["statusCode"] == 400
    assert call(scenes, "scene", id="missing")["statusCode"] == 400
    assert call(scenes, revision="f" * 32)["statusCode"] == 400


def test_generation_uses_real_immutable_episode_owned_scene(scenes, editorial):  # noqa: F811
    unpack(call(scenes, body=edit()))
    scene = unpack(call(scenes, "scene", edit(id="arrival", episodeId="harbor", type="opener")))[
        "record"
    ]
    creation = {
        "schemaVersion": 2,
        "target": "video",
        "sceneRef": {"episodeId": "harbor", "sceneId": "arrival", "revision": scene["revision"]},
        "characterIds": [],
        "sourceKeys": [],
        "contextKeys": [],
    }
    job = editorial.submit({"gameId": "test-game", "creation": creation})
    assert job["selectedScene"] == scene
    assert job["creation"]["brief"] == scene["name"]
    assert job["raw"] is None and job["rawSources"] == []
    assert job["sessionId"] is None
    unpack(
        call(
            scenes,
            "scene",
            edit(
                id="arrival",
                episodeId="harbor",
                name="A new direction",
                expectedRevision=scene["revision"],
            ),
        )
    )
    assert editorial.submit({"gameId": "test-game", "creation": creation})["jobId"] == job["jobId"]
    with pytest.raises(ValueError):
        editorial.submit(
            {
                "gameId": "test-game",
                "creation": {
                    **creation,
                    "sceneRef": {**creation["sceneRef"], "episodeId": "foreign"},
                },
            }
        )
