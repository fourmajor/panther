"""Storyboard cuts own immutable takes; partial footage cannot claim completion."""

import copy
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "infra/lambda/media-api"))
import storyboard_videos as videos  # noqa: E402


def example():
    scene = {
        "gameId": "fictional",
        "episodeId": "episode",
        "id": "scene",
        "revision": "a" * 32,
        "storyboard": {
            "revision": "b" * 64,
            "shots": [
                {"shotId": "arrival", "durationSeconds": 4},
                {"shotId": "reaction", "durationSeconds": 3},
            ],
        },
    }
    metadata = {
        "contentType": "video/mp4",
        "extra": {
            "relationshipRole": "finished",
            "sceneRef": {"episodeId": "episode", "sceneId": "scene", "revision": "c" * 32},
            "storyboardShotRef": {"revision": "b" * 64, "shotId": "arrival"},
            "mediaProbe": {"format": {"duration": "8"}},
        },
    }
    selection = {
        "storyboardRevision": "b" * 64,
        "shotId": "arrival",
        "assetKey": "games/fictional/assets/take/original/video.mp4",
        "startSeconds": 2,
    }
    return scene, metadata, selection


def test_take_selection_pins_cut_and_assembly_requires_every_shot():
    scene, metadata, selection = example()
    scene["shotTakes"] = videos.select(scene, selection, metadata, None)
    cut = scene["shotTakes"]["arrival"]
    assert cut["durationSeconds"] == 4 and cut["startSeconds"] == 2
    assert videos.composition(scene)["missingShotIds"] == ["reaction"]
    second = {**selection, "shotId": "reaction", "startSeconds": 0}
    metadata["extra"]["storyboardShotRef"]["shotId"] = "reaction"
    scene["shotTakes"] = videos.select(scene, second, metadata, None)
    assert videos.composition(scene)["ready"]
    assert [cut["shotId"] for cut in videos.composition(scene)["clips"]] == ["arrival", "reaction"]
    scene["shotTakes"] = videos.select(scene, {**second, "assetKey": None}, {}, None)
    assert not videos.composition(scene)["ready"]


@pytest.mark.parametrize(
    "change",
    [
        "short",
        "negative",
        "nan",
        "wrong-shot",
        "wrong-revision",
        "foreign-scene",
        "legacy-multishot",
    ],
)
def test_invalid_cut_cannot_be_selected(change):
    scene, metadata, selection = example()
    if change == "short":
        selection["startSeconds"] = 5
    if change == "negative":
        selection["startSeconds"] = -1
    if change == "nan":
        selection["startSeconds"] = float("nan")
    if change == "wrong-shot":
        metadata["extra"]["storyboardShotRef"]["shotId"] = "reaction"
    if change == "wrong-revision":
        selection["storyboardRevision"] = "d" * 64
    if change == "foreign-scene":
        metadata["extra"]["sceneRef"]["sceneId"] = "other"
    if change == "legacy-multishot":
        metadata["extra"].pop("storyboardShotRef")
    with pytest.raises(ValueError):
        videos.select(scene, selection, metadata, copy.deepcopy(scene))


@pytest.mark.parametrize('planned,available,accepted', [(18,15,True),(10,8,True),(12,8,False)])
def test_near_enough_cuts_use_actual_footage_duration(planned, available, accepted):
    scene, metadata, selection = example()
    scene['storyboard']['shots'] = [{**scene['storyboard']['shots'][0], 'durationSeconds': planned}]
    metadata['extra']['mediaProbe']['format']['duration'] = str(available)
    selection['startSeconds'] = 0
    if not accepted:
        with pytest.raises(ValueError, match='shorter'):
            videos.select(scene, selection, metadata, None)
        return
    scene['shotTakes'] = videos.select(scene, selection, metadata, None)
    assert scene['shotTakes']['arrival']['durationSeconds'] == available
    assert videos.composition(scene)['ready']
    assert videos.composition(scene)['clips'][0]['durationSeconds'] == available
