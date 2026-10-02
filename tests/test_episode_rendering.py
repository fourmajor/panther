"""Synthetic media verifies episode ordering and preserved sound, without provider calls."""

import shutil
import subprocess

import click
import pytest

from panther_journal import episode_rendering as rendering
from panther_journal.video_production import digest, probe


def manifest(paths):
    scenes = [
        {
            "sceneRef": {"episodeId": "arrival", "sceneId": f"scene-{i}", "revision": "a" * 32},
            "assetKey": f"games/fictional-game/assets/clip-{i}/original/clip.mp4",
            "sha256": digest(p),
            "size": p.stat().st_size,
        }
        for i, p in enumerate(paths)
    ]
    return {
        "schemaVersion": 1,
        "entityType": "EpisodeComposition",
        "gameId": "fictional-game",
        "episode": {"id": "arrival", "revision": "b" * 32, "name": "Arrival"},
        "ready": True,
        "scenes": scenes,
        "sourceKeys": [s["assetKey"] for s in scenes],
        "profile": rendering.PROFILE,
    }


def test_freeze_fails_missing_output_without_download(monkeypatch):
    monkeypatch.setattr(
        rendering.cloud, "api", lambda *a, **k: pytest.fail("No download on incomplete manifest")
    )
    with pytest.raises(click.ClickException, match="complete episode"):
        rendering.freeze({}, {"schemaVersion": 1, "entityType": "EpisodeComposition", "scenes": []})


def test_checksum_requires_pinned_size_and_sha():
    with pytest.raises(click.ClickException, match="checksum"):
        rendering.checksum({"sha256": "not-checksum", "size": 1})


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required"
)
def test_real_assembly_scene_order_audio_and_resume(tmp_path):
    paths = []
    for index, (color, frequency) in enumerate((("red", 440), ("blue", 880))):
        path = tmp_path / f"input-{index}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=160x90:r=24:d=1",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=48000:duration=1",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(path),
            ],
            check=True,
        )
        paths.append(path)
    plan = manifest(paths)
    folder = tmp_path / "attempt"
    folder.mkdir()
    result = rendering.assemble(plan, paths, folder)
    output = folder / result["output"]
    assert result["sceneHasAudio"] == [True, True]
    assert result["duration"] == pytest.approx(2, abs=0.12)
    assert "ffmpeg version" in result["tool"]
    assert "perceptual" in result["verification"]
    streams = probe(output, folder)["streams"]
    assert any(s["codec_name"] == "aac" for s in streams)
    for instant, dominant in ((0.4, 0), (1.4, 2)):
        pixels = subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(instant),
                "-i",
                str(output),
                "-frames:v",
                "1",
                "-vf",
                "scale=1:1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ]
        )
        assert pixels[dominant] > 180
    # Decode each timeline segment and measure zero crossings: tones remain audible and ordered.
    import array

    for instant, frequency in ((0.2, 440), (1.2, 880)):
        data = subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(instant),
                "-i",
                str(output),
                "-t",
                "0.5",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "48000",
                "-f",
                "s16le",
                "-",
            ]
        )
        samples = array.array("h", data)
        crossings = sum(a < 0 <= b for a, b in zip(samples, samples[1:]))
        assert crossings / 0.5 == pytest.approx(frequency, abs=8)
        assert max(samples) > 1000
    assert all(digest(p) == s["sha256"] for p, s in zip(paths, plan["scenes"]))
    with pytest.raises(click.ClickException):
        rendering.assemble(plan, paths, folder)  # FFmpeg never overwrites an existing output.


def test_changed_scene_bytes_rejected(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"original")
    plan = manifest([path])
    path.write_bytes(b"changed")
    with pytest.raises(click.ClickException, match="checksum"):
        rendering.assemble(plan, [path], tmp_path)


def test_cli_registration():
    from panther_journal.video_library import videos

    assert "render-episode" in videos.commands
    assert "publish-episode" in videos.commands


def test_resume_checks_completed_bytes(tmp_path):
    from panther_journal.video_production import stage

    folder = tmp_path / "run"
    folder.mkdir()

    def build(attempt):
        (attempt / "output.mp4").write_bytes(b"synthetic output")
        return {"output": "output.mp4"}

    attempt, result = stage(folder, "assembly", "identity", build)
    assert stage(
        folder, "assembly", "identity", lambda _: pytest.fail("Must reuse checkpoint")
    ) == (attempt, result)
    (attempt / "output.mp4").write_bytes(b"tampered")
    with pytest.raises(click.ClickException, match="checkpoint changed"):
        stage(folder, "assembly", "identity", build)


def test_publish_exact_inputs_hidden_manifest_and_uncertain_resume(tmp_path, monkeypatch):
    import base64
    import hashlib
    import json
    from panther_journal.video_production import stage, write_json

    source = tmp_path / "source.mp4"
    source.write_bytes(b"synthetic finished source")
    plan = manifest([source])
    plan["compositionHash"] = "d" * 64
    identity = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    folder = tmp_path / identity
    folder.mkdir()
    write_json(folder / "manifest.json", plan)

    def build(attempt):
        output = attempt / "episode.mp4"
        output.write_bytes(b"synthetic assembled output")
        return {
            "output": output.name,
            "sha256": digest(output),
            "size": output.stat().st_size,
            "tool": "ffmpeg version synthetic",
            "duration": 1,
        }

    attempt, result = stage(folder, "assembly", identity, build)
    result = {
        **result,
        "output": str((attempt / result["output"]).relative_to(folder)),
        "manifestSha256": digest(folder / "manifest.json"),
    }
    write_json(folder / "result.json", result)
    stored, uploads = {}, []
    monkeypatch.setattr(rendering.cloud, "configuration", lambda: {})

    def api(_config, method, route, **kwargs):
        assert method == "GET" and route == "/object-url"
        key = kwargs["params"]["key"]
        if key not in stored:
            raise click.ClickException("Object not found")
        return stored[key]

    monkeypatch.setattr(rendering.cloud, "api", api)

    def upload(**kwargs):
        key = f"games/{kwargs['game']}/assets/{kwargs['asset']}/original/{kwargs['file'].name}"
        metadata = json.loads(kwargs["metadata"].read_text())
        stored[key] = {
            "sha256": base64.b64encode(bytes.fromhex(digest(kwargs["file"]))).decode(),
            "size": kwargs["file"].stat().st_size,
            "metadata": metadata,
        }
        uploads.append((kwargs["kind"], metadata))
        click.echo(json.dumps({"key": key}))

    monkeypatch.setattr(rendering.cloud.upload, "callback", upload)
    receipt = rendering.publish(folder)
    assert [kind for kind, _ in uploads] == ["episode-composition", "tv-episode"]
    assert uploads[0][1]["extra"]["relationshipRole"] == "intermediate"
    assert uploads[1][1]["sourceKeys"] == [receipt["composition"]["key"]]
    assert uploads[1][1]["extra"]["generation"]["inference"] == "not-applicable"
    provenance = json.loads((folder / "composition.json").read_text())
    assert provenance["sourceKeys"] == plan["sourceKeys"]
    assert provenance["inputArtifacts"]["scene-0"]["sceneRef"] == plan["scenes"][0]["sceneRef"]
    # A lost local receipt after a successful immutable upload is recovered without another upload.
    (folder / "published-browser.json").unlink()
    assert rendering.publish(folder)["browser"]["key"] == receipt["browser"]["key"]
    assert len(uploads) == 2
    result["tool"] = "invented tool provenance"
    (folder / "result.json").write_text(json.dumps(result))
    with pytest.raises(click.ClickException, match="result changed"):
        rendering.publish(folder)


def composition_with_hash(tmp_path):
    import hashlib
    import json

    source = tmp_path / "source.mp4"
    source.write_bytes(b"finished scene")
    value = manifest([source])
    value.pop("profile")
    value["episode"]["sceneIds"] = ["scene-0"]
    for scene in value["scenes"]:
        scene.pop("sha256")
        scene.pop("size")
    value["compositionHash"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return value, source


def test_freeze_verifies_hash_order_and_download_identity(tmp_path, monkeypatch):
    import base64
    import hashlib
    import json

    value, source = composition_with_hash(tmp_path)
    monkeypatch.setattr(
        rendering.cloud,
        "api",
        lambda *a, **k: {
            "size": source.stat().st_size,
            "sha256": base64.b64encode(bytes.fromhex(digest(source))).decode(),
        },
    )
    frozen = rendering.freeze({}, value)
    assert frozen["scenes"][0]["sha256"] == digest(source)
    assert frozen["sourceKeys"] == value["sourceKeys"]
    value["episode"]["sceneIds"] = ["another-scene"]
    with pytest.raises(click.ClickException, match="checksum"):
        rendering.freeze({}, value)
    canonical = {k: v for k, v in value.items() if k != "compositionHash"}
    value["compositionHash"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(click.ClickException, match="order"):
        rendering.freeze({}, value)


def test_download_network_error_has_no_signed_url(tmp_path, monkeypatch):
    import base64

    value, source = composition_with_hash(tmp_path)
    scene = {**value["scenes"][0], "sha256": digest(source), "size": source.stat().st_size}
    monkeypatch.setattr(
        rendering.cloud,
        "api",
        lambda *a, **k: {
            "sha256": base64.b64encode(bytes.fromhex(digest(source))).decode(),
            "size": source.stat().st_size,
            "url": "https://private-bucket.s3.amazonaws.com/secret?token=private",
        },
    )

    def failure(*a, **k):
        raise rendering.requests.RequestException("private signed token")

    monkeypatch.setattr(rendering.requests, "get", failure)
    with pytest.raises(click.ClickException, match="interrupted") as exc:
        rendering.download({}, scene, tmp_path)
    assert "token" not in str(exc.value)


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required"
)
def test_silent_scene_gets_explicit_silent_track(tmp_path):
    path = tmp_path / "silent.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=160x90:r=24:d=0.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    folder = tmp_path / "attempt"
    folder.mkdir()
    result = rendering.assemble(manifest([path]), [path], folder)
    assert result["sceneHasAudio"] == [False]
    output = folder / result["output"]
    assert any(s["codec_type"] == "audio" for s in probe(output, folder)["streams"])
    audio = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(output), "-vn", "-f", "s16le", "-"]
    )
    assert all(byte == 0 for byte in audio)
