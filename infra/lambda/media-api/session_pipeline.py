"""Per-session pipelines. A pipeline is a named definition; a run is one execution for a session.

Topology matches the deployed stages. Status, stage, and run identity come from job records.
"""

import json
import os
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
STATUSES = {"pending", "queued", "running", "done", "failed", "paused", "unknown"}
RANK = {"failed": 6, "running": 5, "queued": 4, "paused": 3, "done": 2, "unknown": 1, "pending": 0}
RAW_STATUS = {
    "SUBMITTED": "queued",
    "QUEUED": "queued",
    "RUNNING": "running",
    "PROCESSING": "running",
    "DONE": "done",
    "NOVEL_READY": "done",
    "READY_FOR_VIDEO_DISCUSSION": "done",
    "FAILED": "failed",
    "BLOCKED": "paused",
    "DEFERRED": "paused",
    "IN_QUEUE": "queued",
    "IN_PROGRESS": "running",
    "PUBLISHED": "done",
    "ATTENTION": "failed",
    "UNKNOWN": "unknown",
    "GENERATING": "running",
    "COMPOSING": "running",
    "SUPERSEDED": "paused",
    "CONFLICT": "paused",
    "complete": "done",
    "interrupted": "done",
    "recording": "running",
}
PREFIX = [
    ("session-audio", "Capture", "Session audio", "mic", 0),
    ("transcription", "Speech", "Transcription", "captions", 0),
    ("speaker-match", "Identity", "Speaker matching", "users", 0),
    ("raw-transcript", "Transcript", "Raw transcript", "file", 0),
    ("context", "Evidence", "Context selection", "library", 0),
    ("correction", "Edit", "Transcript cleanup", "pencil", 0),
    ("corrected-transcript", "Transcript", "Corrected transcript", "file-check", 0),
]
LABELS = {
    "novel-brief": ("Chapter", "Editorial brief", "book"),
    "novel-options": ("Chapter", "Voice and approaches", "book"),
    "novel-outline": ("Chapter", "Scene beats", "list"),
    "novel-draft": ("Chapter", "Full draft", "book"),
    "novel-developmental-edit": ("Review", "Developmental edit", "search"),
    "novel-revision": ("Chapter", "Revision", "pencil"),
    "novel-continuity": ("Review", "Continuity audit", "search"),
    "novel-line-copyedit": ("Edit", "Line copyedit", "pencil"),
    "novel-proof": ("Review", "Reading proof", "search"),
    "novel-chapter": ("Final", "Novel chapter", "book"),
    "video-source-brief": ("Screen", "Source brief", "clapper"),
    "video-treatment": ("Screen", "Treatment", "clapper"),
    "video-screenplay": ("Screen", "Screenplay", "scroll"),
    "video-script-edit": ("Review", "Script critique", "search"),
    "video-shooting-script": ("Screen", "Shooting script", "scroll"),
    "video-breakdown": ("Planning", "Breakdown", "list"),
    "video-design": ("Planning", "Design bible", "palette"),
    "video-reference-plan": ("Planning", "Reference plan", "image"),
    "video-voice-casting": ("Narration", "Voice casting", "mic"),
    "video-blocking": ("Planning", "Blocking", "camera"),
    "video-shot-list": ("Planning", "Shot list", "list"),
    "video-storyboards": ("Image", "Storyboards", "image"),
    "video-generation-packets": ("Planning", "Generation packets", "package"),
    "video-edit-sound-vfx": ("Planning", "Edit, sound and VFX", "audio"),
    "video-production-plan": ("Planning", "Production plan", "list"),
    "video-preflight": ("Review", "Preflight", "shield"),
}
KIND_NODE = {
    "recording": "session-audio",
    "playback": "listening-copy",
    "transcription": "transcription",
    "narration": "narration",
    "chapter": "novel-chapter",
    "episode-render": "session-video",
    "scene-render": "video-generation",
    "asset-generation": "still-images",
}


def plan_document():
    """Prefer the repository plan. Deployed Lambdas receive the same document in WORKSHOP_PLAN."""
    file = Path(__file__).resolve()
    candidate = (
        file.parents[3] / "src/panther_journal/editorial-plan.json"
        if len(file.parents) > 3
        else None
    )
    if candidate and candidate.is_file():
        return json.loads(candidate.read_text())
    return json.loads(os.environ["WORKSHOP_PLAN"])


def _node(identity, column, row, final=False):
    kind, title, icon = LABELS.get(
        identity, ("Stage", identity.replace("-", " ").capitalize(), "circle")
    )
    return {
        "id": identity,
        "type": kind,
        "title": title,
        "icon": icon,
        "column": column,
        "row": row,
        "final": final,
    }


def graph():
    plan = plan_document()
    nodes = []
    for column, (identity, kind, title, icon, row) in enumerate(PREFIX):
        nodes.append(
            {
                "id": identity,
                "type": kind,
                "title": title,
                "icon": icon,
                "column": column,
                "row": row,
                "final": False,
            }
        )
    transcription = next(node for node in nodes if node["id"] == "transcription")
    nodes.append(
        {
            "id": "listening-copy",
            "type": "Audio",
            "title": "Listening copy",
            "icon": "audio",
            "column": transcription["column"],
            "row": 1,
            "final": False,
        }
    )
    novel = [name for name in plan["novel"] if name != "novel-chapter"]
    video = list(plan["video"])
    start = len(PREFIX)
    for offset in range(max(len(novel), len(video), 1)):
        if offset < len(novel):
            nodes.append(_node(novel[offset], start + offset, 0))
        if offset < len(video):
            nodes.append(_node(video[offset], start + offset, 1))
    column = start + max(len(novel), len(video), 1)
    for identity, kind, title, icon in (
        ("storyboard-approval", "Gate", "Storyboard approval", "shield"),
        ("video-generation", "Render", "Video generation", "film"),
        ("sound-delivery", "Delivery", "Sound and delivery", "audio"),
    ):
        nodes.append(
            {
                "id": identity,
                "type": kind,
                "title": title,
                "icon": icon,
                "column": column,
                "row": 1,
                "final": False,
            }
        )
        column += 1
    nodes.append(
        {
            "id": "novel-chapter",
            "type": "Final",
            "title": "Novel chapter",
            "icon": "book",
            "column": column,
            "row": 0,
            "final": True,
        }
    )
    nodes.append(
        {
            "id": "session-video",
            "type": "Final",
            "title": "Session video",
            "icon": "film",
            "column": column,
            "row": 1,
            "final": True,
        }
    )
    story = next((node for node in nodes if node["id"] == "video-storyboards"), None)
    if story:
        nodes.append(
            {
                "id": "still-images",
                "type": "Image",
                "title": "Still images",
                "icon": "image",
                "column": story["column"],
                "row": 2,
                "final": False,
            }
        )
    generation = next(node for node in nodes if node["id"] == "video-generation")
    nodes.append(
        {
            "id": "narration",
            "type": "Narration",
            "title": "Narration",
            "icon": "mic",
            "column": generation["column"],
            "row": 2,
            "final": False,
        }
    )
    edges = []

    def link(source, dest):
        if any(node["id"] == source for node in nodes) and any(
            node["id"] == dest for node in nodes
        ):
            edges.append({"from": source, "to": dest})

    ids = [node["id"] for node in nodes if node["row"] == 0 and node["column"] < len(PREFIX)]
    for source, dest in zip(ids, ids[1:]):
        link(source, dest)
    link("session-audio", "listening-copy")
    if novel:
        link("corrected-transcript", novel[0])
        for source, dest in zip(novel, novel[1:]):
            link(source, dest)
        link(novel[-1], "novel-chapter")
    if video:
        link("corrected-transcript", video[0])
        for source, dest in zip(video, video[1:]):
            link(source, dest)
        link(video[-1], "storyboard-approval")
    link("storyboard-approval", "video-generation")
    link("video-generation", "sound-delivery")
    link("narration", "sound-delivery")
    link("sound-delivery", "session-video")
    if story:
        link("video-storyboards", "still-images")
        link("still-images", "video-generation")
    if any(node["id"] == "video-voice-casting" for node in nodes):
        link("video-voice-casting", "narration")
    return nodes, edges, set(plan["correction"] + plan["novel"] + plan["video"])


NODES, EDGES, EDITORIAL_IDS = graph()
NODE_IDS = {node["id"] for node in NODES}


def slug(value):
    return isinstance(value, str) and len(value) <= 96 and bool(SLUG.fullmatch(value))


def normalize(value):
    if value in STATUSES:
        return value
    return RAW_STATUS.get(value, "unknown" if value else "pending")


def stamp(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)) and value == value:
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0
    return 0


def aggregate(values):
    states = [normalize(value) for value in values]
    if not states:
        return "pending"
    if "failed" in states:
        return "failed"
    if "running" in states or ("done" in states and ("queued" in states or "pending" in states)):
        return "running"
    if "queued" in states:
        return "queued"
    if states.count("done") == len(states):
        return "done"
    if "paused" in states:
        return "paused"
    if "unknown" in states:
        return "unknown"
    return "pending"


def target(kind, stage_id):
    if stage_id in EDITORIAL_IDS or stage_id == "storyboard-approval":
        return stage_id
    if stage_id == "verify-inputs":
        return "session-audio"
    if stage_id == "preserve-raw-transcript" or stage_id.startswith("transcription-window-"):
        return "transcription"
    if stage_id == "match-players":
        return "speaker-match"
    if stage_id in {"publish-transcripts", "preserve-final-transcript"}:
        return "raw-transcript"
    if stage_id == "assemble-verify-publish" or (stage_id == "processing" and kind == "playback"):
        return "listening-copy"
    if stage_id == "sound":
        return "sound-delivery"
    if stage_id in {"delivery", "final-review"} or (
        stage_id == "processing" and kind == "episode-render"
    ):
        return "session-video"
    if stage_id == "processing" and kind == "transcription":
        return "transcription"
    if (
        stage_id.startswith("shot-")
        or (kind == "video-generation" and stage_id != "storyboard-approval")
        or (stage_id == "processing" and kind == "scene-render")
    ):
        return "video-generation"
    if stage_id == "processing" and kind == "narration":
        return "narration"
    if stage_id == "processing" and kind == "asset-generation":
        return "still-images"
    return None


def _clip(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:500] if text else None


def _apply(nodes, identity, status, updated, message=None, artifacts=()):
    node = nodes[identity]
    status = normalize(status)
    better = status != "pending" and (
        node["status"] == "pending"
        or updated > node["_updated"]
        or (updated == node["_updated"] and RANK[status] >= RANK[node["status"]])
    )
    if better:
        node["status"] = status
        node["_updated"] = updated
        if message:
            node["message"] = _clip(message)
    for artifact in artifacts:
        key = artifact.get("key") if isinstance(artifact, dict) else None
        label = artifact.get("label") if isinstance(artifact, dict) else None
        if (
            isinstance(key, str)
            and 0 < len(key) <= 1024
            and not any(item["key"] == key for item in node["artifacts"])
            and len(node["artifacts"]) < 12
        ):
            node["artifacts"].append({"key": key, "label": _clip(label) or node["title"]})


def _log(nodes, identity, text):
    text = _clip(text)
    node = nodes.get(identity)
    if text and node and text not in node["logs"] and len(node["logs"]) < 8:
        node["logs"].append(text)


def _blank():
    return {
        node["id"]: {
            **node,
            "status": "pending",
            "message": None,
            "logs": [],
            "artifacts": [],
            "_updated": -1,
        }
        for node in NODES
    }


def project(observations):
    nodes = _blank()
    titles = {}
    latest = {}
    for observation in observations:
        session = observation.get("sessionId")
        if not slug(session):
            continue
        updated = stamp(observation.get("updatedAt"))
        latest[session] = max(latest.get(session, 0), updated)
        if observation.get("sessionTitle"):
            titles[session] = _clip(observation["sessionTitle"]) or session
        elif session not in titles and observation.get("label"):
            titles[session] = _clip(observation["label"]) or session
        groups = {}
        for stage in observation.get("stages") or []:
            if not isinstance(stage, dict) or not isinstance(stage.get("id"), str):
                continue
            status = normalize(stage.get("status"))
            identity = stage["id"]
            if identity == "start-adaptations":
                _log(
                    nodes, "raw-transcript", stage.get("message") or "Adaptation handoff " + status
                )
                continue
            if identity in {"inputs", "preparation"} and status != "failed":
                _log(nodes, "video-generation", identity.replace("-", " ") + " " + status)
                continue
            dest = (
                "video-generation"
                if identity in {"inputs", "preparation"} and status == "failed"
                else target(observation.get("kind"), identity)
            )
            if dest in nodes:
                groups.setdefault(dest, []).append(stage)
        if not groups and observation.get("kind") in KIND_NODE:
            groups[KIND_NODE[observation["kind"]]] = [
                {
                    "id": observation["kind"],
                    "status": observation.get("status"),
                    "message": observation.get("message"),
                    "outputKey": observation.get("outputKey"),
                }
            ]
        for dest, items in groups.items():
            status = aggregate(item.get("status") for item in items)
            messages = [_clip(item.get("message")) for item in items if _clip(item.get("message"))]
            message = (
                messages[0]
                if messages
                else (_clip(observation.get("message")) if status == "failed" else None)
            )
            artifacts = [
                {"key": item.get("outputKey"), "label": nodes[dest]["title"]}
                for item in items
                if item.get("outputKey")
            ]
            _apply(nodes, dest, status, updated, message, artifacts)
        for artifact in observation.get("artifacts") or []:
            dest = KIND_NODE.get(observation.get("kind")) or next(iter(groups), None)
            if dest in nodes:
                _apply(
                    nodes,
                    dest,
                    observation.get("status") or "pending",
                    updated,
                    artifacts=[artifact],
                )
    if nodes["session-audio"]["status"] == "pending" and any(
        nodes[name]["status"] in {"done", "running", "queued"}
        for name in ("transcription", "listening-copy", "speaker-match", "raw-transcript")
    ):
        nodes["session-audio"]["status"] = "done"
        nodes["session-audio"]["message"] = (
            "A later recorded stage already has this session's audio."
        )
    public = []
    for node in NODES:
        item = nodes[node["id"]]
        public.append(
            {
                key: item[key]
                for key in (
                    "id",
                    "type",
                    "title",
                    "icon",
                    "column",
                    "row",
                    "final",
                    "status",
                    "message",
                    "logs",
                    "artifacts",
                )
            }
        )
    by_id = {node["id"]: node for node in public}
    edges = [{**edge, "status": by_id[edge["from"]]["status"]} for edge in EDGES]
    return public, edges, titles, latest


def rollup(nodes):
    states = {node["status"] for node in nodes}
    if "failed" in states:
        return "failed"
    if "running" in states:
        return "running"
    if "queued" in states:
        return "queued"
    finals = {node["id"]: node["status"] for node in nodes if node["final"]}
    if finals.get("novel-chapter") == "done" and finals.get("session-video") == "done":
        return "done"
    return "pending"


def definitions():
    """Named pipelines. Workers are the heartbeats that pipeline actually needs."""
    plan = plan_document()
    return (
        {
            "id": "listening",
            "name": "Listening copy",
            "workers": ("playback",),
            "runs": ("playback",),
            "stages": ("session-audio", "listening-copy"),
        },
        {
            "id": "transcript",
            "name": "Speech → transcript",
            "workers": (),
            "runs": ("transcription",),
            "stages": ("transcription", "speaker-match", "raw-transcript"),
        },
        {
            "id": "story",
            "name": "Transcript → story & screen planning",
            "workers": ("editorial",),
            "runs": ("editorial", "chapter"),
            "stages": (*plan["correction"], *plan["novel"], *plan["video"], "storyboard-approval"),
        },
        {
            "id": "video",
            "name": "Narration and session video",
            "workers": (),
            "runs": (
                "episode-render",
                "scene-render",
                "narration",
                "video-generation",
                "video-production",
                "asset-generation",
            ),
            "stages": (
                "still-images",
                "narration",
                "video-generation",
                "sound-delivery",
                "session-video",
            ),
        },
    )


def _targets(observation):
    kind = observation.get("kind")
    found = []
    for stage in observation.get("stages") or []:
        if not isinstance(stage, dict) or not isinstance(stage.get("id"), str):
            continue
        dest = target(kind, stage["id"])
        if dest and dest not in found:
            found.append(dest)
    if not found and kind in KIND_NODE:
        found.append(KIND_NODE[kind])
    return found


def _slice(nodes, edges, stage_ids):
    chosen = [node for node in nodes if node["id"] in stage_ids]
    columns = sorted({node["column"] for node in chosen})
    remap = {column: index for index, column in enumerate(columns)}
    sliced = [{**node, "column": remap[node["column"]]} for node in chosen]
    present = {node["id"] for node in sliced}
    return sliced, [dict(edge) for edge in edges if edge["from"] in present and edge["to"] in present]


def _pipeline_status(nodes):
    states = [node["status"] for node in nodes]
    if not states or set(states) <= {"pending", "unknown"}:
        return "pending"
    if "failed" in states:
        return "failed"
    if "running" in states or "queued" in states:
        return "running"
    if "paused" in states:
        return "paused"
    if states.count("done") == len(states):
        return "done"
    if "done" in states:
        return "started"
    return "pending"


def _focus(nodes):
    ordered = sorted(nodes, key=lambda node: (node["column"], node["row"], node["id"]))
    for status in ("failed", "running", "queued", "paused"):
        found = next((node for node in ordered if node["status"] == status), None)
        if found:
            return found
    if any(node["status"] == "done" for node in ordered):
        waiting = next((node for node in ordered if node["status"] != "done"), None)
        return waiting or next(node for node in reversed(ordered) if node["status"] == "done")
    return None


def _run(observations, kinds):
    ranked = [
        item
        for item in observations
        if item.get("kind") in kinds and isinstance(item.get("runId"), str) and item["runId"].strip()
    ]
    if not ranked:
        return None
    primary = [item for item in ranked if item.get("kind") == kinds[0]]
    chosen = max(primary or ranked, key=lambda item: (stamp(item.get("updatedAt")), item["runId"]))
    identity = chosen["runId"].strip()
    if len(identity) > 160:
        return None
    started = stamp(chosen.get("startedAt"))
    return {"id": identity, "startedAt": started or None, "status": normalize(chosen.get("status"))}


def _pipelines(nodes, edges, observations, updated):
    result = []
    for definition in definitions():
        stages = set(definition["stages"])
        sliced, sliced_edges = _slice(nodes, edges, stages)
        touched = [item for item in observations if stages.intersection(_targets(item))]
        latest = max((stamp(item.get("updatedAt")) for item in touched), default=0)
        if latest == 0 and any(node["status"] != "pending" for node in sliced):
            latest = updated or 0
        stage = _focus(sliced)
        result.append(
            {
                "id": definition["id"],
                "name": definition["name"],
                "workers": list(definition["workers"]),
                "status": _pipeline_status(sliced),
                "stage": (
                    {"id": stage["id"], "title": stage["title"], "status": stage["status"]}
                    if stage
                    else None
                ),
                "updatedAt": latest,
                "run": _run(observations, definition["runs"]),
                "nodes": sliced,
                "edges": sliced_edges,
            }
        )
    return result


def view(session_id, observations):
    if session_id is not None and not slug(session_id):
        raise ValueError("Invalid session")
    grouped = {}
    for observation in observations:
        session = observation.get("sessionId")
        if slug(session):
            grouped.setdefault(session, []).append(observation)
    sessions = []
    manifests = {}
    for session, rows in grouped.items():
        session_nodes, session_edges, session_titles, session_latest = project(rows)
        title = session_titles.get(session) or session
        updated = session_latest.get(session, 0)
        sessions.append(
            {"id": session, "title": title, "updatedAt": updated, "status": rollup(session_nodes)}
        )
        manifests[session] = {
            "schemaVersion": 1,
            "sessionId": session,
            "title": title,
            "updatedAt": updated,
            "nodes": session_nodes,
            "edges": session_edges,
        }
    if session_id and session_id not in manifests:
        empty_nodes, empty_edges, _, _ = project([])
        sessions.append(
            {"id": session_id, "title": session_id, "updatedAt": 0, "status": "pending"}
        )
        manifests[session_id] = {
            "schemaVersion": 1,
            "sessionId": session_id,
            "title": session_id,
            "updatedAt": 0,
            "nodes": empty_nodes,
            "edges": empty_edges,
        }
    sessions.sort(key=lambda item: (-item["updatedAt"], item["id"]))
    selected = session_id or (sessions[0]["id"] if sessions else None)
    if selected:
        manifest = manifests[selected]
    else:
        empty_nodes, empty_edges, _, _ = project([])
        manifest = {
            "schemaVersion": 1,
            "sessionId": None,
            "title": None,
            "updatedAt": 0,
            "nodes": empty_nodes,
            "edges": empty_edges,
        }
    selected_rows = grouped.get(selected, []) if selected else []
    pipelines = _pipelines(
        manifest["nodes"], manifest["edges"], selected_rows, manifest.get("updatedAt") or 0
    )
    return {
        "schemaVersion": 1,
        "source": "job-records",
        "sessions": sessions,
        "manifest": manifest,
        "pipelines": pipelines,
    }


def session_of(item):
    """Use an explicit session id. A title suffix counts only when it is a real slug with a hyphen."""
    sid = item.get("sessionId")
    if slug(sid):
        return sid
    title = item.get("title") or ""
    if " · " not in title:
        return None
    suffix = title.split(" · ", 1)[1].strip()
    if "-" in suffix and slug(suffix):
        return suffix
    return None
