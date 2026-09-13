"""Synthetic media only: no game files, cloud credentials or paid inference."""

import copy
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

import click
from click.testing import CliRunner
import pytest
import jsonschema
from pydantic import ValidationError

from panther_journal import video_production as p
from panther_journal.cli import main


def report(**kwargs):
    return {
        "checks": [
            {"category": c, "status": "pass", "evidence": "Synthetic fixture"} for c in p.CHECKS
        ],
        "notes": [],
        "trimStart": 0,
        "trimEnd": 0,
        "brightness": 0,
        "contrast": 1,
        "saturation": 1,
        "reason": "Preserve synthetic footage",
        **kwargs,
    }


def manifest():
    return {
        "schemaVersion": 1,
        "entityType": "VideoProduction",
        "gameId": "synthetic-game",
        "sessionId": None,
        "title": "Synthetic film",
        "complete": False,
        "sourceKeys": [],
        "shots": [
            {
                "id": "one",
                "sceneId": "scene",
                "use": "city",
                "prompt": "Synthetic city",
                "continuity": "Red then blue test card",
                "appearances": [],
                "outSeconds": 2.0,
            }
        ],
    }


def ref(path, name="source"):
    return {
        "path": str(path),
        "sha256": p.digest(path),
        "key": f"games/synthetic-game/assets/{name}/original/{path.name}",
    }


def command(*args):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-nostdin", "-n", *map(str, args)],
        check=True,
        capture_output=True,
        timeout=60,
    )


@pytest.fixture
def media(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/ffprobe required for real media integration tests")
    clip = tmp_path / "clip.mp4"
    command(
        "-f",
        "lavfi",
        "-i",
        "color=red:s=320x180:r=24:d=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        clip,
    )
    wav = tmp_path / "music.wav"
    command("-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=2", wav)
    caption = tmp_path / "captions.json"
    caption.write_text('{"text":"Synthetic test"}')
    m = manifest()
    m["complete"] = True
    shot = m["shots"][0]
    shot["clip"] = ref(clip)
    shot["sounds"] = [
        {
            "role": "music",
            "source": ref(wav, "music"),
            "at": 0.0,
            "sourceStart": 0.0,
            "duration": 2.0,
            "gainDb": -6.0,
            "rightsNote": "Locally generated synthetic sine wave",
        }
    ]
    shot["captions"] = [
        {"start": 0.25, "end": 1.5, "text": "Synthetic test", "source": ref(caption, "captions")}
    ]
    return p.Production.model_validate(m)


def test_manifest_validation():
    m = manifest()
    assert p.Production.model_validate(m).shots[0].nativeAudio == "mute"
    for change in (
        {"complete": True},
        {"gameId": "../bad"},
        {"sourceKeys": ["games/another/assets/a/original/a.mp4"]},
        {"shots": m["shots"] * 2},
    ):
        with pytest.raises((ValidationError, click.ClickException)):
            p.Production.model_validate({**m, **change})
    for change in (
        {"outSeconds": float("nan")},
        {"inSeconds": 2.0},
        {"nativeAudio": "isolated-dialogue"},
        {
            "endImage": {
                "path": "/tmp/a.png",
                "sha256": "a" * 64,
                "key": "games/synthetic-game/assets/a/original/a.png",
            }
        },
    ):
        bad = copy.deepcopy(m)
        bad["shots"][0].update(change)
        with pytest.raises(ValidationError):
            p.Production.model_validate(bad)


def test_complete_gate_and_private_paths(tmp_path):
    with pytest.raises(click.ClickException, match="explicitly complete"):
        p.execute(p.Production.model_validate(manifest()), tmp_path)
    with pytest.raises(click.ClickException, match="outside Git"):
        p.private(Path(__file__).parent)


def test_review_validation():
    p.validate_review(report())
    for value in (
        report(contrast=2),
        report(trimStart=float("nan")),
        report(checks=[]),
        report(trimEnd=-1),
        report(brightness=True),
    ):
        with pytest.raises((click.ClickException, jsonschema.ValidationError)):
            p.validate_review(value)


def test_checkpoint_retry_preserves_partial_and_verifies_completed(tmp_path):
    def interrupted(folder):
        (folder / "partial.txt").write_text("keep me")
        raise p.local.Deferred()

    with pytest.raises(p.local.Deferred):
        p.stage(tmp_path, "sample", "id", interrupted)
    folder, result = p.stage(tmp_path, "sample", "id", lambda d: {"ok": True})
    assert result == {"ok": True}
    assert len(list((tmp_path / "sample").glob("*/partial.txt"))) == 1
    assert p.stage(tmp_path, "sample", "id", lambda _: pytest.fail("reran"))[0] == folder
    with pytest.raises(click.ClickException, match="inputs changed"):
        p.stage(tmp_path, "sample", "changed", lambda _: {})


def test_snapshot_checks_checksum_and_remote_identity(media, tmp_path, monkeypatch):
    target = tmp_path / "snapshot"
    target.mkdir()
    monkeypatch.setattr(p.cloud, "configuration", lambda: {})
    monkeypatch.setattr(p.cloud, "api", lambda *a, **kw: {"sha256": "wrong", "size": 1})
    with pytest.raises(click.ClickException, match="immutable Panther"):
        p.snapshot(media, target, verify_cloud=True)
    path = Path(media.shots[0].clip.path)
    path.write_bytes(b"changed")
    with pytest.raises(click.ClickException, match="checksum"):
        p.snapshot(media, target, verify_cloud=False)


def test_real_finishing_and_idempotency(media, tmp_path):
    calls = []

    def reviewer(folder, images, data):
        assert all(image.exists() for image in images)
        calls.append(data["stage"])
        return report(trimStart=0.5, trimEnd=0.25)

    original = p.digest(Path(media.shots[0].clip.path))
    folder, result = p.execute(media, tmp_path / "runs", verify_cloud=False, reviewer=reviewer)
    assert result["status"] == "AI_REVIEWED"
    assert calls == ["shot-continuity", "revised-shot-review", "finished-sequence"]
    assert result["edits"][0]["start"] == 0  # Sound and caption preservation guard.
    assert result["delivery"]["technicalQc"] == "passed"
    assert result["delivery"]["captionCount"] == 1
    assert result["sound"]["measurement"]["peakPassed"]
    assert "00:00:00.250 --> 00:00:01.500" in Path(result["delivery"]["captions"]).read_text()
    assert not result["sound"]["measurement"]["silent"]
    native = Path(result["sound"]["stems"][0])
    assert p.measure_sound(native, tmp_path)[
        "silent"
    ]  # Native 440Hz tone removed, not in music stem.
    streams = p.probe(result["delivery"]["browser"], tmp_path)["streams"]
    assert [s["codec_name"] for s in streams] == ["h264", "aac"]
    assert result["delivery"]["browserCaptions"] == "burned-in"
    assert result["delivery"]["browserAudioGainDb"] == -1.5
    master_sound = result["delivery"]["audioQc"]["master.mov"]
    browser_sound = result["delivery"]["audioQc"]["browser.mp4"]
    assert browser_sound["peakPassed"]
    assert browser_sound["input_i"] == pytest.approx(master_sound["input_i"] - 1.5, abs=0.3)
    pixels = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "0.5",
            "-i",
            result["delivery"]["browser"],
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    # White caption pixels actually appear on the red synthetic footage.
    assert (
        sum(
            r > 200 and g > 200 and b > 200
            for r, g, b in zip(pixels[::3], pixels[1::3], pixels[2::3])
        )
        > 100
    )
    assert p.digest(Path(media.shots[0].clip.path)) == original
    second, again = p.execute(
        media,
        tmp_path / "runs",
        verify_cloud=False,
        reviewer=lambda *args: pytest.fail("Completed AI stage reran"),
    )
    assert second == folder and again == result
    plan, files = p.package(folder, result)
    doc = json.loads(files[0][1].read_text())
    assert doc["sourceKeys"] == result["sourceKeys"]
    assert str(tmp_path) not in json.dumps(doc)
    assert len(files) == 10
    Path(result["delivery"]["browser"]).write_bytes(b"corrupted")
    with pytest.raises(click.ClickException, match="checkpoint changed"):
        p.execute(media, tmp_path / "runs", verify_cloud=False, reviewer=reviewer)


def test_unresolved_continuity_is_working_draft_not_owner_gate(media, tmp_path):
    def reviewer(*args):
        value = report()
        value["checks"][2].update(status="fail", evidence="Synthetic hand continuity failure")
        return value

    _, result = p.execute(media, tmp_path / "runs", verify_cloud=False, reviewer=reviewer)
    assert result["status"] == "WORKING_DRAFT"
    assert Path(result["delivery"]["browser"]).exists()


def test_cli_schema_and_invalid_inputs(tmp_path):
    result = CliRunner().invoke(main, ["video", "production", "schema"])
    assert result.exit_code == 0
    assert json.loads(result.output)["properties"]["entityType"]["const"] == "VideoProduction"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest()))
    result = CliRunner().invoke(
        main,
        ["video", "production", "run", str(manifest_path), "--work-dir", str(tmp_path / "runs")],
    )
    assert result.exit_code != 0
    assert "explicitly complete" in result.output


def test_preparation_selects_profiles_and_never_approves(tmp_path):
    plan = p.Production.model_validate(manifest())
    folder, result = p.execute(
        plan,
        tmp_path / "runs",
        mode="prepare",
        verify_cloud=False,
        reviewer=lambda *a: pytest.fail("No images to review"),
    )
    assert result["generationApproved"] is False
    generated = json.loads(next(folder.glob("preparation/*/generation-manifest.json")).read_text())
    assert generated["shots"][0]["model"] == "veo-3.1-fast"
    assert generated["shots"][0]["maxAttempts"] == 1
    for purpose, expected in (
        ("dialogue", "h3-max"),
        ("action", "kling-3-pro"),
        ("default", "veo-3.1-fast"),
    ):
        assert p.model_for(plan.shots[0].model_copy(update={"use": purpose})) == expected


def test_preparation_checks_selected_appearance_start_and_end(media, tmp_path):
    image = tmp_path / "frame.png"
    command("-f", "lavfi", "-i", "color=blue:s=1280x720", "-frames:v", "1", image)
    frame = p.Reference.model_validate(ref(image, "reference"))
    shot = media.shots[0].model_copy(
        update={
            "use": "action",
            "startImage": frame,
            "endImage": frame,
            "appearances": [p.Appearance(characterId="hero", reference=frame)],
        }
    )
    plan = media.model_copy(update={"shots": [shot], "complete": False})
    calls = []

    def reviewer(folder, images, data):
        calls.append(data)
        assert len(images) == 3
        value = report()
        value["checks"][0].update(status="uncertain", evidence="Synthetic image has no character")
        return value

    folder, result = p.execute(
        plan, tmp_path / "prepared", mode="prepare", verify_cloud=False, reviewer=reviewer
    )
    assert result["status"] == "PREPARATION_WORKING_DRAFT"
    assert not result["generationApproved"]
    generated = json.loads(next(folder.glob("preparation/*/generation-manifest.json")).read_text())
    assert generated["shots"][0]["model"] == "kling-3-pro-image"
    assert generated["shots"][0]["endImage"]["sha256"] == frame.sha256
    assert calls[0]["stage"] == "composition-preparation"


def test_publish_uses_verified_sources_and_is_retryable(media, tmp_path, monkeypatch):
    monkeypatch.setattr(p.cloud, "configuration", lambda: {})
    assets = {
        r.key: {
            "sha256": base64.b64encode(bytes.fromhex(r.sha256)).decode(),
            "size": Path(r.path).stat().st_size,
        }
        for r in p.references(media)
    }

    def api(config, method, route, *, params):
        assert method == "GET" and route == "/object-url"
        if params["key"] not in assets:
            raise click.ClickException("Object not found")
        return assets[params["key"]]

    monkeypatch.setattr(p.cloud, "api", api)
    folder, result = p.execute(media, tmp_path / "verified-runs", reviewer=lambda *a: report())
    uploads = []

    def upload(**kw):
        uploads.append(kw)
        file = kw["file"]
        key = f"games/{kw['game']}/assets/{kw['asset']}/original/{file.name}"
        meta = json.loads(kw["metadata"].read_text())
        # /uploads owns the stored metadata schema version; callers may not supply it.
        assert set(meta) <= {
            "title", "description", "category", "characterIds", "sessionId",
            "tags", "sourceKeys", "extra",
        }
        assert meta["extra"]["generation"]["cost"] == {"status": "subscription"}
        assets[key] = {
            "sha256": base64.b64encode(bytes.fromhex(p.digest(file))).decode(),
            "size": file.stat().st_size,
            "metadata": meta,
        }

    monkeypatch.setattr(p.cloud.upload, "callback", upload)
    published = p.publish(folder)
    assert len(uploads) == 10
    assert published == p.publish(folder)
    assert len(uploads) == 10
    assert assets[published["browser"]]["metadata"]["sourceKeys"] == [published["provenance"]]
    assert (
        assets[published["stem-dialogue"]]["metadata"]["extra"]["relationshipRole"]
        == "intermediate"
    )
    doc = json.loads((folder / "publication" / "production.json").read_text())
    assert str(tmp_path) not in json.dumps(doc)
    assert media.shots[0].clip.key in doc["sourceKeys"]
    assert doc["manifest"]["shots"][0]["captions"][0]["text"] == "Synthetic test"
    assets[published["browser"]]["metadata"]["category"] = "canonical-source"
    with pytest.raises(click.ClickException, match="metadata conflicts"):
        p.publish(folder)


def test_multiple_shots_cues_follow_final_timeline(media, tmp_path):
    second = media.shots[0].model_copy(deep=True, update={"id": "two"})
    plan = media.model_copy(update={"shots": [media.shots[0], second]})
    calls = []

    def reviewer(folder, images, data):
        calls.append(data)
        return report()

    _, result = p.execute(plan, tmp_path / "runs", verify_cloud=False, reviewer=reviewer)
    assert result["delivery"]["duration"] == 4
    assert "00:00:02.250 --> 00:00:03.500" in Path(result["delivery"]["captions"]).read_text()
    assert any(c.get("previousShotEndingIsLastImage") for c in calls)
    assert len(calls[-1]["timeline"]) == 2


def test_no_generation_capability_in_finishing():
    source = Path(p.__file__).read_text()
    assert "video.submit(" not in source and "Fal(" not in source
    assert "video.approve(" not in source
    assert "forced_login_method" in Path(p.local.__file__).read_text()


@pytest.mark.skipif(
    os.environ.get("PANTHER_VIDEO_AI_SMOKE") != "1",
    reason="Explicit local subscription smoke test only",
)
def test_real_subscription_finishing(media, tmp_path):
    folder, result = p.execute(media, tmp_path / "subscription-runs", verify_cloud=False)
    assert result["status"] in {"AI_REVIEWED", "WORKING_DRAFT"}
    assert result["delivery"]["technicalQc"] == "passed"
    print(f"\nPrivate subscription smoke result: {folder}")
