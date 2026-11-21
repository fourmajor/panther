"""Read-only session list and detail assembled from catalog assets and pipeline runs.

Classification is an explicit kind map. Add a published kind to FINAL_KINDS to show it
with final assets. Every other kind, including kinds this module has never seen, stays
visible under intermediary assets.
"""

import re
from datetime import datetime, timezone

from session_pipeline import normalize, session_of, slug, stamp
from workflow_hierarchy import LABELS as PIPELINE_LABELS

FINAL_KINDS = frozenset({
    "tv-episode",
    "silly-video",
    "session-video",
    "video",
    "video-thumbnail",
    "thumbnail",
    "poster",
    "cover",
    "transcript-summary",
    "recap",
    "session-recap",
    "novel-chapter",
    "novel",
    "story",
    "recording-playback",
})
# Kinds that are session work even when the session id is only carried in the title suffix.
# Character-scoped model and image jobs are not attached unless they store sessionId.
TITLE_SESSION_KINDS = frozenset({
    "editorial",
    "playback",
    "transcription",
    "video-production",
    "video-generation",
    "session-finalization",
    "scene-render",
    "episode-render",
    "narration",
    "chapter",
    "transcript-summary",
})
DETAIL_KINDS = frozenset({
    "editorial",
    "model",
    "playback",
    "transcription",
    "video-production",
    "video-generation",
    "session-finalization",
})
KIND_LABELS = {
    "tv-episode": "Episode video",
    "silly-video": "Video",
    "session-video": "Session video",
    "video": "Video",
    "video-thumbnail": "Thumbnail",
    "thumbnail": "Thumbnail",
    "poster": "Poster",
    "cover": "Cover",
    "transcript-summary": "Recap",
    "recap": "Recap",
    "session-recap": "Recap",
    "novel-chapter": "Novel chapter",
    "novel": "Novel",
    "story": "Story",
    "recording-playback": "Listening copy",
    "raw-transcript": "Raw transcript",
    "corrected-transcript": "Corrected transcript",
    "edited-transcript": "Edited transcript",
    "transcript": "Transcript",
    "recording": "Source audio",
    "recording-manifest": "Recording manifest",
    "narration": "Narration stem",
    "speech": "Speech stem",
    "voice-performance": "Voice performance",
    "music": "Music stem",
    "model-3d": "Model output",
    "model-provenance": "Model provenance",
    "scene-render": "Render",
    "face-pass": "Face pass",
    "asset-generation": "Generated asset",
}
STATUS_LABELS = {
    "failed": "Failed",
    "running": "Running",
    "queued": "Queued",
    "paused": "Waiting",
    "done": "Done",
    "started": "In progress",
    "recorded": "Recorded",
    "pending": "Not started",
    "unknown": "Unknown",
}
PART = re.compile(r"part-\d{4}\.(?:flac|wav|mp3|m4a|ogg)\Z", re.IGNORECASE)
GENERIC_TITLE = re.compile(
    r"^(?:recording(?:-manifest|-playback)?|(?:raw-|corrected-|edited-)?transcript)\Z",
    re.IGNORECASE,
)
NOISY_TITLE = re.compile(r"[a-f0-9]{24,}|\.(?:json|wav|mp3|flac|md|png|jpe?g|mp4|webm)\Z", re.IGNORECASE)
TRANSCRIPT_KINDS = ("raw-transcript", "transcript", "corrected-transcript", "edited-transcript")
TERMINAL = {"done", "failed", "paused"}
ASSET_PAGES = 30


def classify(asset, finals=None):
    """Return ``final`` or ``intermediary``. Unknown kinds are intermediary, never dropped."""
    chosen = FINAL_KINDS if finals is None else finals
    kind = asset.get("kind") if isinstance(asset.get("kind"), str) else ""
    name = asset.get("name") if isinstance(asset.get("name"), str) else ""
    if PART.fullmatch(name):
        return "intermediary"
    if kind in chosen:
        return "final"
    return "intermediary"


# Kind to the pipeline that produces it when no run output pin is recorded.
# Unknown kinds stay visible under Other work rather than disappearing.
KIND_STAGE = {
    "raw-transcript": "editorial",
    "transcript": "editorial",
    "corrected-transcript": "editorial",
    "edited-transcript": "editorial",
    "recording": "playback",
    "recording-manifest": "playback",
    "recording-playback": "playback",
    "recording-playback-manifest": "playback",
    "recording-checkpoint": "playback",
    "recording-setup": "playback",
    "capture-health": "playback",
    "model-3d": "model",
    "model-provenance": "model",
    "face-pass": "model",
    "scene-render": "scene-render",
    "episode-render": "episode-render",
    "narration": "narration",
    "speech": "narration",
    "voice-performance": "narration",
    "asset-generation": "asset-generation",
    "portrait": "asset-generation",
    "character-turnaround-view": "asset-generation",
}
STAGE_ORDER = (
    "session-finalization",
    "editorial",
    "transcription",
    "playback",
    "model",
    "narration",
    "asset-generation",
    "video-generation",
    "scene-render",
    "episode-render",
    "video-production",
    "other",
)
TYPE_SPECS = (
    ("audio", "Audio", "rows"),
    ("transcripts", "Transcripts", "rows"),
    ("scripts", "Scripts", "rows"),
    ("portraits", "Portraits", "images"),
    ("face-passes", "Face passes", "images"),
    ("images", "Images", "images"),
    ("video", "Video", "rows"),
    ("logs", "Logs and JSON", "rows"),
    ("other", "Other", "rows"),
)
SCRIPT_KINDS = {
    "novel-draft", "novel-outline", "novel-revision", "video-screenplay",
    "video-shooting-script", "video-treatment", "video-audio-script",
}
IMAGE_TYPES = {"portraits", "face-passes", "images"}


def stage_for_kind(kind):
    if kind in KIND_STAGE:
        return KIND_STAGE[kind]
    if kind.startswith(("novel-", "video-", "editorial-")):
        return "editorial"
    return "other"


def asset_type(view):
    """File-type bucket. Unknown kinds land in Other and stay visible."""
    kind = view.get("kind") or ""
    name = (view.get("name") or "").lower()
    preview = view.get("preview")
    if "face" in kind and "pass" in kind:
        return "face-passes"
    if kind in {"portrait", "character-turnaround-view"}:
        return "portraits"
    if "transcript" in kind:
        return "transcripts"
    if kind in SCRIPT_KINDS or kind.endswith("-script") or "screenplay" in kind:
        return "scripts"
    if preview == "audio" or kind in {"recording", "narration", "speech", "voice-performance", "music"}:
        return "audio"
    if preview == "video":
        return "video"
    if preview == "image":
        return "images"
    content = view.get("contentType") or ""
    if (
        content in {"application/json", "text/plain"}
        or name.endswith((".json", ".log", ".txt"))
        or "provenance" in kind
        or kind.endswith("-log")
    ):
        return "logs"
    return "other"


def format_bytes(size):
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    if size < 1024 ** 3:
        return f"{size / 1024 ** 2:.1f} MB"
    return f"{size / 1024 ** 3:.1f} GB"


def size_summary(assets):
    """Count plus total size. Missing sizes never become zero."""
    count = len(assets)
    files = "1 file" if count == 1 else f"{count} files"
    known = [asset["size"] for asset in assets if isinstance(asset.get("size"), int)]
    if not known:
        return {"count": count, "size": None, "summary": files}
    total = sum(known)
    label = format_bytes(total)
    if len(known) != count:
        text = f"{files}, at least {label}"
    else:
        text = f"{files}, {label}"
    return {"count": count, "size": total, "summary": text}


def anchor_for(run_id):
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", run_id).replace("~", "--").strip("-")
    return "pipeline-" + (safe or "run")[:120]


def kind_label(kind):
    if not isinstance(kind, str) or not kind.strip():
        return "Asset"
    if kind in KIND_LABELS:
        return KIND_LABELS[kind]
    return kind.replace("-", " ").strip().capitalize()


def pipeline_label(kind):
    if kind in PIPELINE_LABELS:
        return PIPELINE_LABELS[kind]
    if isinstance(kind, str) and kind.strip():
        return kind.replace("-", " ").strip().capitalize()
    return "Pipeline"


def _clip(value, limit=500):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:limit]


def _metadata(asset):
    metadata = asset.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def explicit_session(asset):
    sid = _metadata(asset).get("sessionId")
    return sid if slug(sid) else None


def session_index(assets):
    """Map asset keys to a session id. One unique source hop is enough; ambiguous links stay unset."""
    by_key = {}
    for asset in assets:
        key = asset.get("key") if isinstance(asset, dict) else None
        if isinstance(key, str) and key not in by_key:
            by_key[key] = asset
    resolved = {key: sid for key, asset in by_key.items() if (sid := explicit_session(asset))}
    for _ in range(4):
        changed = False
        for key, asset in by_key.items():
            if key in resolved:
                continue
            found = []
            for source in asset.get("sourceKeys") or []:
                if isinstance(source, str) and source in resolved:
                    found.append(resolved[source])
            unique = set(found)
            if len(unique) == 1:
                resolved[key] = next(iter(unique))
                changed = True
        if not changed:
            break
    return resolved


def tied_session(item):
    if not isinstance(item, dict):
        return None
    sid = item.get("sessionId")
    if slug(sid):
        return sid
    kind = item.get("kind")
    if kind in TITLE_SESSION_KINDS:
        return session_of(item)
    return None


def _preview(asset):
    mime = asset.get("contentType") if isinstance(asset.get("contentType"), str) else ""
    name = asset.get("name") if isinstance(asset.get("name"), str) else ""
    if mime.startswith("image/") or re.search(r"\.(?:png|jpe?g|webp|gif|avif|svg)\Z", name, re.IGNORECASE):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/") or re.search(r"\.(?:mp4|webm|mov|m4v)\Z", name, re.IGNORECASE):
        return "video"
    return "none"


def _same_game_key(game, key):
    if not isinstance(key, str) or not key.startswith(f"games/{game}/assets/"):
        return None
    if ".." in key.split("/") or re.search(r"[\\\x00-\x1f]", key):
        return None
    return key


def _asset_view(game, asset):
    metadata = _metadata(asset)
    kind = asset.get("kind") if isinstance(asset.get("kind"), str) else "unclassified"
    title = _clip(metadata.get("title"), 160)
    created = asset.get("lastModified") or asset.get("createdAt")
    size = asset.get("size")
    if isinstance(size, bool) or not isinstance(size, (int, float)) or size < 0:
        size = None
    elif isinstance(size, float) and size != size:
        size = None
    else:
        size = int(size)
    thumb = asset.get("thumbnailKey")
    extra = metadata.get("extra") if isinstance(metadata.get("extra"), dict) else {}
    preview = extra.get("preview") if isinstance(extra.get("preview"), dict) else {}
    image = _same_game_key(game, thumb) or _same_game_key(game, preview.get("imageKey"))
    job = extra.get("jobId")
    result = {
        "key": asset.get("key"),
        "kind": kind,
        "kindLabel": kind_label(kind),
        "name": asset.get("name") if isinstance(asset.get("name"), str) else "",
        "title": title,
        "size": size,
        "contentType": asset.get("contentType") if isinstance(asset.get("contentType"), str) else "application/octet-stream",
        "createdAt": created if isinstance(created, (str, int, float)) and not isinstance(created, bool) else None,
        "role": classify(asset),
        "preview": _preview(asset),
        "thumbnailKey": image,
        "jobId": job if isinstance(job, str) and job.strip() else None,
    }
    result["typeId"] = asset_type(result)
    return result


def _people(assets):
    players = []
    seen = set()
    for asset in assets:
        transcript = asset.get("transcript") if isinstance(asset.get("transcript"), dict) else {}
        for person in transcript.get("participants") or []:
            if not isinstance(person, dict):
                continue
            identity = person.get("id")
            if not isinstance(identity, str) or identity in seen:
                continue
            seen.add(identity)
            name = person.get("name") if isinstance(person.get("name"), str) and person["name"].strip() else None
            players.append({"id": identity, "name": name})
    characters = []
    character_ids = set()
    for asset in assets:
        for identity in _metadata(asset).get("characterIds") or []:
            if isinstance(identity, str) and slug(identity) and identity not in character_ids:
                character_ids.add(identity)
                characters.append({"id": identity})
    players.sort(key=lambda person: (person["name"] or person["id"]).casefold())
    characters.sort(key=lambda character: character["id"])
    return players, characters


def _title(assets, session_id, when):
    for asset in assets:
        recording = asset.get("recording") if isinstance(asset.get("recording"), dict) else {}
        name = _clip(recording.get("sessionName"), 160) or _clip(_metadata(asset).get("sessionName"), 160)
        if name:
            return name
    for asset in assets:
        title = _clip(_metadata(asset).get("title"), 160)
        if title and not GENERIC_TITLE.fullmatch(title) and not NOISY_TITLE.search(title):
            return title
    if when:
        return when
    return session_id


def _iso(value):
    stamped = stamp(value)
    if not stamped:
        return None
    return datetime.fromtimestamp(stamped, timezone.utc).isoformat()


def _when(assets, runs):
    for asset in assets:
        recording = asset.get("recording") if isinstance(asset.get("recording"), dict) else {}
        for value in (recording.get("startedAt"), _metadata(asset).get("recordedAt")):
            found = _iso(value)
            if found:
                return found
    modified = [stamp(asset.get("lastModified") or asset.get("createdAt")) for asset in assets]
    modified = [value for value in modified if value]
    if modified:
        return datetime.fromtimestamp(min(modified), timezone.utc).isoformat()
    started = [run["startedAt"] for run in runs if run.get("startedAt")]
    if started:
        return datetime.fromtimestamp(min(started), timezone.utc).isoformat()
    return None


def _thumbnail(game, assets):
    for asset in assets:
        view = _asset_view(game, asset)
        if view["role"] == "final" and view["preview"] == "image" and view["kind"] in {"video-thumbnail", "thumbnail", "poster", "cover"}:
            return view["key"]
        if view["role"] == "final" and view["preview"] == "image" and view["kind"] in {"tv-episode", "session-video", "video", "silly-video"}:
            return view["key"]
    for asset in assets:
        view = _asset_view(game, asset)
        if view["thumbnailKey"]:
            return view["thumbnailKey"]
        if view["role"] == "final" and view["preview"] == "image":
            return view["key"]
    return None


def _recording_key(assets):
    playbacks = [asset for asset in assets if asset.get("kind") == "recording-playback" and _preview(asset) == "audio"]
    playbacks.sort(key=lambda asset: str(asset.get("lastModified") or ""), reverse=True)
    if playbacks:
        return playbacks[0].get("key")
    for asset in assets:
        playback = asset.get("playback") if isinstance(asset.get("playback"), dict) else {}
        key = playback.get("audioKey")
        if isinstance(key, str):
            return key
    return None


def _summary_source(assets):
    transcripts = [asset for asset in assets if asset.get("kind") in TRANSCRIPT_KINDS and str(asset.get("key") or "").endswith(".json")]
    transcripts.sort(key=lambda asset: (0 if asset.get("kind") == "raw-transcript" else 1, str(asset.get("lastModified") or "")))
    if not transcripts:
        return None
    raw = [asset for asset in transcripts if asset.get("kind") in {"raw-transcript", "transcript"}]
    chosen = raw[-1] if raw else transcripts[-1]
    return chosen.get("key")


def _summary_text(summary):
    if not isinstance(summary, dict):
        return None
    text = summary.get("text") or summary.get("summary")
    if isinstance(text, dict):
        text = text.get("summary")
    return _clip(text, 600)


def shape_run(item, game):
    if not isinstance(item, dict):
        return None
    identity = item.get("id") if isinstance(item.get("id"), str) and item.get("id").strip() else item.get("runId")
    if not isinstance(identity, str) or not identity.strip() or "/" in identity or len(identity) > 200:
        return None
    kind = item.get("kind") if isinstance(item.get("kind"), str) and item["kind"].strip() else "unknown"
    status = normalize(item.get("status"))
    started = stamp(item.get("createdAt")) or stamp(item.get("startedAt")) or None
    ended = None
    if status in TERMINAL:
        for field in ("completedAt", "endedAt", "reportedAt", "observedAt", "updatedAt"):
            ended = stamp(item.get(field)) or None
            if ended:
                break
        if ended and started and ended < started:
            ended = None
    duration = int(ended - started) if ended and started else None
    message = _clip(item.get("note") or item.get("message"))
    outputs = []
    for stage in item.get("stages") or []:
        if isinstance(stage, dict) and isinstance(stage.get("outputKey"), str):
            outputs.append(stage["outputKey"])
    for field in ("outputKey", "assetKey"):
        if isinstance(item.get(field), str):
            outputs.append(item[field])
    if kind in DETAIL_KINDS and slug(kind):
        detail = f"/games/{game}/workflows/{kind}/{identity}"
    else:
        detail = None
    return {
        "id": identity,
        "kind": kind,
        "type": pipeline_label(kind),
        "title": _clip(item.get("title") or item.get("label"), 240) or pipeline_label(kind),
        "status": status,
        "statusLabel": STATUS_LABELS.get(status, "Unknown"),
        "startedAt": started,
        "endedAt": ended,
        "durationSeconds": duration,
        "message": message,
        "detailPath": detail,
        "outputKeys": list(dict.fromkeys(outputs)),
        "anchor": anchor_for(identity),
    }


def _run_for(view, runs, by_output):
    pinned = by_output.get(view.get("key"))
    if pinned:
        return pinned
    job = view.get("jobId")
    if not job:
        return None
    for run in runs:
        if job == run["id"] or job == run["id"].split("~", 1)[-1]:
            return run
    return None


def _featured_transcript(views):
    transcripts = [view for view in views if view.get("typeId") == "transcripts" and view.get("role") != "final"]
    preferred = [view for view in transcripts if view.get("kind") in {"corrected-transcript", "edited-transcript"}]
    pool = preferred or transcripts
    if not pool:
        return None
    return sorted(pool, key=lambda view: (str(view.get("createdAt") or ""), view.get("key") or ""))[-1]


def organize_library(views, runs):
    """Final cards, then intermediary files by pipeline stage, run, and type."""
    by_output = {}
    for run in runs:
        for key in run.get("outputKeys") or []:
            by_output.setdefault(key, run)
    featured = _featured_transcript(views)
    finals = [view for view in views if view.get("role") == "final"]
    if featured and featured not in finals:
        finals.append(featured)
    finals.sort(key=lambda view: (str(view.get("createdAt") or ""), view.get("key") or ""), reverse=True)
    buckets = {}
    for view in views:
        if view.get("role") == "final" or view is featured:
            continue
        run = _run_for(view, runs, by_output)
        stage = run["kind"] if run else stage_for_kind(view.get("kind") or "")
        run_id = run["id"] if run else ""
        buckets.setdefault((stage, run_id), {}).setdefault(view["typeId"], []).append(view)
    type_meta = {type_id: (label, layout) for type_id, label, layout in TYPE_SPECS}
    present = []
    stages = []
    seen_stages = []
    for stage, _run_id in buckets:
        if stage not in seen_stages:
            seen_stages.append(stage)
    ordered = [stage for stage in STAGE_ORDER if stage in seen_stages]
    ordered.extend(sorted(stage for stage in seen_stages if stage not in STAGE_ORDER))
    run_by_id = {run["id"]: run for run in runs}
    for stage in ordered:
        run_ids = []
        for key_stage, run_id in buckets:
            if key_stage == stage and run_id not in run_ids:
                run_ids.append(run_id)
        run_ids.sort(key=lambda run_id: (-(run_by_id.get(run_id, {}).get("startedAt") or 0), run_id))
        run_groups = []
        stage_assets = []
        for run_id in run_ids:
            types = buckets[(stage, run_id)]
            type_groups = []
            run_assets = []
            for type_id, label, layout in TYPE_SPECS:
                members = types.get(type_id) or []
                if not members:
                    continue
                members = sorted(members, key=lambda view: (str(view.get("createdAt") or ""), view.get("key") or ""), reverse=True)
                run_assets.extend(members)
                if type_id not in present:
                    present.append(type_id)
                type_groups.append({
                    "id": type_id,
                    "title": label,
                    "layout": layout,
                    **size_summary(members),
                    "assets": members,
                })
            for type_id, members in types.items():
                if type_id in type_meta:
                    continue
                label = type_id.replace("-", " ").capitalize()
                members = sorted(members, key=lambda view: (str(view.get("createdAt") or ""), view.get("key") or ""), reverse=True)
                run_assets.extend(members)
                type_groups.append({"id": type_id, "title": label, "layout": "rows", **size_summary(members), "assets": members})
            run = run_by_id.get(run_id)
            stage_assets.extend(run_assets)
            run_groups.append({
                "id": run_id or None,
                "title": run["title"] if run else "Not tied to a run",
                "anchor": run["anchor"] if run else None,
                **size_summary(run_assets),
                "types": type_groups,
            })
        stages.append({
            "id": stage,
            "title": pipeline_label(stage) if stage != "other" else "Other work",
            **size_summary(stage_assets),
            "runs": run_groups,
        })
    return {
        "finals": finals,
        "stages": stages,
        "types": [{"id": type_id, "label": type_meta[type_id][0]} for type_id in present if type_id in type_meta],
    }


def _status(runs, assets):
    states = {run["status"] for run in runs}
    for state in ("failed", "running", "queued", "paused"):
        if state in states:
            return state
    if states and states <= {"done"}:
        return "done"
    if "done" in states:
        return "started"
    if "unknown" in states:
        return "unknown"
    if any(asset.get("kind") in {"recording", "recording-manifest", "recording-playback"} or asset.get("recording") for asset in assets):
        return "recorded"
    return "pending"


def _sort_stamp(value):
    return stamp(value) or 0


def assemble(game, assets, runs, session_id=None, summaries=None, assets_complete=True):
    """Build the list, and one detail when ``session_id`` is set. Inputs are not modified."""
    if not slug(game):
        raise ValueError("Invalid game")
    if session_id is not None and not slug(session_id):
        raise ValueError("Invalid session")
    summaries = summaries or {}
    assets = [asset for asset in assets if isinstance(asset, dict)]
    membership = session_index(assets)
    grouped = {}
    for asset in assets:
        sid = membership.get(asset.get("key"))
        if sid:
            grouped.setdefault(sid, {"assets": [], "runs": []})["assets"].append(asset)
    shaped = []
    for item in runs:
        if not isinstance(item, dict):
            continue
        sid = tied_session(item)
        run = shape_run(item, game) if sid else None
        if not sid or not run:
            continue
        grouped.setdefault(sid, {"assets": [], "runs": []})
        shaped.append((sid, run))
    for sid, run in shaped:
        grouped[sid]["runs"].append(run)
    if session_id and session_id not in grouped:
        grouped[session_id] = {"assets": [], "runs": []}

    def card(sid, bucket):
        bucket_assets = bucket["assets"]
        bucket_runs = sorted(bucket["runs"], key=lambda run: (-(run["startedAt"] or 0), run["id"]))
        when = _when(bucket_assets, bucket_runs)
        status = _status(bucket_runs, bucket_assets)
        summary = _summary_text(summaries.get(sid))
        players, characters = _people(bucket_assets)
        return {
            "id": sid,
            "title": _title(bucket_assets, sid, when),
            "occurredAt": when,
            "thumbnailKey": _thumbnail(game, bucket_assets),
            "summaryText": summary,
            "summarySourceKey": _summary_source(bucket_assets),
            "status": status,
            "statusLabel": STATUS_LABELS.get(status, "Unknown"),
            "players": players,
            "characters": characters,
            "href": f"/games/{game}/sessions/{sid}",
            "runs": bucket_runs,
            "recordingKey": _recording_key(bucket_assets),
            "assets": bucket_assets,
        }

    cards = [card(sid, bucket) for sid, bucket in grouped.items()]
    cards.sort(key=lambda item: (-_sort_stamp(item["occurredAt"]), item["id"]))
    selected = None
    if session_id:
        match = next(item for item in cards if item["id"] == session_id)
        views = [_asset_view(game, asset) for asset in match["assets"] if isinstance(asset.get("key"), str)]
        views.sort(key=lambda asset: (str(asset.get("createdAt") or ""), asset["key"]), reverse=True)
        pipeline = []
        for run in match["runs"]:
            public_run = {key: value for key, value in run.items() if key != "outputKeys"}
            public_run["pipelinePath"] = f"/games/{game}/pipeline/{session_id}"
            pipeline.append(public_run)
        library = organize_library(views, match["runs"])
        selected = {
            "id": session_id,
            "title": match["title"],
            "occurredAt": match["occurredAt"],
            "thumbnailKey": match["thumbnailKey"],
            "summaryText": match["summaryText"],
            "summarySourceKey": match["summarySourceKey"],
            "status": match["status"],
            "statusLabel": match["statusLabel"],
            "players": match["players"],
            "characters": match["characters"],
            "recordingKey": match["recordingKey"],
            "href": match["href"],
            "finalAssets": [asset for asset in views if asset["role"] == "final"],
            "intermediaryAssets": [asset for asset in views if asset["role"] != "final"],
            "library": library,
            "pipelines": pipeline,
        }
    hidden = {"assets", "runs", "recordingKey"}
    return {
        "schemaVersion": 1,
        "gameId": game,
        "complete": bool(assets_complete),
        "sessionId": session_id,
        "sessions": [
            {**{key: value for key, value in item.items() if key not in hidden}, "runCount": len(item["runs"])}
            for item in cards
        ],
        "session": selected,
    }


def catalog_page_limit():
    return ASSET_PAGES
