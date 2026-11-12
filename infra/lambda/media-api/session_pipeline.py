"""One branching session pipeline. A run is one execution of that pipeline for a session.

The graph starts at the session recording. Shared stages lead into one lane per final artifact.
Append a lane in graph() and a title in LANE_TITLES to add the next artifact. Status comes from
job records. A later run keeps reused stages done instead of painting them as not started.
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
    "storyboard-approval": ("Gate", "Storyboard approval", "shield"),
    "video-generation": ("Render", "Video generation", "film"),
    "sound-delivery": ("Delivery", "Sound and delivery", "audio"),
    "session-video": ("Final", "Session video", "film"),
    "listening-copy": ("Audio", "Listening copy", "audio"),
    "still-images": ("Image", "Still images", "image"),
    "narration": ("Narration", "Narration", "mic"),
}
# Lane order inside the one graph. Append the next artifact's title here.
LANE_TITLES = (
    ("shared", "Shared"),
    ("novel", "Novel"),
    ("video", "Video"),
)
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


def _node(identity, column, row, lane, final=False):
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
        "lane": lane,
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
                "lane": "shared",
                "final": False,
            }
        )
    transcription = next(node for node in nodes if node["id"] == "transcription")
    nodes.append(_node("listening-copy", transcription["column"], 1, "shared"))
    # Each artifact lane branches from the corrected transcript at this column.
    # Append (lane id, stage ids, final id) for the next artifact, and its title in LANE_TITLES.
    branch = len(PREFIX)
    artifact_lanes = (
        ("novel", list(plan["novel"]), "novel-chapter"),
        (
            "video",
            [
                *plan["video"],
                "storyboard-approval",
                "video-generation",
                "sound-delivery",
                "session-video",
            ],
            "session-video",
        ),
    )
    for lane, stages, final_id in artifact_lanes:
        for index, identity in enumerate(stages):
            nodes.append(_node(identity, branch + index, 0, lane, final=identity == final_id))
    by_id = {node["id"]: node for node in nodes}
    story = by_id.get("video-storyboards")
    if story:
        nodes.append(_node("still-images", story["column"], 1, story["lane"]))
    generation = by_id["video-generation"]
    nodes.append(_node("narration", generation["column"], 1, generation["lane"]))
    edges = []

    def link(source, dest):
        if any(node["id"] == source for node in nodes) and any(node["id"] == dest for node in nodes):
            edges.append({"from": source, "to": dest})

    shared = [node["id"] for node in nodes if node["lane"] == "shared" and node["row"] == 0]
    for source, dest in zip(shared, shared[1:]):
        link(source, dest)
    link("session-audio", "listening-copy")
    for _lane, stages, _final in artifact_lanes:
        if not stages:
            continue
        link("corrected-transcript", stages[0])
        for source, dest in zip(stages, stages[1:]):
            link(source, dest)
    link("narration", "sound-delivery")
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
                    "lane",
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
    finals = [node for node in nodes if node["final"]]
    if finals and all(node["status"] == "done" for node in finals):
        return "done"
    if any(node["status"] not in {"pending", "unknown"} for node in nodes):
        return "started"
    return "pending"


def _run_id(row):
    if row.get("kind") != "editorial":
        return None
    identity = row.get("runId")
    if not isinstance(identity, str):
        return None
    identity = identity.strip()
    if not identity or len(identity) > 160:
        return None
    return identity


def _reused(row):
    values = row.get("reusedStages")
    if not isinstance(values, list):
        return []
    return [name for name in values if isinstance(name, str) and name in NODE_IDS][:80]


def _paint(rows, reused):
    nodes, edges, _, _ = project(rows)
    if not reused:
        return nodes, edges
    wanted = set(reused)
    painted = []
    for node in nodes:
        if node["id"] in wanted and node["status"] in {"pending", "queued", "unknown"}:
            painted.append(
                {**node, "status": "done", "message": node["message"] or "Reused from the previous run."}
            )
        else:
            painted.append(node)
    by_id = {node["id"]: node for node in painted}
    return painted, [{**edge, "status": by_id[edge["from"]]["status"]} for edge in edges]


def _rows_for(rows, run_id):
    if run_id is None:
        return rows
    return [row for row in rows if _run_id(row) in {None, run_id}]


def _worker_for(stage_id):
    if stage_id == "listening-copy":
        return "playback"
    if stage_id in EDITORIAL_IDS:
        return "editorial"
    return None


def _needed_workers(nodes, edges):
    """Workers for stages that are ready to run. Later gray stages do not count."""
    by_id = {node["id"]: node for node in nodes}
    incoming = {}
    for edge in edges:
        incoming.setdefault(edge["to"], []).append(edge["from"])
    needed = []
    for node in nodes:
        worker = _worker_for(node["id"])
        if not worker or node["status"] in {"done", "failed"}:
            continue
        predecessors = incoming.get(node["id"], [])
        ready = node["status"] in {"queued", "running"} or not predecessors or any(
            by_id[name]["status"] in {"done", "running", "queued"} for name in predecessors
        )
        if node["status"] == "pending" and not ready:
            continue
        if worker not in needed:
            needed.append(worker)
    return needed


def _lane_status(nodes):
    states = {node.get("status") or "pending" for node in nodes}
    if "failed" in states:
        return "failed"
    if "running" in states:
        return "running"
    if "queued" in states:
        return "queued"
    if "paused" in states:
        return "paused"
    if nodes and all(node.get("status") == "done" for node in nodes):
        return "done"
    if any(node.get("status") not in {None, "pending", "unknown"} for node in nodes):
        return "started"
    return "pending"


def _lanes(nodes):
    """Lane headers in graph order. A lane id that is not listed yet is appended."""
    grouped = {}
    for node in nodes:
        grouped.setdefault(node.get("lane") or "shared", []).append(node)
    titles = dict(LANE_TITLES)
    order = [lane for lane, _title in LANE_TITLES]
    for node in nodes:
        lane = node.get("lane") or "shared"
        if lane not in titles:
            titles[lane] = lane.replace("-", " ").capitalize()
            order.append(lane)
    headers = []
    for lane in order:
        members = grouped.get(lane)
        if not members:
            continue
        stage, _finals = _progress(members)
        headers.append(
            {
                "id": lane,
                "title": titles[lane],
                "status": _lane_status(members),
                "stage": stage,
            }
        )
    return headers


def _progress(nodes):
    ordered = sorted(nodes, key=lambda node: (node["column"], node["row"], node["id"]))
    failed = [node for node in ordered if node["status"] == "failed"]
    reached = [node for node in ordered if node["status"] not in {"pending", "unknown"}]
    chosen = failed[-1] if failed else (reached[-1] if reached else None)
    stage = (
        {"id": chosen["id"], "title": chosen["title"], "status": chosen["status"]} if chosen else None
    )
    finals = [
        {"id": node["id"], "title": node["title"], "status": node["status"]}
        for node in sorted((node for node in nodes if node["final"]), key=lambda node: node["row"])
    ]
    return stage, finals


def _run_graph(rows, row):
    identity = _run_id(row)
    nodes, edges = _paint(_rows_for(rows, identity), _reused(row))
    started = stamp(row.get("startedAt"))
    return {
        "id": identity,
        "startedAt": started or None,
        "updatedAt": stamp(row.get("updatedAt")),
        "status": rollup(nodes),
        "workers": _needed_workers(nodes, edges),
        "nodes": nodes,
        "edges": edges,
        "lanes": _lanes(nodes),
    }


def view(session_id, observations):
    if session_id is not None and not slug(session_id):
        raise ValueError("Invalid session")
    grouped = {}
    for observation in observations:
        session = observation.get("sessionId")
        if slug(session):
            grouped.setdefault(session, []).append(observation)
    sessions = []
    graphs = {}
    for session, rows in grouped.items():
        _, _, titles, latest = project(rows)
        title = titles.get(session) or session
        updated = latest.get(session, 0)
        run_rows = sorted(
            (row for row in rows if _run_id(row)),
            key=lambda row: (
                stamp(row.get("startedAt")) or stamp(row.get("updatedAt")),
                stamp(row.get("updatedAt")),
                _run_id(row),
            ),
        )
        runs = [_run_graph(rows, row) for row in run_rows]
        runs.reverse()
        if runs:
            nodes, edges = runs[0]["nodes"], runs[0]["edges"]
        else:
            nodes, edges = _paint(rows, [])
        stage, finals = _progress(nodes)
        sessions.append(
            {
                "id": session,
                "title": title,
                "updatedAt": updated,
                "status": rollup(nodes),
                "stage": stage,
                "finals": finals,
            }
        )
        graphs[session] = {
            "title": title,
            "updatedAt": updated,
            "nodes": nodes,
            "edges": edges,
            "runs": runs,
        }
    if session_id and session_id not in graphs:
        nodes, edges = _paint([], [])
        stage, finals = _progress(nodes)
        sessions.append(
            {
                "id": session_id,
                "title": session_id,
                "updatedAt": 0,
                "status": "pending",
                "stage": stage,
                "finals": finals,
            }
        )
        graphs[session_id] = {
            "title": session_id,
            "updatedAt": 0,
            "nodes": nodes,
            "edges": edges,
            "runs": [],
        }
    sessions.sort(key=lambda item: (-item["updatedAt"], item["id"]))
    selected = session_id or (sessions[0]["id"] if sessions else None)
    if selected:
        chosen = graphs[selected]
        manifest = {
            "schemaVersion": 1,
            "sessionId": selected,
            "title": chosen["title"],
            "updatedAt": chosen["updatedAt"],
            "nodes": chosen["nodes"],
            "edges": chosen["edges"],
            "lanes": _lanes(chosen["nodes"]),
        }
        runs = chosen["runs"]
        workers_needed = runs[0]["workers"] if runs else _needed_workers(chosen["nodes"], chosen["edges"])
    else:
        nodes, edges = _paint([], [])
        manifest = {
            "schemaVersion": 1,
            "sessionId": None,
            "title": None,
            "updatedAt": 0,
            "nodes": nodes,
            "edges": edges,
            "lanes": _lanes(nodes),
        }
        runs = []
        workers_needed = []
    return {
        "schemaVersion": 1,
        "source": "job-records",
        "sessions": sessions,
        "manifest": manifest,
        "runs": runs,
        "workersNeeded": workers_needed,
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
