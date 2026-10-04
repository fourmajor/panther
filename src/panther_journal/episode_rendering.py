"""Deterministic local assembly of pinned, already finished scene videos. No inference."""

import base64
from contextlib import redirect_stdout
import hashlib
import io
import json
import math
from pathlib import Path
from urllib.parse import urlparse

import click
import requests

from panther_journal import cloud, generation_metadata
from panther_journal.video_production import (
    digest,
    ffmpeg,
    input_args,
    lock,
    private,
    probe,
    run_tool,
    stage,
    write_json,
)

PROFILE = "episode-sdr-720p24-aac-v1"


def checksum(remote):
    try:
        value = base64.b64decode(remote["sha256"], validate=True)
        size = remote["size"]
        if len(value) != 32 or type(size) is not int or not 0 < size <= cloud.MAX_UPLOAD_BYTES:
            raise ValueError()
        return value.hex(), size
    except (KeyError, ValueError, TypeError):
        raise click.ClickException("Scene output has no valid immutable checksum/size") from None


def freeze(config, composition):
    scenes = composition.get("scenes")
    if (
        composition.get("entityType") != "EpisodeComposition"
        or composition.get("schemaVersion") != 1
        or composition.get("ready") is not True
        or not isinstance(scenes, list)
        or not 1 <= len(scenes) <= 20
    ):
        raise click.ClickException(
            "Rendering requires a complete episode with 1–20 selected scene outputs"
        )
    canonical = {k: v for k, v in composition.items() if k != "compositionHash"}
    expected_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    if composition.get("compositionHash") != expected_hash:
        raise click.ClickException("Episode composition checksum failed")
    if composition["episode"].get("sceneIds") != [scene["sceneRef"]["sceneId"] for scene in scenes]:
        raise click.ClickException("Composition scene order differs from its pinned episode")
    if composition.get("sourceKeys") != [scene["assetKey"] for scene in scenes]:
        raise click.ClickException("Composition inputs differ from ordered selected outputs")
    game = cloud.slug(composition["gameId"])
    result = json.loads(json.dumps(composition))
    if len({s["sceneRef"]["sceneId"] for s in scenes}) != len(scenes):
        raise click.ClickException("Episode contains duplicate scenes")
    for scene in result["scenes"]:
        key = scene["assetKey"]
        if (
            not key.startswith(f"games/{game}/")
            or scene["sceneRef"]["episodeId"] != composition["episode"]["id"]
        ):
            raise click.ClickException("Scene output does not belong to this episode/game")
        remote = cloud.api(config, "GET", "/object-url", params={"key": key})
        sha, size = checksum(remote)
        scene.update(sha256=sha, size=size)
    result["profile"] = PROFILE
    return result


def download(config, scene, folder):
    suffix = Path(scene["assetKey"]).suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv"}:
        raise click.ClickException(
            "Episode assembly accepts finished MP4, MOV or MKV scene containers"
        )
    target = folder / f"{scene['sha256']}{suffix}"
    if target.exists():
        if (
            target.is_symlink()
            or target.stat().st_size != scene["size"]
            or digest(target) != scene["sha256"]
        ):
            raise click.ClickException(
                "Retained scene bytes changed; originals were not overwritten"
            )
        return target
    remote = cloud.api(config, "GET", "/object-url", params={"key": scene["assetKey"]})
    if checksum(remote) != (scene["sha256"], scene["size"]):
        raise click.ClickException("Immutable scene output changed")
    url = urlparse(remote.get("url", ""))
    if url.scheme != "https" or not (url.hostname or "").endswith(".amazonaws.com"):
        raise click.ClickException("Invalid signed scene download destination")
    # Retain interrupted downloads separately; a subsequent attempt never overwrites them.
    import uuid

    partial = folder / f"download-{uuid.uuid4().hex}.partial"
    try:
        with requests.get(
            remote["url"], stream=True, timeout=(15, 300), allow_redirects=False
        ) as response:
            if response.status_code != 200:
                raise click.ClickException(
                    "Scene download failed; retry without regenerating footage"
                )
            size = 0
            with partial.open("xb") as out:
                for chunk in response.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > scene["size"]:
                        raise click.ClickException("Scene download exceeded its pinned size")
                    out.write(chunk)
    except requests.RequestException:
        raise click.ClickException(
            "Scene download interrupted; retained partials can be inspected privately"
        ) from None
    if size != scene["size"] or digest(partial) != scene["sha256"]:
        raise click.ClickException("Scene download checksum failed; retained for investigation")
    partial.rename(target)
    return target


def assemble(manifest, paths, folder):
    """Normalize finished tracks without creative edits, muting, or fabricated stems."""
    if len(paths) != len(manifest["scenes"]) or not 1 <= len(paths) <= 24:
        raise click.ClickException("Every ordered scene needs exactly one output")
    if (folder / "episode.mp4").exists() or any(folder.glob("scene-*.mkv")):
        raise click.ClickException(
            "Assembly outputs already exist; use verified checkpoints or a fresh attempt"
        )
    durations, audio = [], []
    for path, scene in zip(paths, manifest["scenes"], strict=True):
        if digest(path) != scene["sha256"] or path.stat().st_size != scene["size"]:
            raise click.ClickException("Scene checksum failed before assembly")
        info = probe(path, folder)
        videos = [s for s in info["streams"] if s["codec_type"] == "video"]
        if len(videos) != 1 or videos[0].get("color_transfer") in {"smpte2084", "arib-std-b67"}:
            raise click.ClickException("Episode profile requires one SDR video track per scene")
        if max(videos[0]["width"], videos[0]["height"]) > 4096:
            raise click.ClickException("Episode profile supports inputs through 4K")
        available = float(info["format"]["duration"])
        duration = scene.get('durationSeconds', available)
        start = scene.get('startSeconds', 0)
        if type(duration) not in (int, float) or type(start) not in (int, float) or not all(math.isfinite(value) for value in (duration, start, available)) or not 0 < duration <= 300 or start < 0 or start + duration > available + .001:
            raise click.ClickException("Each finished scene must be at most five minutes")
        durations.append(duration)
        tracks = [s for s in info["streams"] if s["codec_type"] == "audio"]
        if len(tracks) > 1:
            raise click.ClickException(
                "Episode profile requires a single selected mixed audio track per scene"
            )
        audio.append(bool(tracks))
    if sum(durations) > 1800:
        raise click.ClickException("Episode profile allows at most thirty minutes")
    clips = []
    for index, (path, duration, has_audio) in enumerate(zip(paths, durations, audio, strict=True)):
        output = folder / f"scene-{index:02d}.mkv"
        args = input_args(path)
        if not has_audio:
            args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        if manifest['scenes'][index].get('startSeconds', 0):
            args += ['-ss', manifest['scenes'][index]['startSeconds']]
        args += [
            "-map",
            "0:v:0",
            "-map",
            "0:a:0" if has_audio else "1:a:0",
            "-t",
            duration,
            "-vf",
            "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=24,setsar=1,format=yuv420p",
            "-af",
            "aresample=48000,apad",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-map_metadata",
            "-1",
            output,
        ]
        ffmpeg(folder, f"normalize-{index}", args)
        clips.append(output)
    playlist = folder / "ordered-clips.txt"
    playlist.write_text("".join(f"file '{p.name}'\n" for p in clips))
    output = folder / "episode.mp4"
    ffmpeg(
        folder,
        "assemble",
        [
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            playlist,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-af",
            "asetpts=N/SR/TB",
            "-movflags",
            "+faststart",
            output,
        ],
    )
    ffmpeg(folder, "decode", [*input_args(output), "-f", "null", "-"])
    measured = float(probe(output, folder)["format"]["duration"])
    if abs(measured - sum(durations)) > len(paths) / 24 + 0.2:
        raise click.ClickException("Assembled episode duration failed verification")
    return {
        "output": output.name,
        "sha256": digest(output),
        "size": output.stat().st_size,
        "duration": measured,
        "sceneDurations": durations,
        "sceneHasAudio": audio,
        "audioPolicy": "preserve selected scene mixed soundtracks; silence only where source has no audio",
        "tool": run_tool(["ffmpeg", "-version"], folder, "version").decode().splitlines()[0],
        "verification": "full technical decode, checksum and duration; no new creative/perceptual review",
    }


def render(game, episode, work_dir):
    config = cloud.configuration()
    current = cloud.api(config, "GET", "/episodes", params={"gameId": game, "id": episode})
    record = current["record"]
    composition = cloud.api(
        config,
        "GET",
        "/episode-composition",
        params={"gameId": game, "episodeId": episode, "revision": record["revision"]},
    )
    manifest = freeze(config, composition)
    identity = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    folder = private(work_dir) / identity
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock(folder, "render.lock"):
        saved = folder / "manifest.json"
        if not saved.exists():
            write_json(saved, manifest)
        elif json.loads(saved.read_text()) != manifest:
            raise click.ClickException("Episode manifest changed")
        inputs = folder / "inputs"
        inputs.mkdir(exist_ok=True, mode=0o700)
        paths = [download(config, s, inputs) for s in manifest["scenes"]]
        attempt, result = stage(
            folder, "assembly", identity, lambda target: assemble(manifest, paths, target)
        )
        result = {
            **result,
            "output": str((attempt / result["output"]).relative_to(folder)),
            "manifestSha256": digest(saved),
        }
        if not (folder / "result.json").exists():
            write_json(folder / "result.json", result)
        elif json.loads((folder / "result.json").read_text()) != result:
            raise click.ClickException("Episode result changed")
    return folder


def publish(folder):
    folder = private(folder)
    with lock(folder, "publication.lock"):
        manifest = json.loads((folder / "manifest.json").read_text())
        result = json.loads((folder / "result.json").read_text())
        identity = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if folder.name != identity or digest(folder / "manifest.json") != result["manifestSha256"]:
            raise click.ClickException("Episode manifest changed before publication")
        attempt, verified = stage(
            folder,
            "assembly",
            identity,
            lambda _: (_ for _ in ()).throw(click.ClickException("Assembly checkpoint incomplete")),
        )
        expected = {
            **verified,
            "output": str((attempt / verified["output"]).relative_to(folder)),
            "manifestSha256": digest(folder / "manifest.json"),
        }
        if result != expected:
            raise click.ClickException("Rendered episode result changed")
        output = folder / result["output"]
        if (
            output.is_symlink()
            or folder not in output.resolve().parents
            or digest(output) != result["sha256"]
        ):
            raise click.ClickException("Rendered episode changed")
        if output.stat().st_size > cloud.MAX_UPLOAD_BYTES:
            raise click.ClickException(
                "Episode exceeds the 1 GiB publication limit; local output retained"
            )
        provenance = folder / "composition.json"
        payload = {
            "schemaVersion": 1,
            "entityType": "EpisodeRender",
            "gameId": manifest["gameId"],
            "composition": manifest,
            "sourceKeys": manifest["sourceKeys"],
            "inputArtifacts": {
                f"scene-{i}": {
                    "key": scene["assetKey"],
                    "sha256": scene["sha256"],
                    "size": scene["size"],
                    "sceneRef": scene["sceneRef"],
                    "generationSceneRef": scene.get("generationSceneRef"),
                }
                for i, scene in enumerate(manifest["scenes"])
            },
            "assembly": {k: v for k, v in result.items() if k != "output"},
        }
        if not provenance.exists():
            write_json(provenance, payload)
        elif json.loads(provenance.read_text()) != payload:
            raise click.ClickException("Episode provenance changed")
        published = {}
        for name, path, kind, sources, role in [
            ("composition", provenance, "episode-composition", [], "intermediate"),
            ("browser", output, "tv-episode", None, "finished"),
        ]:
            if sources is None:
                sources = [published["composition"]["key"]]
            metadata = {
                "title": manifest["episode"]["name"],
                "category": "creative-reimagining",
                "sourceKeys": sources,
                "extra": {
                    "episodeRef": {
                        "episodeId": manifest["episode"]["id"],
                        "revision": manifest["episode"]["revision"],
                    },
                    "compositionHash": manifest.get("compositionHash"),
                    "generation": generation_metadata.local(result["tool"]),
                    "relationshipRole": role,
                },
            }
            meta = folder / f"{name}.metadata.json"
            if not meta.exists():
                write_json(meta, metadata)
            elif json.loads(meta.read_text()) != metadata:
                raise click.ClickException("Publication metadata changed")
            receipt = folder / f"published-{name}.json"
            if receipt.exists():
                record = json.loads(receipt.read_text())
                remote = cloud.api(
                    cloud.configuration(), "GET", "/object-url", params={"key": record["key"]}
                )
                if checksum(remote) != (digest(path), path.stat().st_size):
                    raise click.ClickException("Published episode checksum changed")
                if any(remote.get("metadata", {}).get(k) != v for k, v in metadata.items()):
                    raise click.ClickException("Published episode metadata changed")
            else:
                # This is the application's stable reference, never a physical S3 destination.
                # All new writes still obtain their location from the shared server upload builder.
                asset = f"episode-{identity[:32]}"
                key = f"games/{manifest['gameId']}/assets/{asset}/original/{path.name}"
                config = cloud.configuration()
                try:
                    remote = cloud.api(config, "GET", "/object-url", params={"key": key})
                except click.ClickException as exc:
                    if "Object not found" not in str(exc):
                        raise
                    capture = io.StringIO()
                    with redirect_stdout(capture):
                        cloud.upload.callback(
                            file=path,
                            game=manifest["gameId"],
                            asset=asset,
                            kind=kind,
                            metadata=meta,
                            as_json=True,
                        )
                    record = json.loads(capture.getvalue())
                    remote = cloud.api(config, "GET", "/object-url", params={"key": record["key"]})
                else:
                    record = {
                        "key": key,
                        "assetId": asset,
                        "gameId": manifest["gameId"],
                        "kind": kind,
                        "bytes": path.stat().st_size,
                        "sha256": base64.b64encode(bytes.fromhex(digest(path))).decode(),
                    }
                if checksum(remote) != (digest(path), path.stat().st_size):
                    raise click.ClickException("Existing episode asset conflicts; no overwrite")
                if any(remote.get("metadata", {}).get(k) != v for k, v in metadata.items()):
                    raise click.ClickException("Existing episode metadata conflicts; no overwrite")
                write_json(receipt, record)
            published[name] = record
        return published


def register(group):
    @group.command("render-episode")
    @click.option("--game", required=True)
    @click.option("--episode", required=True)
    @click.option("--work-dir", required=True, type=click.Path(path_type=Path))
    @click.option(
        "--publish",
        "publish_output",
        is_flag=True,
        help="Explicitly publish the finished assembly after rendering.",
    )
    def command(game, episode, work_dir, publish_output):
        """Join every selected scene, in episode order, preserving its audio."""
        folder = render(cloud.slug(game), cloud.slug(episode), work_dir)
        click.echo(json.dumps(publish(folder), indent=2) if publish_output else str(folder))

    @group.command("publish-episode")
    @click.argument("run_directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
    def publish_command(run_directory):
        """Publish an assembled episode immutably through Panther authentication."""
        click.echo(json.dumps(publish(run_directory), indent=2))
