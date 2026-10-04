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
    created = unpack(call(scenes, "scene", body))
    scene = created["record"]
    episode = created["episodeRecord"]
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


def output(scenes, scene, **changes):
    key = "games/test-game/assets/take-one/original/clip.mp4"
    board = scene['storyboard']
    if not scene.get('shotTakes'):
        scene['shotTakes'] = {shot['shotId']: {'storyboardRevision': board['revision'], 'shotId': shot['shotId'], 'assetKey': 'games/test-game/assets/raw-take/original/take.mp4', 'startSeconds': 0, 'durationSeconds': shot['durationSeconds'], 'generationSceneRevision': scene['revision']} for shot in board['shots']}
        db = scenes.browse_index.table()
        pointer = scenes.records.pointer(scenes.PREFIX, scene['gameId'], 'scene#' + scene['episodeId'], scene['id'])
        row = db.get_item(Key=pointer)['Item']
        row['payload'] = json.dumps(scene)
        db.put_item(Item=row)
        db.put_item(Item={'pk': f"{scenes.PREFIX}-history#scene#{scene['episodeId']}#{scene['gameId']}#{scene['id']}", 'sk': scene['revision'], 'payload': json.dumps(scene)})
    asset = {
        "key": key,
        "contentType": "video/mp4",
        "size": 10,
        "metadata": {
            "extra": {
                "relationshipRole": "finished",
                "sceneAssembly": {"storyboardRevision": board['revision'], "clips": list(scene['shotTakes'].values())},
                "sceneRef": {
                    "episodeId": scene["episodeId"],
                    "sceneId": scene["id"],
                    "revision": scene["revision"],
                },
            }
        },
        **changes,
    }
    scenes.browse_index.table().put_item(
        Item={
            "pk": scenes.browse_index.partition("test-game", "all"),
            "sk": key,
            "observed": 1,
            "payload": json.dumps(asset),
        }
    )
    return key


def test_scene_append_is_atomic_revisioned_and_replay_does_not_duplicate(scenes):
    first = unpack(call(scenes, body=edit()))["record"]
    body = edit(id="arrival", episodeId="harbor")
    created = unpack(call(scenes, "scene", body))
    parent = created["episodeRecord"]
    assert parent["sceneIds"] == ["arrival"]
    assert parent["previousRevision"] == first["revision"]
    assert unpack(call(scenes, id="harbor", revision=parent["revision"]))["record"] == parent
    assert unpack(call(scenes, "scene", body))["replayed"]
    assert unpack(call(scenes, id="harbor"))["record"]["sceneIds"] == ["arrival"]
    assert call(scenes, body=edit(expectedRevision=first["revision"]))["statusCode"] == 409


def test_explicit_reorder_owned_scenes_and_missing_outputs_are_visible(scenes):
    unpack(call(scenes, body=edit()))
    for identity in ("arrival", "departure"):
        result = unpack(call(scenes, "scene", edit(id=identity, episodeId="harbor")))
    parent = result["episodeRecord"]
    body = edit(expectedRevision=parent["revision"], sceneIds=["departure", "arrival"])
    reordered = unpack(call(scenes, body=body))["record"]
    composition = scenes.pin_episode(
        "test-game", {"episodeId": "harbor", "revision": reordered["revision"]}
    )
    assert not composition["ready"]
    assert composition["missingSceneIds"] == ["departure", "arrival"]
    assert [row["sceneRef"]["sceneId"] for row in composition["scenes"]] == ["departure", "arrival"]
    assert len(composition["compositionHash"]) == 64 and composition["sourceKeys"] == []
    for order in (["arrival", "arrival"], ["missing"], "arrival", [None]):
        assert (
            call(scenes, body={**body, "sceneIds": order, "operationId": uuid.uuid4().hex})[
                "statusCode"
            ]
            == 400
        )
    unpack(call(scenes, body=edit(id="forest")))
    assert call(scenes, body=edit(id="forest", sceneIds=["arrival"]))["statusCode"] == 400


def test_selected_output_pins_actual_generation_scene_revision_and_composition(scenes):
    unpack(call(scenes, body=edit()))
    created = unpack(call(scenes, "scene", edit(id="arrival", episodeId="harbor")))
    first, parent = created["record"], created["episodeRecord"]
    key = output(scenes, first)
    changed = unpack(
        call(
            scenes,
            "scene",
            edit(
                id="arrival",
                episodeId="harbor",
                name="Changed direction",
                expectedRevision=first["revision"],
                selectedOutputKey=key,
            ),
        )
    )["record"]
    assert changed["selectedOutputSceneRevision"] == first["revision"]
    composition = scenes.pin_episode(
        "test-game", {"episodeId": "harbor", "revision": parent["revision"]}
    )
    assert composition["ready"] and composition["sourceKeys"] == [key]
    assert composition["scenes"][0]["sceneRef"]["revision"] == changed["revision"]
    assert composition["scenes"][0]["generationSceneRef"]["revision"] == first["revision"]
    assert (
        "updatedBy" not in composition["episode"]
        and "updatedBy" not in composition["scenes"][0]["scene"]
    )
    for asset_change in (
        {"contentType": "image/png"},
        {"metadata": {"extra": {"relationshipRole": "processing"}}},
        {
            "metadata": {
                "extra": {
                    "relationshipRole": "finished",
                    "sceneRef": {
                        "episodeId": "forest",
                        "sceneId": "arrival",
                        "revision": first["revision"],
                    },
                }
            }
        },
    ):
        output(scenes, first, **asset_change)
        assert (
            call(
                scenes,
                "scene",
                edit(
                    id="arrival",
                    episodeId="harbor",
                    expectedRevision=changed["revision"],
                    selectedOutputKey=key,
                ),
            )["statusCode"]
            == 400
        )
        with pytest.raises(ValueError):
            scenes.pin_episode("test-game", {"episodeId": "harbor", "revision": parent["revision"]})


@pytest.mark.parametrize(
    "changes",
    [
        {"metadata": None},
        {"metadata": {"extra": []}},
        {"contentType": None},
        {"lineageWarning": "Source unavailable"},
        {"kind": "editorial-report"},
    ],
)
def test_malformed_or_processing_video_cannot_be_selected(scenes, changes):
    unpack(call(scenes, body=edit()))
    first = unpack(call(scenes, "scene", edit(id="arrival", episodeId="harbor")))["record"]
    key = output(scenes, first, **changes)
    assert (
        call(
            scenes,
            "scene",
            edit(
                id="arrival",
                episodeId="harbor",
                expectedRevision=first["revision"],
                selectedOutputKey=key,
            ),
        )["statusCode"]
        == 400
    )


def test_composition_endpoint_authorization_and_revision_scope(scenes):
    unpack(call(scenes, body=edit()))
    created = unpack(call(scenes, "scene", edit(id="arrival", episodeId="harbor")))
    event = {
        "routeKey": "GET /episode-composition",
        "queryStringParameters": {
            "gameId": "test-game",
            "episodeId": "harbor",
            "revision": created["episodeRecord"]["revision"],
        },
        "requestContext": {
            "authorizer": {
                "jwt": {"claims": {"sub": "fictional-reader", "cognito:username": "example-reader"}}
            }
        },
    }
    assert scenes.handler(event, None)["statusCode"] == 200
    event["requestContext"]["authorizer"]["jwt"]["claims"]["cognito:username"] = "outsider"
    assert scenes.handler(event, None)["statusCode"] == 403
    event["requestContext"]["authorizer"]["jwt"]["claims"]["cognito:username"] = "example-reader"
    event["queryStringParameters"]["revision"] = "f" * 32
    assert scenes.handler(event, None)["statusCode"] == 400


def test_omitted_fields_preserve_order_and_selected_take_but_null_clears(scenes):
    unpack(call(scenes, body=edit()))
    created = unpack(call(scenes, "scene", edit(id="arrival", episodeId="harbor")))
    first, parent = created["record"], created["episodeRecord"]
    episode = unpack(call(scenes, body=edit(expectedRevision=parent["revision"], name="Retitled")))[
        "record"
    ]
    assert episode["sceneIds"] == ["arrival"]
    key = output(scenes, first)
    selected = unpack(
        call(
            scenes,
            "scene",
            edit(
                id="arrival",
                episodeId="harbor",
                expectedRevision=first["revision"],
                selectedOutputKey=key,
            ),
        )
    )["record"]
    renamed = unpack(
        call(
            scenes,
            "scene",
            edit(
                id="arrival",
                episodeId="harbor",
                name="Retitled scene",
                expectedRevision=selected["revision"],
            ),
        )
    )["record"]
    assert (
        renamed["selectedOutputKey"] == key
        and renamed["selectedOutputSceneRevision"] == first["revision"]
    )
    cleared = unpack(
        call(
            scenes,
            "scene",
            edit(
                id="arrival",
                episodeId="harbor",
                expectedRevision=renamed["revision"],
                selectedOutputKey=None,
            ),
        )
    )["record"]
    assert cleared["selectedOutputKey"] is None and cleared["selectedOutputSceneRevision"] is None


def test_concurrent_episode_edit_cancels_whole_scene_append(scenes, monkeypatch):
    parent = unpack(call(scenes, body=edit()))["record"]
    original = scenes.records.commit

    def race(db, prefix, kind, record, body, claims, fingerprint, guards, media):
        if kind.startswith("scene#"):
            unpack(
                call(scenes, body=edit(expectedRevision=parent["revision"], name="Concurrent edit"))
            )
        return original(db, prefix, kind, record, body, claims, fingerprint, guards, media)

    monkeypatch.setattr(scenes.records, "commit", race)
    assert call(scenes, "scene", edit(id="arrival", episodeId="harbor"))["statusCode"] == 409
    assert unpack(call(scenes, "scene", episodeId="harbor"))["records"] == []
    current = unpack(call(scenes, id="harbor"))["record"]
    assert current["sceneIds"] == [] and current["name"] == "Concurrent edit"


@pytest.mark.parametrize(
    "changes",
    [
        {"revision": "f" * 32},
        {"sceneIds": "arrival"},
        {"sceneIds": ["arrival", "arrival"]},
        {"sceneIds": ["../arrival"]},
    ],
)
def test_invalid_historical_episode_is_not_a_composition(scenes, changes):
    unpack(call(scenes, body=edit()))
    created = unpack(call(scenes, "scene", edit(id="arrival", episodeId="harbor")))
    parent = created["episodeRecord"]
    scenes.browse_index.table().put_item(
        Item={
            "pk": f"{scenes.PREFIX}-history#episode#test-game#harbor",
            "sk": parent["revision"],
            "payload": json.dumps({**parent, **changes}),
        }
    )
    with pytest.raises(ValueError):
        scenes.pin_episode("test-game", {"episodeId": "harbor", "revision": parent["revision"]})


def test_reorder_is_a_permutation_and_cannot_remove_or_add_scenes(scenes):
    unpack(call(scenes, body=edit()))
    for identity in ("arrival", "departure"):
        created = unpack(call(scenes, "scene", edit(id=identity, episodeId="harbor")))
    parent = created["episodeRecord"]
    for order in ([], ["arrival"], ["arrival", "departure", "invented"]):
        assert (
            call(scenes, body=edit(expectedRevision=parent["revision"], sceneIds=order))[
                "statusCode"
            ]
            == 400
        )
    assert unpack(call(scenes, id="harbor"))["record"]["sceneIds"] == ["arrival", "departure"]
    reordered = unpack(
        call(
            scenes,
            body=edit(expectedRevision=parent["revision"], sceneIds=["departure", "arrival"]),
        )
    )["record"]
    assert reordered["sceneIds"] == ["departure", "arrival"]


def test_map_scene_selection_is_explicit_same_game_and_history_backed(scenes):
    unpack(call(scenes, body=edit()))
    key = "games/test-game/assets/map-one/original/map.png"
    scenes.browse_index.table().put_item(
        Item={
            "pk": scenes.browse_index.partition("test-game", "all"),
            "sk": key,
            "observed": 1,
            "payload": json.dumps(
                {
                    "key": key,
                    "contentType": "image/png",
                    "kind": "map",
                    "metadata": {"extra": {}},
                }
            ),
        }
    )
    initial = unpack(call(scenes, "scene", edit(id="journey", episodeId="harbor", type="map")))[
        "record"
    ]
    assert initial["type"] == "map" and not initial.get("mapAssetKey")
    body = edit(
        id="journey",
        episodeId="harbor",
        type="map",
        mapAssetKey=key,
        expectedRevision=initial["revision"],
    )
    selected = unpack(call(scenes, "scene", body))["record"]
    assert selected["mapAssetKey"] == key
    assert (
        scenes.pin_scene(
            "test-game",
            {"episodeId": "harbor", "sceneId": "journey", "revision": initial["revision"]},
        )
        == initial
    )
    for invalid in [key.replace("test-game", "other-game"), "missing", key + ".missing"]:
        assert (
            call(
                scenes,
                "scene",
                {
                    **body,
                    "expectedRevision": selected["revision"],
                    "operationId": uuid.uuid4().hex,
                    "mapAssetKey": invalid,
                },
            )["statusCode"]
            == 400
        )
    cleared = unpack(
        call(
            scenes,
            "scene",
            {
                **body,
                "expectedRevision": selected["revision"],
                "operationId": uuid.uuid4().hex,
                "mapAssetKey": None,
            },
        )
    )["record"]
    assert cleared["mapAssetKey"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"contentType": "image/svg+xml"},
        {"contentType": "video/mp4"},
        {"lineageWarning": "Missing provenance"},
        {"metadata": {"extra": {"relationshipRole": "processing"}}},
    ],
)
def test_map_selection_rejects_non_reference_assets(scenes, changes):
    key = "games/test-game/assets/map-one/original/map.png"
    scenes.browse_index.table().put_item(
        Item={
            "pk": scenes.browse_index.partition("test-game", "all"),
            "sk": key,
            "observed": 1,
            "payload": json.dumps(
                {
                    "key": key,
                    "contentType": "image/png",
                    "kind": "map",
                    "metadata": {"extra": {}},
                    **changes,
                }
            ),
        }
    )
    with pytest.raises(ValueError):
        scenes.map_asset(importlib.import_module("index"), "test-game", key)


def test_scene_inputs_are_owned_persistent_and_archive_guarded(scenes):
    import boto3
    import os
    game, key = 'test-game', 'games/test-game/assets/context/original/map.png'
    boto3.resource('dynamodb').Table(os.environ['CATALOG_TABLE']).put_item(Item={'pk': 'GAME#test-game', 'sk': 'CHARACTER#guide', 'id': 'guide', 'gameId': game})
    scenes.browse_index.table().put_item(Item={'pk': scenes.browse_index.partition(game, 'all'), 'sk': key, 'observed': 'one', 'payload': json.dumps({'key': key, 'kind': 'map', 'contentType': 'image/png', 'metadata': {}})})
    unpack(call(scenes, body=edit()))
    inputs = {'schemaVersion': 1, 'characterIds': ['guide'], 'sourceKeys': [], 'contextKeys': [key]}
    body = edit(id='arrival', episodeId='harbor', generationInputs=inputs)
    first = unpack(call(scenes, 'scene', body))['record']
    updated = unpack(call(scenes, 'scene', edit(id='arrival', episodeId='harbor', description='At dusk', expectedRevision=first['revision'])))['record']
    assert updated['generationInputs'] == inputs
    assert scenes.pin_scene(game, {'episodeId': 'harbor', 'sceneId': 'arrival', 'revision': first['revision']})['generationInputs'] == inputs
    import asset_archive
    assert asset_archive.current_references(game, key)
    for change in ({'characterIds': ['missing']}, {'contextKeys': ['games/other/map.png']}, {'contextKeys': [key, key]}):
        response = call(scenes, 'scene', edit(id='arrival', episodeId='harbor', expectedRevision=updated['revision'], generationInputs={**inputs, **change}))
        assert response['statusCode'] == 400, response
