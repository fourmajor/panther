import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "infra/lambda/media-api"))
import session_pipeline as pipeline


def node(manifest, identity):
    return next(item for item in manifest["nodes"] if item["id"] == identity)


def edge(manifest, source, dest):
    return next(item for item in manifest["edges"] if item["from"] == source and item["to"] == dest)


def test_empty_graph_is_not_started_and_reaches_both_finals():
    manifest = pipeline.view(None, [])["manifest"]
    assert manifest["sessionId"] is None
    assert {item["status"] for item in manifest["nodes"]} == {"pending"}
    assert (
        node(manifest, "session-audio")["column"] < node(manifest, "corrected-transcript")["column"]
    )
    assert node(manifest, "novel-chapter")["final"] and node(manifest, "session-video")["final"]
    assert node(manifest, "novel-chapter")["column"] == node(manifest, "session-video")["column"]
    assert edge(manifest, "corrected-transcript", "novel-brief")["status"] == "pending"
    assert edge(manifest, "corrected-transcript", "video-source-brief")["status"] == "pending"


def test_recorded_jobs_color_nodes_without_painting_later_stages():
    result = pipeline.view(
        None,
        [
            {
                "sessionId": "session-one",
                "sessionTitle": "Night one",
                "kind": "recording",
                "status": "complete",
                "updatedAt": 10,
                "outputKey": "games/example/assets/recording-one/original/recording.json",
            },
            {
                "sessionId": "session-one",
                "kind": "playback",
                "status": "DONE",
                "updatedAt": 12,
                "outputKey": "games/example/assets/recording-one/original/listening.mp3",
            },
            {
                "sessionId": "session-one",
                "kind": "transcription",
                "status": "FAILED",
                "updatedAt": 13,
                "message": "Recognizer rejected the audio.",
                "stages": [
                    {"id": "transcription-window-1", "status": "DONE"},
                    {
                        "id": "transcription-window-2",
                        "status": "FAILED",
                        "message": "Recognizer rejected the audio.",
                    },
                ],
            },
        ],
    )
    manifest = result["manifest"]
    assert result["sessions"][0]["title"] == "Night one"
    assert node(manifest, "session-audio")["status"] == "done"
    assert node(manifest, "listening-copy")["status"] == "done"
    assert node(manifest, "listening-copy")["artifacts"][0]["key"].endswith("listening.mp3")
    assert node(manifest, "transcription")["status"] == "failed"
    assert "rejected" in node(manifest, "transcription")["message"]
    assert node(manifest, "speaker-match")["status"] == "pending"
    assert node(manifest, "novel-chapter")["status"] == "pending"
    assert edge(manifest, "transcription", "speaker-match")["status"] == "failed"
    assert result["sessions"][0]["status"] == "failed"


def test_newer_success_replaces_failure_and_pending_reports_do_not_erase_it():
    manifest = pipeline.view(
        "session-one",
        [
            {
                "sessionId": "session-one",
                "kind": "transcription",
                "status": "failed",
                "updatedAt": 1,
                "stages": [{"id": "processing", "status": "failed", "message": "old"}],
            },
            {
                "sessionId": "session-one",
                "kind": "transcription",
                "status": "done",
                "updatedAt": 2,
                "stages": [
                    {
                        "id": "processing",
                        "status": "done",
                        "outputKey": "games/example/transcript.json",
                    }
                ],
            },
            {
                "sessionId": "session-one",
                "kind": "editorial",
                "status": "running",
                "updatedAt": 3,
                "stages": [
                    {"id": "context", "status": "DONE", "outputKey": "games/example/context.json"},
                    {"id": "correction", "status": "pending"},
                    {"id": "novel-chapter", "status": "pending"},
                ],
            },
        ],
    )["manifest"]
    assert node(manifest, "transcription")["status"] == "done"
    assert node(manifest, "context")["status"] == "done"
    assert node(manifest, "correction")["status"] == "pending"
    assert node(manifest, "novel-chapter")["status"] == "pending"


def test_branches_stay_independent_and_approval_is_not_success():
    manifest = pipeline.view(
        None,
        [
            {
                "sessionId": "session-two",
                "kind": "editorial",
                "status": "READY_FOR_VIDEO_DISCUSSION",
                "updatedAt": 20,
                "stages": [
                    {"id": "corrected-transcript", "status": "DONE"},
                    {
                        "id": "novel-chapter",
                        "status": "DONE",
                        "outputKey": "games/example/chapter.json",
                    },
                    {"id": "video-preflight", "status": "DONE"},
                    {
                        "id": "storyboard-approval",
                        "status": "paused",
                        "message": "Paid video stays blocked until this storyboard revision is approved.",
                    },
                ],
            }
        ],
    )["manifest"]
    assert node(manifest, "novel-chapter")["status"] == "done"
    assert node(manifest, "storyboard-approval")["status"] == "paused"
    assert node(manifest, "video-generation")["status"] == "pending"
    assert node(manifest, "session-video")["status"] == "pending"
    assert (
        pipeline.view(
            None,
            [
                {
                    "sessionId": "session-two",
                    "kind": "episode-render",
                    "status": "RUNNING",
                    "updatedAt": 21,
                    "stages": [{"id": "processing", "status": "running"}],
                }
            ],
        )["sessions"][0]["status"]
        == "running"
    )


def test_sessions_do_not_share_status():
    result = pipeline.view(
        "session-b",
        [
            {
                "sessionId": "session-a",
                "kind": "chapter",
                "status": "done",
                "updatedAt": 5,
                "outputKey": "games/example/a.json",
            },
            {"sessionId": "session-b", "kind": "recording", "status": "running", "updatedAt": 4},
        ],
    )
    assert node(result["manifest"], "novel-chapter")["status"] == "pending"
    assert node(result["manifest"], "session-audio")["status"] == "running"
    assert {item["id"] for item in result["sessions"]} == {"session-a", "session-b"}


def test_unknown_session_is_shown_not_started_and_bad_ids_fail():
    manifest = pipeline.view("session-missing", [])["manifest"]
    assert manifest["sessionId"] == "session-missing"
    assert node(manifest, "session-video")["status"] == "pending"
    with pytest.raises(ValueError):
        pipeline.view("Session One", [])


def test_title_suffix_is_not_a_short_plan_id():
    assert pipeline.session_of({"title": "Video generation · abcd1234"}) is None
    assert (
        pipeline.session_of({"title": "Session finalization · session-2026-11-12-ab12"})
        == "session-2026-11-12-ab12"
    )
    assert pipeline.session_of({"sessionId": "session-one"}) == "session-one"
