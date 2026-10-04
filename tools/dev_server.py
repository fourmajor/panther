"""Loopback development backend with persistent SQLite data; never a production login."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import parse_qs, urlparse
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "infra/lambda/media-api"))
WEB = ROOT / "web/media-explorer"
STYLES = ["photorealistic", "anime", "illustrated-fantasy", "comic-book", "watercolor", "oil-painting", "stylized-3d", "pixel-art"]


def details():
    return {"schemaVersion": 1, "aliases": [], "pronouns": None, "role": None, "status": None, "overview": None, "subtitle": None, "backstory": None, "notes": None, "statistics": [], "relationships": [], "thumbnailAssetKey": None}



def production_asset_views():
    """Load pure catalog predicates without importing cloud clients."""
    import sys
    module_path = str(ROOT / "infra/lambda/media-api")
    if module_path not in sys.path:
        sys.path.insert(0, module_path)
    import asset_views
    return asset_views



def session_asset(asset):
    """Use the production logical Sessions contract for persistent local data."""
    return production_asset_views().session_asset(asset)


def local_assets(assets, section):
    selected = [a for a in assets if section == "all"
        or section == "sessions" and session_asset(a)
        or section == "audio" and a["contentType"].startswith("audio/")
        or section == "transcripts" and "transcript" in a["kind"]
        or section == "videos" and a["contentType"].startswith("video/")
        or section == "images" and a["contentType"].startswith("image/")]
    if section in {"sessions", "transcripts"}:
        by_key = {a["key"]: a for a in assets}
        selected = [a for a in selected if not (a["key"].endswith(".md")
            and a["kind"] in {"transcript", "raw-transcript", "corrected-transcript", "edited-transcript"}
            and by_key.get(a["key"][:-3] + ".json", {}).get("kind") == a["kind"])]
    return selected

class Store:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        if self.path.is_relative_to(ROOT):
            raise ValueError("Keep the development database outside the repository")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, game TEXT, payload TEXT, PRIMARY KEY(kind,id)); CREATE TABLE IF NOT EXISTS objects (key TEXT PRIMARY KEY, game TEXT, metadata TEXT, data BLOB, created TEXT); CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, payload TEXT, response TEXT);")
        self.migrate_episode_composition()
        self.migrate_browser_playback()
        self.migrate_authored_chapter_series()
        self.migrate_notifications()
        self.path.chmod(0o600)

    def notification_for_job(self, kind, payload, game):
        if kind not in {"editorial", "playback", "transcription", "scene-render", "episode-render", "narration", "asset-generation", "transcript-summary"} or not payload.get("jobId"):
            return None
        from notifications import event_for
        return event_for({"gameId": game or payload.get("gameId", ""), "kind": kind,
                          "id": kind + "~" + payload["jobId"], "status": "failed" if payload.get("status") in {"FAILED", "ATTENTION"} else "unknown",
                          "sourceStatus": payload.get("status"), "title": payload.get("title") or payload.get("creation", {}).get("title") or kind.replace("-", " ").capitalize()})

    def migrate_notifications(self):
        """Repeatable local backfill; reads never scan jobs to manufacture a feed."""
        with self.connect() as db:
            for kind, game, raw in db.execute("SELECT kind,game,payload FROM records").fetchall():
                notice = self.notification_for_job(kind, json.loads(raw), game)
                if notice:
                    db.execute("INSERT OR IGNORE INTO records VALUES ('notification',?,?,?)", (notice["id"], notice["gameId"], json.dumps({**notice, "readAt": None})))

    def notifications(self, view="all", cursor=None):
        if view not in {"all", "unread"}:
            raise ValueError("Unknown notification view")
        rows = sorted(self.list("notification"), key=lambda item: (item["createdAt"], item["id"]), reverse=True)
        if view == "unread":
            rows = [row for row in rows if not row.get("readAt")]
        offset, limit = int(cursor or "0"), 10 if view == "unread" else 30
        if offset < 0 or offset > len(rows):
            raise ValueError("Invalid notification cursor")
        return {"notifications": rows[offset:offset + limit], "cursor": str(offset + limit) if len(rows) > offset + limit else None, "schemaVersion": 1}

    def read_notification(self, identity):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM records WHERE kind='notification' AND id=?", (identity,)).fetchone()
            if not row:
                raise LookupError("Notification not found")
            notice = json.loads(row[0])
            notice["readAt"] = notice.get("readAt") or int(time.time())
            db.execute("UPDATE records SET payload=? WHERE kind='notification' AND id=?", (json.dumps(notice), identity))
        return {"read": True, "id": identity}

    def migrate_authored_chapter_series(self):
        """Project exact authored series/version facts; retain records and original bytes."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for identity, game, payload in db.execute("SELECT id,game,payload FROM records WHERE kind='chapter'").fetchall():
                previous = json.loads(payload)
                if previous.get("details", {}).get("authorship") != "human":
                    continue
                row = db.execute("SELECT game,data FROM objects WHERE key=?", (previous.get("assetKey"),)).fetchone()
                if not row or row[0] != game:
                    raise ValueError("An authored chapter's original is unavailable")
                doc = json.loads(row[1])
                if doc.get("entityType") != "UserChapter" or doc.get("gameId") != game or doc.get("chapterId") != identity or not re.fullmatch(r"[a-f0-9]{64}", doc.get("seriesId", "")) or type(doc.get("version")) is not int or doc["version"] < 1:
                    raise ValueError("An authored chapter's series could not be verified")
                updated = {**previous, "seriesId": doc["seriesId"], "version": doc["version"], "sessionId": "chapter-" + doc["seriesId"][:24]}
                if updated == previous:
                    continue
                audit = {"schemaVersion": 1, "previousRecord": previous, "sourceSha256": hashlib.sha256(row[1]).hexdigest()}
                db.execute("INSERT OR IGNORE INTO records VALUES ('development-migration',?,?,?)", ("authored-series-v1:" + identity, game, json.dumps(audit)))
                db.execute("UPDATE records SET payload=? WHERE kind='chapter' AND id=?", (json.dumps(updated), identity))

    def browser_playback_job(self, game, key, checksum):
        meta, raw = self.object(key)
        if hashlib.sha256(raw).hexdigest() != checksum:
            raise ValueError("Recording manifest checksum mismatch")
        doc = json.loads(raw)
        if doc.get("entityType") != "BrowserRecording" or doc.get("gameId") != game or doc.get("status") not in {"complete", "interrupted"} or not isinstance(doc.get("parts"), list) or not 1 <= len(doc["parts"]) <= 1000:
            raise ValueError("Choose a completed browser recording")
        if not key.startswith(f"games/{game}/assets/"):
            raise ValueError("Recording belongs to another game")
        for part in doc["parts"]:
            if not re.fullmatch(r"part-[0-9]{4}\.wav", part.get("file", "")):
                raise ValueError("Invalid recording part")
            _, audio = self.object(key.rsplit("/", 1)[0] + "/" + part["file"])
            if hashlib.sha256(audio).hexdigest() != part["sha256"]:
                raise ValueError("Audio checksum mismatch")
        return {"jobId": checksum, "gameId": game, "chunkSetId": doc["id"], "workflowVersion": 2, "setStatus": "COMPLETE", "recordingKey": key, "sourceManifestSha256": checksum, "status": "QUEUED"}

    def migrate_browser_playback(self):
        """Pin old local completed sets by their exact manifest digest; preserve audit history."""
        if self.get("development-migration", "browser-playback-v2"):
            return
        snapshots = []
        with self.connect() as db:
            jobs = db.execute("SELECT id,game,payload FROM records WHERE kind='playback'").fetchall()
            sources = db.execute("SELECT key,game,data FROM objects WHERE key LIKE '%/recording.json'").fetchall()
        for identity, game, payload in jobs:
            old = json.loads(payload)
            if old.get("recordingKey") or old.get("status") == "DONE":
                continue
            matches = [(key, raw) for key, source_game, raw in sources if source_game == game and hashlib.sha256(raw).hexdigest() == identity]
            try:
                if len(matches) != 1:
                    raise ValueError("The original completed recording manifest could not be verified. Retained browser audio remains downloadable.")
                job = self.browser_playback_job(game, matches[0][0], identity)
            except (ValueError, LookupError, KeyError) as error:
                job = {**old, "status": "FAILED", "message": str(error)}
            self.put("playback", identity, job, game)
            snapshots.append({"jobId": identity, "previousRecord": old, "previousSha256": hashlib.sha256(payload.encode()).hexdigest(), "newStatus": job["status"]})
        self.put("development-migration", "browser-playback-v2", {"schemaVersion": 2, "migratedAt": datetime.now(timezone.utc).isoformat(), "sources": snapshots})

    def migrate_episode_composition(self):
        """One-time audited upgrade of prior explicit local scene order, never a read fallback."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM records WHERE kind='development-migration' AND id='episode-composition-v1'").fetchone():
                return
            rows = db.execute("SELECT kind,id,game,payload FROM records WHERE kind IN ('episode','scene') ORDER BY id").fetchall()
            scenes = [json.loads(row[3]) for row in rows if row[0] == "scene"]
            snapshots = []
            for kind, identity, game, payload in rows:
                record = json.loads(payload)
                updated = dict(record)
                if kind == "episode" and "sceneIds" not in record:
                    owned = [scene for scene in scenes if scene["gameId"] == game and scene["episodeId"] == record["id"]]
                    updated["sceneIds"] = [scene["id"] for scene in sorted(owned, key=lambda scene: (scene["position"], scene["id"]))]
                if kind == "scene" and "selectedOutputKey" not in record:
                    updated.update(selectedOutputKey=None, selectedOutputSceneRevision=None)
                if updated != record:
                    updated["revision"] = uuid.uuid4().hex
                    updated["updatedAt"] = datetime.now(timezone.utc).isoformat()
                    snapshots.append({"kind": kind, "id": identity, "sourceSha256": hashlib.sha256(payload.encode()).hexdigest(), "sourcePayload": payload, "destinationRevision": updated["revision"]})
                    db.execute("UPDATE records SET payload=? WHERE kind=? AND id=?", (json.dumps(updated), kind, identity))
                    history = {"record": updated, "previousRecord": record, "recordedAt": updated["updatedAt"], "reason": "Development composition schema migration v1"}
                    db.execute("INSERT INTO records VALUES (?,?,?,?)", (kind + "-history", identity + ":" + updated["revision"], game, json.dumps(history)))
            audit = {"schemaVersion": 1, "migratedAt": datetime.now(timezone.utc).isoformat(), "sources": snapshots}
            db.execute("INSERT INTO records VALUES ('development-migration','episode-composition-v1','',?)", (json.dumps(audit),))

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def get(self, kind, identity):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, identity)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind, game=None):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM records WHERE kind=?" + (" AND game=?" if game is not None else "") + " ORDER BY rowid DESC", (kind, game) if game is not None else (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, kind, identity, payload, game=""):
        with self.connect() as db:
            db.execute("INSERT INTO records VALUES (?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,game=excluded.game", (kind, identity, game, json.dumps(payload)))
            notice = self.notification_for_job(kind, payload, game)
            if notice:
                db.execute("INSERT OR IGNORE INTO records VALUES ('notification',?,?,?)", (notice["id"], notice["gameId"], json.dumps({**notice, "readAt": None})))
        return payload

    def seed(self):
        """Explicit debugger operation; data is written once, never returned as fixtures."""
        with self.connect() as db:
            for generated in self.list("demo"):
                db.execute("DELETE FROM records WHERE kind=? AND id=?", (generated["kind"], generated["id"]))
                if generated["kind"] == "character":
                    db.execute("DELETE FROM records WHERE kind='history' AND game=?", (generated["id"],))
            db.execute("DELETE FROM records WHERE kind='demo'")
        for identity, name, ruleset in [("preview-campaign", "The Lantern Campaign", "Pathfinder"), ("preview-sandbox", "Creative Sandbox", None)]:
            if not self.get("game", identity):
                self.put("game", identity, {"id": identity, "name": name, "purpose": "campaign", "ruleset": ruleset, "visualStyle": "illustrated-fantasy", "description": "", "descriptionRevision": uuid.uuid4().hex})
                self.put("demo", "game:" + identity, {"kind": "game", "id": identity})
        for identity, name in [("lantern-guide", "The Lantern Guide"), ("silver-wren", "Silver Wren")]:
            key = "preview-campaign:" + identity
            if not self.get("character", key):
                self.create_character({"gameId": "preview-campaign", "id": identity, "name": name})
                self.put("demo", "character:" + key, {"kind": "character", "id": key})
        return {"games": len(self.list("game")), "characters": len(self.list("character"))}

    def game(self, identity):
        record = self.get("game", identity)
        if not record:
            raise LookupError("Game not found")
        return {"game": {k: v for k, v in record.items() if k not in ("description", "descriptionRevision")}, "gameSettings": {k: record.get(k) for k in ("description", "descriptionRevision")}, "canEditGame": True, "visualStyles": [{"id": v, "label": v.replace("-", " ").title(), "previewImage": "/style-previews/" + v + ".webp"} for v in STYLES], "players": self.list("player", identity), "memberships": self.list("membership", identity), "characters": self.list("character", identity)}

    def create_game(self, body):
        fields = {"id", "name", "purpose", "players", "characters", "memberships"}
        if not fields <= set(body) or set(body) - fields - {"ruleset", "visualStyle"} or not isinstance(body["id"], str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", body["id"]) or len(body["id"]) > 96:
            raise ValueError("Invalid game details.")
        for value in [body["name"], *([body["ruleset"]] if "ruleset" in body else [])]:
            if not isinstance(value, str) or not 1 <= len(value) <= 120 or value != value.strip() or any(ord(c) < 32 for c in value):
                raise ValueError("Enter a name of up to 120 characters.")
        if body["purpose"] not in {"campaign", "test"} or body.get("visualStyle", "photorealistic") not in STYLES or any(not isinstance(body[field], list) for field in ("players", "characters", "memberships")):
            raise ValueError("Invalid game details.")
        if any(body[field] for field in ("players", "characters", "memberships")):
            raise ValueError("Add people and characters after creating the game.")
        identity = body["id"]
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        record = {"id": identity, "name": body["name"], "purpose": body["purpose"], "ruleset": body.get("ruleset"), "visualStyle": body.get("visualStyle", "photorealistic"), "description": "", "descriptionRevision": uuid.uuid4().hex, "fingerprint": fingerprint, "createdAt": int(time.time())}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM records WHERE kind='game' AND id=?", (identity,)).fetchone()
            if row and json.loads(row[0]).get("fingerprint") != fingerprint:
                raise FileExistsError("A game with this identity already exists.")
            if not row:
                db.execute("INSERT INTO records VALUES ('game',?,?,?)", (identity, None, json.dumps(record)))
        return self.game(identity)

    def create_character(self, body):
        game, identity = body["gameId"], body["id"]
        if not self.get("game", game) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identity):
            raise ValueError("Choose a valid game and character ID")
        key = game + ":" + identity
        if self.get("character", key):
            raise FileExistsError("Character already exists")
        record = {"schemaVersion": 2, "gameId": game, "id": identity, "characterId": identity, "name": body["name"], "revision": uuid.uuid4().hex, "details": details(), "updatedAt": int(time.time())}
        self.put("character", key, record, game)
        self.put("history", key + ":" + record["revision"], {"revision": record["revision"], "previousRevision": None, "recordedAt": datetime.now(timezone.utc).isoformat(), "reason": "Created character", "name": record["name"], "details": record["details"]}, key)
        return {"character": record}

    def edit_character(self, body):
        key = body["gameId"] + ":" + body["characterId"]
        record = self.get("character", key)
        if not record:
            raise LookupError("Character not found")
        if record["revision"] != body["expectedRevision"]:
            raise FileExistsError("Character changed. Reopen it before saving.")
        updated = {**record, "name": body.get("name", record["name"]), "details": body["details"], "revision": uuid.uuid4().hex, "updatedAt": int(time.time())}
        with self.connect() as db:
            changed = db.execute("UPDATE records SET payload=? WHERE kind='character' AND id=? AND json_extract(payload,'$.revision')=?", (json.dumps(updated), key, record["revision"])).rowcount
            if not changed:
                raise FileExistsError("Character changed")
            history = {"revision": updated["revision"], "previousRevision": record["revision"], "recordedAt": datetime.now(timezone.utc).isoformat(), "reason": body["reason"], "name": updated["name"], "previousName": record["name"], "details": updated["details"], "previousDetails": record["details"]}
            db.execute("INSERT INTO records VALUES ('history',?,?,?)", (key + ":" + updated["revision"], key, json.dumps(history)))
        return {"character": updated}

    def save_story_entity(self, kind, body):
        game, identity, operation = body["gameId"], body["id"], body["operationId"]
        self.game(game)
        expected_fields = {"gameId", "id", "name", "description", "expectedRevision", "operationId"} | ({"episodeId", "type", "selectedOutputKey", "mapAssetKey", "generationInputs"} if kind == "scene" else {"sceneIds"})
        required_fields = expected_fields - {"description", "type", "selectedOutputKey", "mapAssetKey", "generationInputs", "sceneIds"}
        if not required_fields <= set(body) <= expected_fields:
            raise ValueError("Invalid episode or scene edit")
        if kind not in ("episode", "scene") or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identity) or not re.fullmatch(r"[a-f0-9]{32}", operation):
            raise ValueError("Invalid episode, scene or operation ID")
        if not isinstance(body.get("name"), str) or not 1 <= len(body["name"].strip()) <= 160 or not isinstance(body.get("description", ""), str) or len(body.get("description", "")) > 4000:
            raise ValueError("Enter a title and a description under 4000 characters")
        episode_id = body.get("episodeId") if kind == "scene" else None
        if kind == "scene" and (not isinstance(episode_id, str) or not self.get("episode", game + ":" + episode_id) or body.get("type", "general") not in {"general", "opener", "travel", "map", "action", "dialogue"}):
            raise ValueError("Choose an episode in this game and a valid scene type")
        key = game + ":" + ((episode_id + ":") if episode_id else "") + identity
        payload = json.dumps(body, sort_keys=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous_operation = db.execute("SELECT payload,response FROM operations WHERE id=?", (operation,)).fetchone()
            if previous_operation:
                if previous_operation[0] != kind + ":" + payload:
                    raise FileExistsError("Operation reused with different content")
                return json.loads(previous_operation[1])
            row = db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
            previous = json.loads(row[0]) if row else None
            if body.get("expectedRevision") != (previous["revision"] if previous else None):
                raise FileExistsError("This record changed. Reopen it before saving.")
            if kind == "scene" and previous:
                for job_kind in ("scene-render", "editorial"):
                    for job_row in db.execute("SELECT payload FROM records WHERE kind=? AND game=?", (job_kind, game)):
                        active = json.loads(job_row[0])
                        ref = active.get("sceneRef") or active.get("creation", {}).get("sceneRef") or {}
                        if ref.get("episodeId") == episode_id and ref.get("sceneId") == identity and active.get("status") in {"QUEUED", "SUBMITTED", "RUNNING", "PROCESSING", "COMPOSING", "IN_QUEUE", "IN_PROGRESS"}:
                            raise FileExistsError("This scene is generating. You can edit it when generation finishes.")
            record = {"schemaVersion": 1, "entityType": "Episode" if kind == "episode" else "Scene", "gameId": game, "id": identity, "name": body["name"].strip(), "description": body.get("description", "").strip(), "revision": uuid.uuid4().hex, "updatedAt": datetime.now(timezone.utc).isoformat()}
            record["createdAt"] = previous["createdAt"] if previous else record["updatedAt"]
            if kind == "episode":
                record["position"] = previous["position"] if previous else int(time.time() * 1000)
                ids = body.get("sceneIds", previous["sceneIds"] if previous else [])
                owned = [json.loads(row[0])["id"] for row in db.execute("SELECT payload FROM records WHERE kind='scene' AND game=? AND json_extract(payload,'$.episodeId')=?", (game, identity)).fetchall()]
                if not isinstance(ids, list) or len(ids) > 50 or any(not isinstance(value, str) for value in ids) or len(ids) != len(set(ids)) or set(ids) != set(owned):
                    raise ValueError("Scene order must include every same-episode scene exactly once")
                record["sceneIds"] = ids
            if kind == "scene":
                count = db.execute("SELECT count(*) FROM records WHERE kind='scene' AND game=? AND json_extract(payload,'$.episodeId')=?", (game, episode_id)).fetchone()[0]
                if not previous and count >= 50:
                    raise ValueError("Episode supports at most 50 scenes")
                selected = body.get("selectedOutputKey", previous["selectedOutputKey"] if previous else None)
                selected_revision = None
                if selected is not None:
                    if not isinstance(selected, str) or not selected.startswith(f"games/{game}/assets/"):
                        raise ValueError("Choose a same-game finished scene video")
                    asset_row = db.execute("SELECT metadata FROM objects WHERE key=? AND game=? AND NOT EXISTS (SELECT 1 FROM records WHERE kind='asset-deletion' AND id=objects.key)", (selected, game)).fetchone()
                    meta = json.loads(asset_row[0]) if asset_row else {}
                    extra = meta.get("extra", {})
                    ref = extra.get("sceneRef", {})
                    if not meta.get("contentType", "").startswith("video/") or extra.get("relationshipRole") != "finished" or ref.get("episodeId") != episode_id or ref.get("sceneId") != identity or not re.fullmatch(r"[a-f0-9]{32}", ref.get("revision", "")):
                        raise ValueError("Choose a finished output of this scene")
                    historical = db.execute("SELECT 1 FROM records WHERE kind='scene-history' AND id=?", (key + ":" + ref["revision"],)).fetchone()
                    if not historical:
                        raise ValueError("Selected output has no exact scene revision")
                    selected_revision = ref["revision"]
                map_key = body.get("mapAssetKey", previous.get("mapAssetKey") if previous else None)
                if "mapAssetKey" in body or "mapAssetKey" in (previous or {}):
                    record["mapAssetKey"] = map_key
                if map_key is not None:
                    self.map_asset(game, map_key, db)
                    record["mapAssetKey"] = map_key
                production_asset_views()
                import scene_inputs
                inputs = scene_inputs.normalize(body.get("generationInputs", (previous or {}).get("generationInputs")), game)
                for character_id in inputs["characterIds"]:
                    if not db.execute("SELECT 1 FROM records WHERE kind='character' AND id=? AND game=?", (game + ":" + character_id, game)).fetchone():
                        raise ValueError("Choose a character from this game")
                for source_key in scene_inputs.asset_keys({"generationInputs": inputs}):
                    if not db.execute("SELECT 1 FROM objects WHERE key=? AND game=? AND NOT EXISTS (SELECT 1 FROM records WHERE kind='asset-deletion' AND id=objects.key)", (source_key, game)).fetchone():
                        raise ValueError("A selected source is unavailable")
                record["generationInputs"] = inputs
                record.update( episodeId=episode_id, type=body.get("type", "general"), position=previous["position"] if previous else count, selectedOutputKey=selected, selectedOutputSceneRevision=selected_revision)
            db.execute("INSERT INTO records VALUES (?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload", (kind, key, game, json.dumps(record)))
            history = {"record": record, "previousRecord": previous, "recordedAt": record["updatedAt"]}
            db.execute("INSERT INTO records VALUES (?,?,?,?)", (kind + "-history", key + ":" + record["revision"], game, json.dumps(history)))
            response = {"record": record}
            if kind == "scene" and not previous:
                parent_key = game + ":" + episode_id
                parent_row = db.execute("SELECT payload FROM records WHERE kind='episode' AND id=?", (parent_key,)).fetchone()
                parent = json.loads(parent_row[0])
                updated_parent = {**parent, "sceneIds": [*parent["sceneIds"], identity], "revision": uuid.uuid4().hex, "updatedAt": record["updatedAt"]}
                db.execute("UPDATE records SET payload=? WHERE kind='episode' AND id=?", (json.dumps(updated_parent), parent_key))
                parent_history = {"record": updated_parent, "previousRecord": parent, "recordedAt": record["updatedAt"], "reason": "Append newly created scene"}
                db.execute("INSERT INTO records VALUES ('episode-history',?,?,?)", (parent_key + ":" + updated_parent["revision"], game, json.dumps(parent_history)))
                response["episodeRecord"] = updated_parent
            db.execute("INSERT INTO operations VALUES (?,?,?)", (operation, kind + ":" + payload, json.dumps(response)))
        return response

    def map_asset(self, game, key, db=None):
        """Resolve a single explicitly selected local catalog record, preserving cloud rules."""
        if not isinstance(key, str) or not re.fullmatch(r"games/" + re.escape(game) + r"/assets/[a-z0-9-]+/(?:original|derived/[a-z0-9-]+|metadata)/[^/]+", key):
            raise ValueError("Choose a same-game map image")
        if db is None:
            with self.connect() as connection:
                return self.map_asset(game, key, connection)
        row = db.execute("SELECT metadata,data FROM objects WHERE key=? AND game=? AND NOT EXISTS (SELECT 1 FROM records WHERE kind='asset-deletion' AND id=objects.key)", (key, game)).fetchone()
        if not row:
            raise ValueError("Map image is unavailable in the catalog")
        meta, data = json.loads(row[0]), row[1]
        production_asset_views()
        import asset_metadata
        extra = meta.get("extra") or {}
        if not isinstance(extra, dict) or not isinstance(meta.get("kind", ""), str):
            raise ValueError("Invalid map metadata")
        if meta.get("contentType") not in {"image/png", "image/jpeg", "image/webp"} or meta.get("lineageWarning") or asset_metadata.internal(meta.get("kind", "")) or extra.get("relationshipRole") in {"processing", "intermediate", "internal"}:
            raise ValueError("Choose a finished PNG, JPEG or WebP map image")
        return meta, data

    def pin_map(self, game, scene):
        if not scene or scene.get("type") != "map":
            return None
        key = scene.get("mapAssetKey")
        meta, data = self.map_asset(game, key)
        if not 0 < len(data) <= 20 * 1024**2:
            raise ValueError("Choose a checksummed map image under 20 MiB")
        return {"schemaVersion": 1, "key": key, "sha256": base64.b64encode(hashlib.sha256(data).digest()).decode(), "size": len(data), "contentType": meta["contentType"], "role": "first-frame", "instructions": production_asset_views().MAP_SCENE_INSTRUCTIONS}

    def episode_composition(self, game, episode_id, revision):
        history = self.get("episode-history", game + ":" + episode_id + ":" + revision)
        episode = history["record"] if history else None
        if not episode or episode.get("gameId") != game:
            raise LookupError("Episode revision not found")
        if not episode["sceneIds"]:
            raise ValueError("Add scenes before previewing this episode")
        scenes, missing, sources = [], [], []
        for identity in episode["sceneIds"]:
            scene = self.get("scene", game + ":" + episode_id + ":" + identity)
            if not scene:
                raise LookupError("Scene in episode order is unavailable")
            selected = scene["selectedOutputKey"]
            generation = None
            if selected:
                with self.connect() as db:
                    asset_row = db.execute("SELECT metadata FROM objects WHERE key=? AND game=?", (selected, game)).fetchone()
                if not asset_row:
                    raise LookupError("Selected output unavailable")
                meta = json.loads(asset_row[0])
                generation = meta.get("extra", {}).get("sceneRef")
                if not meta.get("contentType", "").startswith("video/") or meta.get("extra", {}).get("relationshipRole") != "finished" or not generation or generation.get("episodeId") != episode_id or generation.get("sceneId") != identity or generation.get("revision") != scene["selectedOutputSceneRevision"]:
                    raise ValueError("Selected scene output is invalid")
                sources.append(selected)
            else:
                missing.append(identity)
            scenes.append({"sceneRef": {"episodeId": episode_id, "sceneId": identity, "revision": scene["revision"]}, "generationSceneRef": generation, "scene": scene, "assetKey": selected})
        result = {"schemaVersion": 1, "entityType": "EpisodeComposition", "gameId": game, "episode": episode, "ready": not missing, "missingSceneIds": missing, "scenes": scenes, "sourceKeys": sources}
        result["compositionHash"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        return result

    def objects(self, game):
        with self.connect() as db:
            rows = db.execute("SELECT key,metadata,length(data),created FROM objects WHERE game=? AND NOT EXISTS (SELECT 1 FROM records WHERE kind='asset-deletion' AND id=objects.key) ORDER BY created DESC", (game,)).fetchall()
            thumbnails = {key: json.loads(payload) for key, payload in db.execute("SELECT id,payload FROM records WHERE kind='video-thumbnail' AND game=?", (game,))}
        assets = [{"key": key, "name": key.rsplit("/", 1)[-1], "metadata": json.loads(meta), "contentType": json.loads(meta).get("contentType", "application/octet-stream"), "kind": json.loads(meta).get("kind", "other"), "size": size, "lastModified": created} for key, meta, size, created in rows]
        for asset in assets:
            if asset['kind'] == 'recording-manifest' and asset['name'] == 'recording.json':
                try:
                    _, raw = self.object(asset['key'])
                    if len(raw) <= 2 * 1024**2:
                        projected = production_asset_views().recording_summary(json.loads(raw))
                        if projected:
                            asset['recording'] = projected
                except (ValueError, UnicodeError, LookupError):
                    pass
            if asset['contentType'].startswith('video/'):
                thumbnail = thumbnails.get(asset['key'], {})
                asset['thumbnailStatus'] = thumbnail.get('status', 'PENDING')
                if thumbnail.get('status') == 'READY':
                    asset['thumbnailKey'] = thumbnail['thumbnailKey']
        production_asset_views()
        from tag_management import project
        events = sorted(self.list('tag-change', game), key=lambda event: event['at'])
        return [project(asset, events) for asset in assets] if events else assets

    def episode_thumbnails(self, game, episodes):
        """Poster discovery does not select a take or change playback readiness."""
        with self.connect() as db:
            rows = db.execute("""WITH candidates AS (
                SELECT scene.game, json_extract(scene.payload,'$.episodeId') episode,
                    json_extract(scene.payload,'$.position') position,
                    COALESCE(NULLIF(json_extract(scene.payload,'$.selectedOutputKey'),''), (
                        SELECT json_extract(render.payload,'$.outputKey') FROM records render
                        JOIN objects output ON output.key=json_extract(render.payload,'$.outputKey')
                            AND output.game=render.game
                        WHERE render.kind='scene-render' AND render.game=scene.game
                            AND json_extract(render.payload,'$.status')='DONE'
                            AND json_extract(render.payload,'$.sceneRef.episodeId')=json_extract(scene.payload,'$.episodeId')
                            AND json_extract(render.payload,'$.sceneRef.sceneId')=json_extract(scene.payload,'$.id')
                            AND json_extract(output.metadata,'$.contentType') LIKE 'video/%'
                            AND NOT EXISTS (SELECT 1 FROM records archive WHERE archive.kind='asset-deletion' AND archive.id=output.key)
                        ORDER BY json_extract(render.payload,'$.completedAt') DESC, render.rowid DESC LIMIT 1
                    )) video_key
                FROM records scene WHERE scene.kind='scene' AND scene.game=?
            ) SELECT candidates.episode, thumbnail.payload FROM candidates
                JOIN objects video ON video.key=candidates.video_key AND video.game=candidates.game
                LEFT JOIN records thumbnail ON thumbnail.kind='video-thumbnail'
                    AND thumbnail.id=candidates.video_key AND thumbnail.game=candidates.game
                WHERE json_extract(video.metadata,'$.contentType') LIKE 'video/%'
                    AND NOT EXISTS (SELECT 1 FROM records archive WHERE archive.kind='asset-deletion' AND archive.id=video.key)
                ORDER BY candidates.position""", (game,)).fetchall()
        first = {}
        for episode, payload in rows:
            first.setdefault(episode, json.loads(payload) if payload else {})
        for episode in episodes:
            thumbnail = first.get(episode['id'], {})
            episode['thumbnailStatus'] = thumbnail.get('status', 'PENDING')
            if thumbnail.get('status') == 'READY':
                episode['thumbnailKey'] = thumbnail['thumbnailKey']
        return episodes

    def transcript_summary_source(self, game, key):
        self.game(game)
        if not isinstance(key, str) or not re.fullmatch(rf"games/{re.escape(game)}/assets/[a-z0-9-]+/original/[^/\\]+\.json", key):
            raise ValueError("Choose a structured same-game transcript")
        with self.connect() as db:
            row = db.execute("SELECT data FROM objects WHERE key=? AND game=?", (key, game)).fetchone()
        if not row:
            raise LookupError("Transcript not found")
        raw = row[0]
        if not 0 < len(raw) <= 2 * 1024**2:
            raise ValueError("Transcript exceeds the summary source limit")
        doc = json.loads(raw)
        if not isinstance(doc, dict):
            raise ValueError("Choose a structured transcript object")
        if doc.get("entityType") == "EditorialArtifact" and doc.get("stage") == "corrected-transcript":
            doc = doc.get("payload", {}).get("transcript", {}) if isinstance(doc.get("payload"), dict) else {}
        if not isinstance(doc, dict) or doc.get("entityType") not in {"PlayerTranscript", "BrowserTranscript"} or doc.get("gameId") != game or not isinstance(doc.get("segments"), list) or not doc["segments"] or any(not isinstance(segment, dict) or not isinstance(segment.get("text"), str) for segment in doc["segments"]):
            raise ValueError("Choose completed structured speech")
        if doc.get("entityType") == "BrowserTranscript" and doc.get("mode") != "final":
            raise ValueError("Live speech is not completed transcript evidence")
        return {"key": key, "sha256": base64.b64encode(hashlib.sha256(raw).digest()).decode(), "size": len(raw)}, doc

    def transcript_summary_view(self, game, key):
        reference, doc = self.transcript_summary_source(game, key)
        pointer_id = game + ":" + hashlib.sha256(key.encode()).hexdigest()
        pointer = self.get("summary-source", pointer_id) or {}
        job = self.get("transcript-summary", pointer.get("jobId", ""))
        if not job or job["source"] != reference:
            return {"schemaVersion": 1, "gameId": game, "key": key, "jobId": None, "status": "MISSING", "source": reference, "summary": None, "participants": [], "recordedAt": None, "assetKey": None}
        previous = self.get("transcript-summary", pointer.get("readyJobId", ""))
        if not job.get("summary") and previous and previous["source"] == reference:
            job = {**job, **{field: previous.get(field) for field in ("summary", "assetKey", "participants", "recordedAt")}}
        return job

    def submit_transcript_summary(self, body):
        if not isinstance(body, dict) or not {"gameId", "key"} <= set(body) <= {"gameId", "key", "operationId"}:
            raise ValueError("Choose a transcript")
        game, key = body["gameId"], body["key"]
        reference, doc = self.transcript_summary_source(game, key)
        operation = body.get("operationId", "initial")
        if operation != "initial" and (not isinstance(operation, str) or not re.fullmatch(r"[a-f0-9]{32}", operation)):
            raise ValueError("Invalid regeneration operation")
        identity = hashlib.sha256(json.dumps({"schemaVersion": 1, "source": reference, "operationId": operation}, sort_keys=True).encode()).hexdigest()
        pointer_id = game + ":" + hashlib.sha256(key.encode()).hexdigest()
        participants = []
        for player in doc.get("players", []) if isinstance(doc.get("players"), list) else []:
            if isinstance(player, dict) and isinstance(player.get("id", player.get("playerId")), str):
                participants.append({"id": player.get("id", player.get("playerId")), **({"name": player["name"]} if isinstance(player.get("name"), str) else {})})
        declared = {player["id"] for player in participants}
        for segment in doc["segments"]:
            player = segment.get("playerId")
            if isinstance(player, str) and player not in declared:
                participants.append({"id": player})
                declared.add(player)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM objects WHERE key=? AND game=? AND NOT EXISTS (SELECT 1 FROM records WHERE kind='asset-deletion' AND id=objects.key)", (key, game)).fetchone()
            if not row or base64.b64encode(hashlib.sha256(row[0]).digest()).decode() != reference["sha256"]:
                raise FileExistsError("This transcript changed. Choose it again before generating a summary.")
            existing = db.execute("SELECT payload FROM records WHERE kind='transcript-summary' AND id=?", (identity,)).fetchone()
            if not existing:
                pointer_row = db.execute("SELECT payload FROM records WHERE kind='summary-source' AND id=?", (pointer_id,)).fetchone()
                pointer = json.loads(pointer_row[0]) if pointer_row else {}
                previous = self.get("transcript-summary", pointer.get("readyJobId", ""))
                job = {"schemaVersion": 1, "gameId": game, "key": key, "jobId": identity, "source": reference, "operationId": operation, "status": "QUEUED", "message": None, "createdAt": int(time.time()), "participants": participants, "recordedAt": next((doc[field] for field in ("recordedAt", "startedAt", "capturedAt") if isinstance(doc.get(field), str)), None), "summary": None, "assetKey": None, "previousSummaryKey": previous.get("assetKey") if previous and previous["source"] == reference else None}
                inserted = db.execute("INSERT OR IGNORE INTO records VALUES ('transcript-summary',?,?,?)", (identity, game, json.dumps(job)))
                if inserted.rowcount:
                    db.execute("INSERT OR REPLACE INTO records VALUES ('summary-source',?,?,?)", (pointer_id, game, json.dumps({**pointer, "jobId": identity})))
        return self.transcript_summary_view(game, key)

    def submit_asset_generation(self, body):
        from dev_asset_generation import submit
        return submit(self, body)

    def asset_generation_options(self, game):
        from dev_asset_generation import options
        return options(self, game)

    def rename_asset(self, body):
        if not isinstance(body, dict) or set(body) != {"gameId", "key", "title", "sha256", "operationId"}:
            raise ValueError("Choose an asset and its new title")
        self.game(body["gameId"])
        if not isinstance(body["key"], str) or not body["key"].startswith(f"games/{body['gameId']}/assets/") or not isinstance(body["title"], str) or not 1 <= len(body["title"].strip()) <= 160 or any(ord(c) < 32 for c in body["title"]):
            raise ValueError("Choose a valid same-game asset and title")
        if not isinstance(body["operationId"], str) or not re.fullmatch(r"[a-f0-9]{32}", body["operationId"]):
            raise ValueError("Invalid rename operation")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous_operation = db.execute("SELECT payload,response FROM operations WHERE id=?", (body["operationId"],)).fetchone()
            if previous_operation:
                if json.loads(previous_operation[0]) != body:
                    raise ValueError("Operation reused with a different rename request")
                return json.loads(previous_operation[1])
            row = db.execute("SELECT metadata,data,created FROM objects WHERE key=? AND game=? AND NOT EXISTS (SELECT 1 FROM records WHERE kind='asset-deletion' AND id=objects.key)", (body["key"], body["gameId"])).fetchone()
            if not row:
                raise FileNotFoundError("Asset is no longer available")
            if base64.b64encode(hashlib.sha256(row[1]).digest()).decode() != body["sha256"]:
                raise FileExistsError("This asset changed. Choose it again before renaming.")
            previous = json.loads(row[0])
            metadata = {**previous, "title": body["title"].strip()}
            history = {"key": body["key"], "sha256": body["sha256"], "previousMetadata": previous, "metadata": metadata, "recordedAt": datetime.now(timezone.utc).isoformat(), "operationId": body["operationId"]}
            db.execute("INSERT INTO records VALUES ('asset-metadata-history',?,?,?)", (body["key"] + ":" + body["operationId"], body["gameId"], json.dumps(history)))
            db.execute("UPDATE objects SET metadata=? WHERE key=?", (json.dumps(metadata), body["key"]))
            response = {"key": body["key"], "title": metadata["title"], "asset": {"key": body["key"], "name": body["key"].rsplit("/", 1)[-1], "size": len(row[1]), "metadata": metadata, "contentType": metadata.get("contentType", "application/octet-stream"), "kind": metadata.get("kind", "unclassified"), "lastModified": row[2]}}
            db.execute("INSERT INTO operations VALUES (?,?,?)", (body["operationId"], json.dumps(body), json.dumps(response)))
        return response

    def asset_generation_view(self, job):
        if job:
            job = {**job, "status": {"DONE": "PUBLISHED", "IN_QUEUE": "QUEUED", "SUBMITTED": "QUEUED", "IN_PROGRESS": "GENERATING", "COMPOSING": "GENERATING"}.get(job.get("status"), job.get("status"))}
        label = "Image generation" if job and job.get("mediaType", "image") == "image" else "Generation"
        if job and job.get("status") in {"FAILED", "BLOCKED", "ATTENTION", "UNKNOWN"} and not job.get("recoverableWaiting"):
            message = label + " could not be confirmed." if job.get("outcomeUnknown") else "The asset could not be saved." if job.get("publicationRecoveryAvailable") else {400: ("The image" if label == "Image generation" else "The asset") + " could not be generated. Try another prompt.", 422: ("The image" if label == "Image generation" else "The asset") + " could not be generated. Try another prompt.", 429: label + " is temporarily unavailable."}.get(job.get("errorCode"), label + " is unavailable. Check the server configuration.")
            return {**job, "message": message, "error": None}
        if job and job.get("status") in {"QUEUED", "PENDING", "RUNNING", "GENERATING"}:
            service = self.get("service", {"video": "video", "audio": "narration", "text": "editorial"}.get(job.get("mediaType"), "images")) or {}
            if service.get("status") != "RUNNING" or time.time() - service.get("updatedAt", 0) > 120:
                return {**job, "status": "ATTENTION", "recoverableWaiting": True, "message": label + " is unavailable. Check the server configuration."}
        return job

    def asset_generation_page(self, game, cursor=None, character=None):
        self.game(game)
        offset = 0
        if cursor:
            try:
                pointer = json.loads(base64.urlsafe_b64decode(cursor))
            except (ValueError, UnicodeError):
                raise ValueError("Invalid generation cursor") from None
            if not isinstance(pointer, dict) or set(pointer) != {"gameId", "offset"} or pointer["gameId"] != game or type(pointer["offset"]) is not int or pointer["offset"] < 0:
                raise ValueError("Invalid generation cursor")
            offset = pointer["offset"]
        with self.connect() as db:
            if character:
                if not isinstance(character, str) or not self.get("character", game + ":" + character):
                    raise ValueError("Choose a same-game character")
                rows = db.execute("SELECT payload FROM records WHERE kind='asset-generation' AND game=? AND (json_extract(payload,'$.characterId')=? OR EXISTS(SELECT 1 FROM json_each(json_extract(records.payload,'$.characterIds')) WHERE value=?)) ORDER BY rowid DESC LIMIT 26 OFFSET ?", (game, character, character, offset)).fetchall()
            else:
                rows = db.execute("SELECT payload FROM records WHERE kind='asset-generation' AND game=? ORDER BY rowid DESC LIMIT 26 OFFSET ?", (game, offset)).fetchall()
        next_cursor = base64.urlsafe_b64encode(json.dumps({"gameId": game, "offset": offset + 25}).encode()).decode() if len(rows) > 25 else None
        return {"jobs": [self.asset_generation_view(json.loads(row[0])) for row in rows[:25]], "cursor": next_cursor}

    def upload_request(self, body):
        self.game(body["gameId"])
        for field in ("assetId", "kind"):
            if not isinstance(body.get(field), str) or len(body[field]) > 96 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", body[field]):
                raise ValueError("Invalid asset ID or kind")
        filename = body.get("filename")
        if not isinstance(filename, str) or not 1 <= len(filename.encode()) <= 180 or filename in {".", ".."} or any(ord(character) < 32 or character in "/\\" for character in filename):
            raise ValueError("Invalid filename")
        if type(body.get("size")) is not int or not 0 <= body["size"] <= 100 * 1024**2:
            raise ValueError("Uploads must be at most 100 MiB")
        if not isinstance(body.get("contentType"), str) or len(body["contentType"]) > 120 or not re.fullmatch(r"[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+", body["contentType"]):
            raise ValueError("Invalid content type")
        try:
            valid_checksum = isinstance(body.get("sha256"), str) and len(base64.b64decode(body["sha256"], validate=True)) == 32
        except ValueError:
            valid_checksum = False
        if not valid_checksum or not isinstance(body.get("metadata", {}), dict):
            raise ValueError("Invalid checksum or metadata")
        key = f"games/{body['gameId']}/assets/{body['assetId']}/original/{filename}"
        return key

    def describe_asset(self, game, key):
        """Exact immutable-key detail, independent of a currently loaded browse page."""
        self.game(game)
        if not isinstance(key, str) or len(key) > 1024 or not key.startswith(f"games/{game}/assets/") or key.endswith("/") or ".." in key.split("/") or any(ord(character) < 32 for character in key):
            raise ValueError("Invalid asset for selected game")
        with self.connect() as db:
            row = db.execute("SELECT metadata,data,created FROM objects WHERE key=? AND game=?", (key, game)).fetchone()
        if not row:
            raise LookupError("Asset not found")
        meta, raw, created = json.loads(row[0]), row[1], row[2]
        result = {"key": key, "name": key.rsplit("/", 1)[-1], "size": len(raw), "contentType": meta.get("contentType", "application/octet-stream"), "kind": meta.get("kind", "unclassified"), "metadata": meta, "lastModified": created, "document": None, "sourceKeys": []}
        result["sourceKeys"] = sorted({source for source in meta.get("sourceKeys", []) if isinstance(source, str) and source.startswith(f"games/{game}/assets/") and source != key}) if isinstance(meta.get("sourceKeys", []), list) else []
        if key.endswith(".json") and 0 < len(raw) <= 2 * 1024**2:
            try:
                doc = json.loads(raw)
                if isinstance(doc, dict):
                    if doc.get("gameId", game) != game:
                        result["lineageWarning"] = "Document game identity does not match; structured content excluded."
                    else:
                        result["document"] = doc
            except (ValueError, UnicodeError):
                result["lineageWarning"] = "Structured provenance could not be read. Original retained."
        elif key.endswith(".json") and len(raw) > 2 * 1024**2:
            result["lineageWarning"] = "Large document: only compact metadata links are indexed."
        return result

    def object(self, key):
        with self.connect() as db:
            row = db.execute("SELECT metadata,data FROM objects WHERE key=?", (key,)).fetchone()
        if not row:
            raise LookupError("Asset not found")
        from dev_cost_estimates import overlay
        return overlay(self, key, json.loads(row[0]), row[1]), row[1]

    def prepare_editorial_job(self, job):
        """Snapshot local inputs for a real worker without changing their source bytes."""
        game, creation = job["gameId"], job["creation"]
        catalog = self.game(game)
        catalog["officialArtwork"] = {}
        references = []
        for key in creation["sourceKeys"]:
            reference, _ = self.transcript_summary_source(game, key)
            references.append(reference)
        contexts = []
        for key in creation["contextKeys"]:
            meta, raw = self.object(key)
            if not key.startswith(f"games/{game}/assets/") or not 0 < len(raw) <= 2 * 1024**2:
                raise ValueError("Choose bounded same-game context")
            if meta.get("kind", "").startswith("novel") or meta.get("kind", "").startswith("video"):
                raise ValueError("Adaptations cannot become factual context")
            contexts.append({"key": key, "sha256": base64.b64encode(hashlib.sha256(raw).digest()).decode(), "size": len(raw), "contentType": meta.get("contentType", "application/octet-stream")})
        cast = []
        for identity in creation.get("characterIds", []):
            character = self.get("character", game + ":" + identity)
            if not character:
                raise ValueError("Choose same-game characters")
            cast.append({"characterId": identity, "name": character["name"], "details": character.get("details", {}), "appearance": None, "appearanceAssets": []})
        return {**job, "workflowVersion": 4, "sessionId": "creation-" + job["jobId"][:24], "rawSources": references, "selectedContext": contexts, "catalog": catalog, "gameContext": catalog, "selectedCharacters": cast, "contextCutoff": int(time.time()), "sourceMode": "transcript" if references else "prompt", "status": "QUEUED", "message": None, "localWorkerVersion": 1}

    def editorial_view(self, job):
        if job and job.get("status") in {"FAILED", "BLOCKED", "ATTENTION", "DEFERRED"}:
            # Keep the provider diagnostic in the persisted job and worker log.
            # The browser receives recovery copy for the operation it requested.
            name = "Video" if job.get("creation", {}).get("target") == "video" else "Chapter"
            result = {**job, "message": name + " generation could not finish. Your prompt and sources are saved."}
            result.pop("error", None)
            return result
        if not job or job.get("status") not in {"SUBMITTED", "QUEUED", "RUNNING"}:
            return job
        worker = self.get("service", "editorial") or {}
        if worker.get("status") == "RUNNING" and time.time() - worker.get("updatedAt", 0) < 120:
            return job
        return {**job, "status": "BLOCKED", "message": "Generation is temporarily unavailable. Your request is saved."}


    def submit_transcription(self, body):
        game, recording, mode = body["gameId"], body["recordingId"], body["mode"]
        self.game(game)
        if not re.fullmatch(r"recording-[a-f0-9]{32}", recording) or mode not in {"live", "final"}:
            raise ValueError("Choose a valid recording")
        inputs, manifest_pin = [], None
        session = {"sessionId": recording, "sessionName": "Recording", "captureWarnings": [], "captureStatus": "complete"}
        if mode == "final":
            playback = self.get("playback", body["playbackJobId"])
            if not playback or playback.get("gameId") != game or playback.get("chunkSetId") != recording:
                raise LookupError("Completed recording not found")
            self.browser_playback_job(game, playback["recordingKey"], playback["sourceManifestSha256"])
            _, raw = self.object(playback["recordingKey"])
            doc = json.loads(raw)
            manifest_pin = {"key": playback["recordingKey"], "sha256": base64.b64encode(hashlib.sha256(raw).digest()).decode(), "size": len(raw)}
            session = {"sessionId": doc["sessionId"], "sessionName": doc["sessionName"], "captureWarnings": doc["captureWarnings"], "captureStatus": doc["status"]}
            parts = [(playback["recordingKey"].rsplit("/", 1)[0] + "/" + part["file"], part) for part in doc["parts"]]
        else:
            key = body["inputKey"]
            if not re.fullmatch(rf"games/{re.escape(game)}/assets/{recording}/original/part-[0-9]{{4}}\.wav", key):
                raise ValueError("Choose a same-recording audio part")
            meta, _ = self.object(key)
            part = meta.get("extra", {}).get("browserPart")
            if not part or part.get("recordingId") != recording:
                raise ValueError("Audio has no verified recording part metadata")
            parts = [(key, part)]
            session["sessionId"] = meta.get("sessionId") or recording
        for key, part in parts:
            _, raw = self.object(key)
            if len(raw) != part["size"] or hashlib.sha256(raw).hexdigest() != part["sha256"]:
                raise ValueError("Recording audio changed")
            inputs.append({"key": key, "sha256": base64.b64encode(hashlib.sha256(raw).digest()).decode(), "size": len(raw), "duration": part["duration"], "start": part["start"]})
        identity = hashlib.sha256(json.dumps({"mode": mode, "inputs": inputs, "recording": manifest_pin}, sort_keys=True).encode()).hexdigest()
        job = self.get("transcription", identity)
        if not job:
            job = {"id": identity, "jobId": identity, "gameId": game, "recordingId": recording, "mode": mode, "status": "SUBMITTED", "inputs": inputs, "recording": manifest_pin, "createdAt": int(time.time()), **session}
            self.put("transcription", identity, job, game)
        return job

    def narration_voices(self):
        cached = self.get("service", "narration-voices")
        if cached and time.time() - cached.get("updatedAt", 0) < 300:
            return {"voices": cached["voices"]}
        from dev_narration_worker import ElevenLabs
        client = ElevenLabs()
        response = client.session.get("https://api.elevenlabs.io/v1/voices", timeout=(10, 30), allow_redirects=False)
        if response.status_code != 200:
            raise ValueError("The voice list is temporarily unavailable.")
        voices = [{"id": item["voice_id"], "name": item["name"], "previewUrl": item.get("preview_url")} for item in response.json().get("voices", []) if item.get("category") == "premade"]
        self.put("service", "narration-voices", {"updatedAt": time.time(), "voices": voices})
        return {"voices": voices}

    def submit_narration(self, body):
        game = body["gameId"]
        self.game(game)
        if body.get("episodeId") and not self.get("episode", game + ":" + body["episodeId"]):
            raise ValueError("Choose an episode in this game.")
        if not isinstance(body.get("text"), str) or not 1 <= len(body["text"].strip()) <= 5000 or not isinstance(body.get("direction", ""), str) or len(body.get("direction", "")) > 2000:
            raise ValueError("Enter narration text under 5000 characters.")
        if body.get("voiceId") not in {voice["id"] for voice in self.narration_voices()["voices"]}:
            raise ValueError("Choose an available stock voice.")
        sources = body.get("sourceKeys", [])
        if not isinstance(sources, list) or len(sources) > 20:
            raise ValueError("Choose valid narration sources.")
        refs = []
        for key in sources:
            if not isinstance(key, str) or not key.startswith(f"games/{game}/assets/"):
                raise ValueError("Choose sources from this game.")
            _, raw = self.object(key)
            refs.append({"key": key, "size": len(raw), "sha256": base64.b64encode(hashlib.sha256(raw).digest()).decode()})
        if not isinstance(body.get("operationId"), str) or not re.fullmatch(r"[a-f0-9]{32}", body["operationId"]):
            raise ValueError("Invalid narration request.")
        identity = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        existing = self.get("narration", identity)
        if existing:
            return existing
        job = {**body, "jobId": identity, "id": identity, "text": body["text"].strip(), "inputRefs": refs, "status": "QUEUED", "createdAt": int(time.time()), "updatedAt": int(time.time())}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for ref in refs:
                if db.execute("SELECT 1 FROM records WHERE kind='asset-deletion' AND id=?", (ref["key"],)).fetchone():
                    raise FileExistsError("A selected source was deleted. Choose another source.")
            db.execute("INSERT OR IGNORE INTO records VALUES ('narration',?,?,?)", (identity, game, json.dumps(job)))
        return job

    def tags(self, game):
        self.game(game)
        records = self.list("tag", game)
        names = {r["name"] for r in records if not r.get('deleted')}
        names.update(tag for asset in self.objects(game) for tag in asset.get("metadata", {}).get("tags", []))
        names = {name for name in names if not any(r.get('deleted') and r['name'].casefold() == name.casefold() for r in records)}
        return {"tags": sorted(names, key=str.casefold)}

    def manage_tag(self, body):
        production_asset_views()
        from tag_management import validate
        body = validate(body)
        game, name = body['gameId'], body['name']
        self.game(game)
        fingerprint = json.dumps(body, sort_keys=True)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT payload,response FROM operations WHERE id=?', (body['operationId'],)).fetchone()
            if previous:
                if previous[0] != 'tag:' + fingerprint:
                    raise FileExistsError('Operation reused with different content')
                return json.loads(previous[1])
            vocabulary = self.tags(game)['tags']
            if not any(value.casefold() == name.casefold() for value in vocabulary):
                raise LookupError('Tag not found')
            if body['action'] == 'rename' and any(value.casefold() == body['newName'].casefold() and value.casefold() != name.casefold() for value in vocabulary):
                raise FileExistsError('A tag with that name already exists')
            event = {**body, 'schemaVersion': 1, 'at': time.time()}
            db.execute("INSERT INTO records VALUES ('tag-change',?,?,?)", (body['operationId'], game, json.dumps(event)))
            db.execute("INSERT INTO records VALUES ('tag',?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload", (game + ':' + name.casefold(), game, json.dumps({'name': name, 'deleted': True})))
            vocabulary = [value for value in vocabulary if value.casefold() != name.casefold()]
            if body['action'] == 'rename':
                renamed = body['newName']
                db.execute("INSERT INTO records VALUES ('tag',?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload", (game + ':' + renamed.casefold(), game, json.dumps({'name': renamed, 'createdAt': event['at']})))
                vocabulary.append(renamed)
            response = {'tags': sorted(vocabulary, key=str.casefold)}
            db.execute('INSERT INTO operations VALUES (?,?,?)', (body['operationId'], 'tag:' + fingerprint, json.dumps(response)))
        return response

    def delete_asset(self, body):
        game, key, operation = body["gameId"], body["key"], body.get("operationId", "")
        self.game(game)
        if not isinstance(key, str) or not key.startswith(f"games/{game}/assets/") or not re.fullmatch(r"[a-f0-9]{32}", operation):
            raise ValueError("Choose an asset from this game.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT metadata,data FROM objects WHERE key=? AND game=?", (key, game)).fetchone()
            if not row:
                raise LookupError("Asset not found")
            sha = base64.b64encode(hashlib.sha256(row[1]).digest()).decode()
            if body.get("sha256") != sha:
                raise FileExistsError("This asset changed. Reopen it before deleting.")
            previous = db.execute("SELECT payload FROM records WHERE kind='asset-deletion' AND id=?", (key,)).fetchone()
            if previous:
                return {"deleted": True, "key": key}
            for kind, payload in db.execute("SELECT kind,payload FROM records WHERE game=?", (game,)):
                record = json.loads(payload)
                if kind == "character" and record.get("details", {}).get("thumbnailAssetKey") == key or kind == "scene" and key in {record.get("mapAssetKey"), record.get("selectedOutputKey"), *(record.get("generationInputs", {}).get("sourceKeys", [])), *(record.get("generationInputs", {}).get("contextKeys", []))}:
                    raise FileExistsError("This asset is selected by a character or scene. Choose a replacement before deleting it.")
                if kind in {"editorial", "scene-render", "episode-render", "narration", "transcription", "playback", "transcript-summary", "asset-generation"} and record.get("status") in {"QUEUED", "SUBMITTED", "RUNNING", "PROCESSING", "GENERATING", "COMPOSING", "IN_QUEUE", "IN_PROGRESS"}:
                    def references(value):
                        if isinstance(value, dict):
                            return any(references(item) for item in value.values())
                        if isinstance(value, list):
                            return any(references(item) for item in value)
                        return value == key
                    if references(record):
                        raise FileExistsError("This asset is being processed. Wait for it to finish before deleting it.")
            tombstone = {"schemaVersion": 1, "entityType": "AssetDeletion", "gameId": game, "key": key, "sha256": sha, "operationId": operation, "deletedAt": int(time.time()), "previousMetadata": json.loads(row[0])}
            db.execute("INSERT INTO records VALUES ('asset-deletion',?,?,?)", (key, game, json.dumps(tombstone)))
        return {"deleted": True, "key": key}

    def create_tag(self, body):
        game, name = body["gameId"], body.get("name", "")
        self.game(game)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 64 or any(ord(c) < 32 for c in name):
            raise ValueError("Enter a tag of up to 64 characters.")
        name = name.strip()
        existing = next((value for value in self.tags(game)["tags"] if value.casefold() == name.casefold()), None)
        name = existing or name
        self.put("tag", game + ":" + name.casefold(), {"name": name, "createdAt": int(time.time())}, game)
        return {"tag": name, **self.tags(game)}

    def review_chapter(self, body):
        game, identity = body["gameId"], body["chapterId"]
        chapter = self.get("chapter", identity)
        if not chapter or chapter["gameId"] != game:
            raise LookupError("Chapter not found")
        status, comment, operation = body.get("status"), body.get("comment", ""), body.get("operationId", "")
        if status not in {"approved", "rejected"} or not isinstance(comment, str) or len(comment) > 4000 or not re.fullmatch(r"[a-f0-9]{32}", operation):
            raise ValueError("Choose Approved or Rejected and a comment of up to 4000 characters.")
        key = game + ":" + identity
        payload = json.dumps(body, sort_keys=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous_operation = db.execute("SELECT payload,response FROM operations WHERE id=?", (operation,)).fetchone()
            if previous_operation:
                if previous_operation[0] != "novel-review:" + payload:
                    raise FileExistsError("Operation reused with different content")
                return json.loads(previous_operation[1])
            row = db.execute("SELECT payload FROM records WHERE kind='novel-review' AND id=?", (key,)).fetchone()
            previous = json.loads(row[0]) if row else None
            if body.get("expectedRevision") != (previous["revision"] if previous else None):
                raise FileExistsError("This review changed. Reopen it before saving.")
            review = {"status": status, "comment": comment.strip() if status == "rejected" else "", "revision": uuid.uuid4().hex, "chapterId": identity, "gameId": game, "updatedAt": int(time.time())}
            db.execute("INSERT INTO records VALUES ('novel-review',?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload", (key, game, json.dumps(review)))
            db.execute("INSERT INTO records VALUES ('novel-review-history',?,?,?)", (key + ":" + review["revision"], game, json.dumps({"review": review, "previous": previous})))
            result = {"review": review}
            db.execute("INSERT INTO operations VALUES (?,?,?)", (operation, "novel-review:" + payload, json.dumps(result)))
        return result

    def generation_capabilities(self):
        def available(name):
            worker = self.get("service", name) or {}
            return worker.get("status") == "RUNNING" and time.time() - worker.get("updatedAt", 0) < 120
        return {name: available(service) for name, service in {
            "images": "images", "editorial": "editorial", "transcription": "transcription",
            "summaries": "summary", "playback": "playback", "video": "video",
            "narration": "narration", "episodes": "episodes"}.items()}

    def generation_job_view(self, job, kind):
        if not job:
            return job
        result = dict(job)
        if job.get("status") in {"FAILED", "ATTENTION", "UNKNOWN"}:
            name = {"scene-render": "Video generation", "episode-render": "Episode assembly", "narration": "Narration"}[kind]
            result["message"] = name + (" could not be confirmed. Check its status before trying again." if job.get("status") == "UNKNOWN" or job.get("outcomeUnknown") else " failed. Your inputs are saved; you can try again.")
            result.pop("error", None)
        return result

    def submit_episode_render(self, body):
        composition = self.episode_composition(body["gameId"], body["episodeId"], body["revision"])
        if not composition["ready"]:
            raise ValueError("Choose a rendered video for every scene first.")
        for scene in composition["scenes"]:
            _, raw = self.object(scene["assetKey"])
            scene.update(sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
        composition["profile"] = "episode-sdr-720p24-aac-v1"
        identity = hashlib.sha256(json.dumps(composition, sort_keys=True).encode()).hexdigest()
        job = self.get("episode-render", identity)
        if job and body.get("retry") is True and job["status"] in {"FAILED", "ATTENTION"}:
            self.put("episode-render-history", identity + ":" + uuid.uuid4().hex, job, body["gameId"])
            job = {**job, "status": "QUEUED", "updatedAt": int(time.time()), "message": None}
            self.put("episode-render", identity, job, body["gameId"])
        if not job:
            job = {"jobId": identity, "gameId": body["gameId"], "episodeId": body["episodeId"], "composition": composition, "status": "QUEUED", "createdAt": int(time.time()), "updatedAt": int(time.time()), "message": None}
            self.put("episode-render", identity, job, body["gameId"])
        return job

    def submit_scene_render(self, body):
        game, episode, identity = body["gameId"], body["episodeId"], body["sceneId"]
        scene = self.get("scene", game + ":" + episode + ":" + identity)
        if not scene or scene.get("revision") != body["revision"]:
            raise ValueError("The scene changed. Reopen it before generating.")
        prompt = body.get("prompt") or scene["name"]
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
            raise ValueError("Describe the video you want.")
        characters = body.get("characterIds", [])
        if not isinstance(characters, list) or len(characters) > 12 or len(set(characters)) != len(characters):
            raise ValueError("Choose valid characters.")
        refs, character_context = [], []
        for character in characters:
            record = self.get("character", game + ":" + character)
            if not record:
                raise ValueError("Choose characters from this game.")
            character_context.append({"id": character, "name": record["name"], "details": record.get("details", {})})
            thumbnail = record.get("details", {}).get("thumbnailAssetKey")
            if thumbnail:
                _, raw = self.object(thumbnail)
                refs.append({"key": thumbnail, "sha256": base64.b64encode(hashlib.sha256(raw).digest()).decode(), "size": len(raw)})
        source_keys, context_keys = body.get("sourceKeys", []), body.get("contextKeys", [])
        for keys in (source_keys, context_keys):
            if not isinstance(keys, list) or len(keys) > 20 or any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys):
                raise ValueError("Choose valid sources from this game.")
        for key in dict.fromkeys(source_keys + context_keys):
            if not key.startswith(f"games/{game}/assets/"):
                raise ValueError("Choose sources from this game.")
            if key in source_keys:
                self.transcript_summary_source(game, key)
            _, raw = self.object(key)
            refs.append({"key": key, "sha256": base64.b64encode(hashlib.sha256(raw).digest()).decode(), "size": len(raw)})
        map_pin = self.pin_map(game, scene)
        if map_pin:
            refs.append(map_pin)
        job = {"gameId": game, "sceneRef": {"episodeId": episode, "sceneId": identity, "revision": scene["revision"]}, "prompt": prompt.strip(), "sceneType": scene["type"], "sourceKeys": [ref["key"] for ref in refs], "inputRefs": refs, "mapPin": map_pin, "characterIds": characters, "characterContext": character_context, "transcriptKeys": source_keys, "contextKeys": context_keys}
        operation = body["operationId"]
        if not isinstance(operation, str) or not re.fullmatch(r"[a-f0-9]{32}", operation):
            raise ValueError("Invalid generation request.")
        key = hashlib.sha256(json.dumps({**job, "operationId": operation}, sort_keys=True).encode()).hexdigest()
        existing = self.get("scene-render", key)
        if existing:
            return existing
        job.update(id=key, jobId=key, status="QUEUED", createdAt=int(time.time()), updatedAt=int(time.time()))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT payload FROM records WHERE kind='scene' AND id=?", (game + ":" + episode + ":" + identity,)).fetchone()
            if not current or json.loads(current[0])["revision"] != body["revision"]:
                raise FileExistsError("The scene changed. Reopen it before generating.")
            for ref in refs:
                if db.execute("SELECT 1 FROM records WHERE kind='asset-deletion' AND id=?", (ref["key"],)).fetchone():
                    raise FileExistsError("A selected source was deleted. Choose another source.")
            duplicate = db.execute("SELECT payload FROM records WHERE kind='scene-render' AND id=?", (key,)).fetchone()
            if duplicate:
                return json.loads(duplicate[0])
            for row in db.execute("SELECT payload FROM records WHERE kind='scene-render' AND game=?", (game,)):
                active = json.loads(row[0])
                if active.get("sceneRef", {}).get("episodeId") == episode and active.get("sceneRef", {}).get("sceneId") == identity and active.get("status") in {"QUEUED", "SUBMITTED", "RUNNING", "COMPOSING", "IN_QUEUE", "IN_PROGRESS"}:
                    raise FileExistsError("This scene is already generating.")
            db.execute("INSERT INTO records VALUES ('scene-render',?,?,?)", (key, game, json.dumps(job)))
        return job

    def workflows(self, game, identity=None, cursor=None, view=None, workflow_type=None):
        """Observe real SQLite jobs without starting processing or inventing activity."""
        self.game(game)
        plan = json.loads((ROOT / "src/panther_journal/editorial-plan.json").read_text())
        states = {"SUBMITTED": "queued", "QUEUED": "queued", "RUNNING": "running", "PROCESSING": "running", "DONE": "done", "NOVEL_READY": "done", "READY_FOR_VIDEO_DISCUSSION": "done", "FAILED": "failed", "BLOCKED": "paused", "DEFERRED": "paused", "IN_QUEUE": "queued", "IN_PROGRESS": "running", "PUBLISHED": "done", "ATTENTION": "failed", "UNKNOWN": "paused", "GENERATING": "running", "COMPOSING": "running"}
        rows = []
        for kind in ("editorial", "playback"):
            for record in self.list(kind, game):
                job = self.editorial_view(record) if kind == "editorial" else record
                tasks = {task["stage"]: task for task in self.list("editorial-task", game) if task.get("jobId") == job["jobId"]} if kind == "editorial" else {}
                target = job.get("creation", {}).get("target", "novel")
                names = ((plan["correction"] if job.get("rawSources") and target == "novel" else ["context"]) + plan[target]) if kind == "editorial" else ["assemble-verify-publish"]
                stages = []
                for name in names:
                    task = tasks.get(name, {}) if kind == "editorial" else job
                    stages.append({"id": name, "label": name.replace("-", " ").capitalize(), "status": states.get(task.get("status"), "pending"), **({"outputKey": task["output"]["key"]} if isinstance(task.get("output"), dict) and task["output"].get("key") else {})})
                row = {"schemaVersion": 1, "id": kind + "~" + job["jobId"], "kind": kind, "gameId": game, "title": job.get("creation", {}).get("title") or ("Chapter generation" if target == "novel" else "Scene planning") if kind == "editorial" else "Continuous audio playback", "status": states.get(job.get("status"), "unknown"), "sourceStatus": job.get("status"), "createdAt": job.get("createdAt", 0), "sessionId": job.get("sessionId"), "stages": stages, "note": job.get("message") or "", "observedAt": int(time.time()), "reportedAt": job.get("updatedAt") or job.get("completedAt") or job.get("publishedAt") or job.get("createdAt", 0), "source": "local-worker", "workflowVersion": job.get("workflowVersion"), "completedStages": sum(s["status"] == "done" for s in stages), "totalStages": len(stages), "activeStages": [s for s in stages if s["status"] not in {"done", "pending"}]}
                if row["id"] == identity:
                    row["flow"] = {"schemaVersion": 1, "mode": "sequence", "lanes": [{"id": "sequence", "label": "Chapter generation" if kind == "editorial" and target == "novel" else "Processing", "stageIds": names}], "edges": [{"from": a, "to": b} for a, b in zip(names, names[1:])], "note": ""}
                    return {"workflow": row}
                rows.append(row)
        for kind, title in (("scene-render", "Scene video"), ("episode-render", "Episode assembly"), ("narration", "Narration"), ("asset-generation", "Asset generation"), ("transcription", "Transcription"), ("transcript-summary", "Transcript summary")):
            for job in self.list(kind, game):
                status = states.get(job.get("status"), "pending")
                output = job.get("outputKey") or job.get("assetKey") or job.get("transcriptKey")
                stages = [{"id": "processing", "label": title, "status": status, **({"outputKey": output} if output else {})}]
                row = {"schemaVersion": 1, "id": kind + "~" + job["jobId"], "kind": kind, "gameId": game, "title": job.get("title") or job.get("name") or job.get("prompt") or title, "status": status, "sourceStatus": status, "createdAt": job.get("createdAt", 0), "stages": stages, "note": job.get("message") or "", "observedAt": int(time.time()), "reportedAt": job.get("updatedAt") or job.get("completedAt") or job.get("publishedAt") or job.get("createdAt", 0), "source": "local-worker", "completedStages": int(status == "done"), "totalStages": 1, "activeStages": stages if status not in {"done", "pending"} else []}
                if row["id"] == identity:
                    row["flow"] = {"schemaVersion": 1, "mode": "sequence", "lanes": [{"id": "sequence", "label": title, "stageIds": ["processing"]}], "edges": [], "note": ""}
                    return {"workflow": row}
                rows.append(row)
        if identity:
            raise LookupError("Workflow not found in this game")
        from workflow_hierarchy import LABELS, summary
        if view == "types":
            return {"schemaVersion": 1, "types": [summary(kind, [row for row in rows if row["kind"] == kind]) for kind in LABELS if any(row["kind"] == kind for row in rows)]}
        if view == "runs":
            if workflow_type not in LABELS:
                raise ValueError("Unknown workflow type")
            rows = [row for row in rows if row["kind"] == workflow_type]
        rows.sort(key=lambda row: (row["createdAt"], row["id"]), reverse=True)
        offset = int(cursor or "0")
        if offset < 0 or offset > len(rows):
            raise ValueError("Invalid workflow cursor")
        return {"workflows": rows[offset:offset + 40], "cursor": str(offset + 40) if len(rows) > offset + 40 else None}


class Server(ThreadingHTTPServer):
    def __init__(self, address, store):
        super().__init__(address, Handler)
        self.store = store


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def send(self, body, content_type="application/json", status=200):
        data = json.dumps(body).encode() if content_type == "application/json" else body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            self.get()
        except LookupError as exc:
            self.send({"error": str(exc)}, status=404)
        except (ValueError, KeyError) as exc:
            self.send({"error": str(exc)}, status=400)

    def get(self):
        parsed = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        path, store = parsed.path, self.server.store
        if path == "/config.js":
            claims = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + 86400, "sub": "development-account", "cognito:username": "developer"}).encode()).decode().rstrip("=")
            tokens = json.dumps({"id_token": f"development.{claims}.local"})
            config = {"development": True, "apiUrl": self.origin, "clientId": "development", "cognitoDomain": self.origin, "redirectUri": self.origin + "/"}
            return self.send("window.PANTHER_CONFIG=" + json.dumps(config) + ";sessionStorage.setItem('panther.tokens'," + json.dumps(tokens) + ");", "application/javascript")
        if path == "/development/object":
            meta, raw = store.object(q["key"])
            return self.send(raw, meta.get("contentType", "application/octet-stream"))
        if self.headers.get("Authorization", "").startswith("Bearer "):
            game = q.get("gameId", "")
            if path == "/games":
                result = {"games": [self.server.store.game(g["id"])["game"] for g in store.list("game")]}
            elif path == "/notifications":
                result = store.notifications(q.get("view", "all"), q.get("cursor"))
            elif path == "/game":
                result = store.game(game)
            elif path == "/dashboard-recent":
                production_asset_views()
                import asset_metadata
                assets = store.objects(game)
                groups = {"characters": store.list("character", game), "transcripts": [a for a in assets if "transcript" in a["kind"]], "videos": [a for a in assets if a["contentType"].startswith("video/")], "chapters": store.list("chapter", game), "assets": [a for a in assets if a["contentType"].startswith("image/") and not asset_metadata.internal(a["kind"]) and not a.get("lineageWarning") and a["metadata"].get("extra", {}).get("relationshipRole") not in {"processing", "intermediate", "internal"}]}
                for values in groups.values():
                    values.sort(key=lambda value: str(value.get("updatedAt", value.get("publishedAt", value.get("lastModified", "")))), reverse=True)
                result = {"complete": True, "groups": {k: v[:5] for k, v in groups.items()}, "counts": {k: len(v) for k, v in groups.items()}}
            elif path == "/episode-composition":
                store.game(game)
                result = store.episode_composition(game, q["episodeId"], q["revision"])
            elif path in ("/episodes", "/scenes"):
                store.game(game)
                kind = "episode" if path == "/episodes" else "scene"
                if kind == "scene":
                    if not store.get("episode", game + ":" + q.get("episodeId", "")):
                        raise LookupError("Episode not found in this game")
                    records = [r for r in store.list(kind, game) if r["episodeId"] == q["episodeId"]]
                    records.sort(key=lambda record: record["position"])
                else:
                    records = store.list(kind, game)
                    records = store.episode_thumbnails(game, records)
                if q.get("id"):
                    identity = game + ":" + ((q["episodeId"] + ":") if kind == "scene" else "") + q["id"]
                    if q.get("revision"):
                        historical = store.get(kind + "-history", identity + ":" + q["revision"])
                        record = historical["record"] if historical else None
                    else:
                        record = store.get(kind, identity)
                    if not record:
                        raise LookupError("Episode or scene not found")
                    if kind == 'episode':
                        record = store.episode_thumbnails(game, [record])[0]
                    result = {"record": record}
                else:
                    result = {"records": records, "cursor": None}
            elif path == "/characters":
                result = {"characters": store.list("character", game), "cursor": None}
            elif path in ("/character", "/character-details", "/character-details/history"):
                key = game + ":" + q["characterId"]
                character = store.get("character", key)
                if not character:
                    raise LookupError("Character not found")
                result = {"character": character, "appearance": None, "selection": None, "poster": None, "model": None, "warnings": [], "canEdit": True}
                if path.endswith("history"):
                    result = {"history": store.list("history", key), "cursor": None}
            elif path == "/character-versions":
                result = {"schemaVersion": 2, "appearances": [], "selections": [], "activations": [], "current": None, "activationRevision": None}
            elif path == "/assets":
                assets = store.objects(game)
                section = q.get("section", "all")
                result = {"assets": local_assets(assets, section), "cursor": None}
            elif path == "/objects":
                prefix = q["prefix"]
                game = prefix.split("/")[1]
                assets = [a for a in store.objects(game) if a["key"].startswith(prefix)]
                result = {"objects": [a for a in assets if "/" not in a["key"][len(prefix):]], "prefixes": sorted({prefix + a["key"][len(prefix):].split("/")[0] + "/" for a in assets if "/" in a["key"][len(prefix):]}), "nextCursor": None}
            elif path == "/transcript-summaries":
                result = store.transcript_summary_view(game, q["key"])
            elif path == "/asset-generation":
                if q.get("view") == "options":
                    result = store.asset_generation_options(game)
                elif q.get("jobId"):
                    result = store.asset_generation_view(store.get("asset-generation", q["jobId"]))
                    if not result or result["gameId"] != game:
                        raise LookupError("Generation job not found")
                else:
                    result = store.asset_generation_page(game, q.get("cursor"), q.get("characterId"))
            elif path == "/asset-document":
                result = store.describe_asset(game, q["key"])
            elif path == "/object-url":
                meta, raw = store.object(q["key"])
                result = {"key": q["key"], "kind": meta.get("kind", "unclassified"), "filename": q["key"].rsplit("/", 1)[-1], "sha256": base64.b64encode(hashlib.sha256(raw).digest()).decode(), "url": self.origin + "/development/object?key=" + q["key"], "size": len(raw), "metadata": meta, "expiresIn": None, "contentType": meta.get("contentType", "application/octet-stream")}
                if meta.get('contentType', '').startswith('video/'):
                    thumbnail = store.get('video-thumbnail', q['key']) or {}
                    result['thumbnailStatus'] = thumbnail.get('status', 'PENDING')
                    if thumbnail.get('status') == 'READY':
                        result['thumbnailKey'] = thumbnail['thumbnailKey']
            elif path == "/generation-capabilities":
                result = store.generation_capabilities()
            elif path == "/browser-recording/capabilities":
                worker = store.get("service", "playback") or {}
                available = worker.get("status") == "RUNNING" and time.time() - worker.get("updatedAt", 0) < 120
                result = {"canRecord": True, "transcriptionAvailable": bool((store.get("service", "transcription") or {}).get("status") == "RUNNING" and time.time() - (store.get("service", "transcription") or {}).get("updatedAt", 0) < 120), "transcriptionUnavailableReason": "Transcription service is offline.", "playbackAvailable": available, "playbackUnavailableReason": "Audio processing is temporarily unavailable. Your recording is saved.", "liveModel": "gpt-live-transcribe", "liveTransport": "realtime", "model": "gpt-transcribe", "chunkSeconds": 15, "maxParts": 1000}
            elif path == "/browser-transcriptions":
                job = store.get("playback", q.get("playbackJobId", ""))
                if job and job.get("gameId") != game:
                    raise LookupError("Recording not found in this game")
                if job and job.get("status") in {"SUBMITTED", "QUEUED", "RUNNING"} and not store.generation_capabilities()["playback"]:
                    job = {**job, "status": "BLOCKED", "message": "Audio processing is temporarily unavailable. Your recording is saved."}
                jobs = [item for item in store.list("transcription", game) if item.get("recordingId") == q.get("recordingId") and item.get("mode") == q.get("mode", "live")]
                result = {"jobs": jobs, "transcriptKey": next((item.get("transcriptKey") for item in jobs if item.get("status") == "DONE"), None), **({"playback": job} if job else {})}
            elif path == "/novel":
                result = {"chapters": store.list("chapter", game), "cursor": None}
            elif path == "/tags":
                result = store.tags(game)
            elif path == "/novel-review":
                chapter = store.get("chapter", q["chapterId"])
                if not chapter or chapter["gameId"] != game:
                    raise LookupError("Chapter not found")
                result = {"review": store.get("novel-review", game + ":" + q["chapterId"])}
            elif path == "/novel-chapter":
                result = store.get("chapter", q["chapterId"])
                if not result or result["gameId"] != game:
                    raise LookupError("Chapter not found")
            elif path == "/editorial-jobs":
                if "jobId" not in q:
                    result = {"jobs": [store.editorial_view(job) for job in store.list("editorial", game)], "cursor": None}
                else:
                    job = store.get("editorial", q["jobId"])
                    if not job or job.get("gameId") != game:
                        raise LookupError("Generation job not found in this game")
                    result = {"job": store.editorial_view(job), "tasks": [task for task in store.list("editorial-task", job.get("gameId", "") if job else "") if task.get("jobId") == q["jobId"]]}
                    result["tasks"].sort(key=lambda task: task.get("ordinal", 0))
            elif path == "/narration-voices":
                result = store.narration_voices()
            elif path in ("/episode-renders", "/scene-renders", "/narration-jobs"):
                kind = {"/episode-renders": "episode-render", "/scene-renders": "scene-render", "/narration-jobs": "narration"}[path]
                if q.get("jobId"):
                    job = store.get(kind, q["jobId"])
                    if not job or job["gameId"] != game:
                        raise LookupError("Generation job not found")
                    result = store.generation_job_view(job, kind)
                else:
                    result = {"jobs": [store.generation_job_view(job, kind) for job in store.list(kind, game) if not q.get("episodeId") or job.get("episodeId", job.get("sceneRef", {}).get("episodeId")) == q["episodeId"]]}
            elif path == "/workflows":
                result = store.workflows(game, q.get("id"), q.get("cursor"), q.get("view"), q.get("type"))
            elif path in ("/novel-stories", "/novel-books", "/tv-series", "/tv-episodes"):
                kind = {"/novel-stories": "story", "/novel-books": "book", "/tv-series": "tv-series", "/tv-episodes": "tv-episode"}[path]
                if "id" in q:
                    record = store.get(kind, q["id"])
                    if not record or record["gameId"] != game:
                        raise LookupError("Record not found")
                    result = {"record": record}
                else:
                    result = {"records": store.list(kind, game), "cursor": None}
            elif path == "/novel-library":
                result = {"schemaVersion": 1, "stories": [], "books": [], "illustrations": [], "cursor": None}
            elif path == "/video-collections":
                collection = store.get("collection", game + ":" + q["id"]) if "id" in q else None
                if "id" in q and not collection:
                    raise LookupError("Scene not found")
                assets = {a["key"]: a for a in store.objects(game)}
                result = {"collection": collection, "assets": [assets[key] for key in collection["assetKeys"] if key in assets], "warnings": []} if collection else {"collections": store.list("collection", game), "cursor": None}
            elif path in ("/recordings/live", "/recordings/live/history"):
                result = {"recordings": [], "chunks": [], "collections": [], "cursor": None}
            else:
                raise LookupError("Operation unavailable on the development backend")
            return self.send(result)
        relative = path.lstrip("/")
        file = WEB / relative
        if not relative or not file.is_file():
            file = WEB / "index.html"
        if not file.resolve().is_relative_to(WEB):
            raise ValueError("Invalid file path")
        if path == "/vendor/model-viewer.min.js":
            file = ROOT / "infra/node_modules/@google/model-viewer/dist/model-viewer.min.js"
        return self.send(file.read_bytes(), mimetypes.guess_type(file.name)[0] or "application/octet-stream")

    def do_POST(self):
        if self.headers.get("Origin") not in (None, self.origin):
            return self.send({"error": "Same-origin development requests required"}, status=403)
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", "0")), 2 * 1024**2)))
            self.post(urlparse(self.path).path, body)
        except FileExistsError as exc:
            self.send({"error": str(exc)}, status=409)
        except LookupError as exc:
            self.send({"error": str(exc)}, status=404)
        except (ValueError, KeyError) as exc:
            self.send({"error": str(exc)}, status=400)

    def post(self, path, body):
        store = self.server.store
        if path == "/notifications/read":
            return self.send(store.read_notification(body["id"]))
        if path == "/games":
            return self.send(store.create_game(body))
        if path == "/development/seed":
            return self.send(store.seed())
        if path == "/auth/account":
            profile = store.get("profile", "developer") or {"username": "developer", "name": "", "picture": "", "email": "", "emailVerified": False, "totpEnabled": False}
            if body["action"] == "profile":
                store.put("profile", "developer", {**profile, "name": body["name"], "picture": body["picture"]})
                return self.send({})
            if body["action"] == "get":
                return self.send(profile)
            return self.send({"error": "Security settings require a Panther account on the live service."}, status=501)
        if path in ("/episodes", "/scenes"):
            return self.send(store.save_story_entity("episode" if path == "/episodes" else "scene", body))
        if path == "/game/characters":
            return self.send(store.create_character(body), status=201)
        if path == "/character-details":
            return self.send(store.edit_character(body))
        if path in ("/game/settings", "/game/style"):
            record = store.get("game", body["gameId"])
            if not record:
                raise LookupError("Game not found")
            if path.endswith("settings"):
                if body["expectedName"] != record["name"] or body["expectedRuleset"] != record["ruleset"] or body["expectedDescriptionRevision"] != record["descriptionRevision"]:
                    raise FileExistsError("Settings changed. Reopen Settings before saving.")
                record.update(name=body["name"], ruleset=body["ruleset"], description=body["description"], descriptionRevision=uuid.uuid4().hex)
            else:
                if body["expectedStyle"] != record["visualStyle"]:
                    raise FileExistsError("Style changed")
                record["visualStyle"] = body["visualStyle"]
            store.put("game", record["id"], record)
            return self.send(store.game(record["id"]))
        if path == "/video-collections":
            game, identity = body["gameId"], body["id"]
            store.game(game)
            existing = store.get("collection", game + ":" + identity)
            if body["expectedRevision"] != (existing["revision"] if existing else None):
                raise FileExistsError("Scene changed. Reopen it before saving.")
            if not 1 <= len(body["assetKeys"]) <= 50 or len(set(body["assetKeys"])) != len(body["assetKeys"]):
                raise ValueError("Choose distinct clips")
            for key in body["assetKeys"]:
                meta, _ = store.object(key)
                if not key.startswith(f"games/{game}/assets/") or not meta["contentType"].startswith("video/"):
                    raise ValueError("Choose same-game video clips")
            collection = {"schemaVersion": 1, "entityType": "VideoCollection", "gameId": game, "id": identity, "name": body["name"], "description": body["description"], "assetKeys": body["assetKeys"], "revision": uuid.uuid4().hex, "updatedAt": datetime.now(timezone.utc).isoformat()}
            store.put("collection", game + ":" + identity, collection, game)
            return self.send({"collection": collection})
        if path == "/editorial-jobs":
            game, creation = body["gameId"], body["creation"]
            store.game(game)
            video = creation.get("schemaVersion") == 2 and creation.get("target") == "video"
            prompt_novel = creation.get("schemaVersion") == 3 and creation.get("target") == "novel"
            if prompt_novel:
                if not isinstance(creation.get("brief"), str) or not 1 <= len(creation["brief"].strip()) <= 4000 or any(not isinstance(creation.get(field), list) or len(creation[field]) > maximum or any(not isinstance(value, str) for value in creation[field]) or len(set(creation[field])) != len(creation[field]) for field, maximum in (("sourceKeys", 8), ("contextKeys", 12))):
                    raise ValueError("Enter a prompt and choose valid optional sources")
                creation = {**creation, "title": creation["brief"].strip()[:160]}
            if not video and not prompt_novel and (creation.get("schemaVersion") != 1 or creation.get("target") != "novel" or not 1 <= len(creation["sourceKeys"]) <= 8):
                raise ValueError("Choose completed transcripts")
            if video:
                if not isinstance(creation.get("brief", ""), str) or len(creation.get("brief", "")) > 4000 or any(not isinstance(creation.get(field), list) or len(creation[field]) > limit or any(not isinstance(value, str) for value in creation[field]) or len(set(creation[field])) != len(creation[field]) for field, limit in (("sourceKeys", 8), ("characterIds", 12), ("contextKeys", 12))):
                    raise ValueError("Enter a prompt and choose up to 12 characters")
                for character in creation["characterIds"]:
                    if not store.get("character", game + ":" + character):
                        raise ValueError("Choose same-game characters")
                reference = creation.get("sceneRef")
                if not isinstance(reference, dict) or set(reference) != {"episodeId", "sceneId", "revision"}:
                    raise ValueError("Choose a scene")
                history_key = game + ":" + str(reference["episodeId"]) + ":" + str(reference["sceneId"]) + ":" + str(reference["revision"])
                history = store.get("scene-history", history_key)
                scene = history.get("record") if history else None
                if not store.get("episode", game + ":" + str(reference["episodeId"])) or not scene or scene["gameId"] != game or scene["episodeId"] != reference["episodeId"] or scene["id"] != reference["sceneId"]:
                    raise ValueError("Scene revision not found")
                creation = dict(creation, title=creation.get("title") or scene["name"], brief=creation.get("brief") or scene["name"])
            for key in creation["sourceKeys"] + creation["contextKeys"]:
                if not key.startswith(f"games/{game}/assets/"):
                    raise ValueError("Choose same-game sources")
                store.object(key)
            selected_map = store.pin_map(game, scene) if video else None
            identity_body = {**body, **({"selectedMap": selected_map} if selected_map else {})}
            identity = hashlib.sha256(json.dumps(identity_body, sort_keys=True).encode()).hexdigest()
            job = store.get("editorial", identity)
            if not job:
                job = store.prepare_editorial_job({"jobId": identity, "gameId": game, "creation": creation, "createdAt": int(time.time()), "videoGenerationAuthorized": False, **({"selectedScene": scene, **({"selectedMap": selected_map} if selected_map else {})} if video else {})})
            store.put("editorial", identity, job, game)
            return self.send(job)
        if path == "/tags":
            return self.send(store.create_tag(body))
        if path == "/tags/manage":
            return self.send(store.manage_tag(body))
        if path == "/assets/delete":
            return self.send(store.delete_asset(body))
        if path == "/novel-review":
            return self.send(store.review_chapter(body))
        if path == "/novel-chapters":
            game, operation = body["gameId"], body["operationId"]
            store.game(game)
            if not re.fullmatch(r"[a-f0-9]{32}", operation) or not body["title"].strip() or not body["markdown"].strip():
                raise ValueError("Enter a title and chapter text")
            if len(body["title"]) > 160 or len(body["markdown"]) > 100000 or len(body["sourceKeys"]) > 20:
                raise ValueError("Chapter exceeds allowed size")
            for key in body["sourceKeys"]:
                if not key.startswith(f"games/{game}/assets/"):
                    raise ValueError("Choose same-game references")
                store.object(key)
            previous = store.get("chapter", body["previousChapterId"]) if body["previousChapterId"] else None
            if body["previousChapterId"] and (not previous or previous["gameId"] != game):
                raise LookupError("Previous chapter not found")
            identity = hashlib.sha256((game + ":" + operation).encode()).hexdigest()
            key = f"games/{game}/assets/chapter-{identity[:32]}/original/chapter.json"
            now = int(time.time())
            series_id, version = identity, 1
            if previous and previous.get("details", {}).get("authorship") == "human":
                _, earlier_raw = store.object(previous["assetKey"])
                earlier = json.loads(earlier_raw)
                if earlier.get("entityType") != "UserChapter" or earlier.get("gameId") != game or earlier.get("chapterId") != previous["id"] or type(earlier.get("version")) is not int:
                    raise ValueError("The earlier chapter version could not be verified")
                series_id, version = earlier["seriesId"], earlier["version"] + 1
            chapter = {"id": identity, "gameId": game, "sessionId": "chapter-" + identity[:24], "assetKey": key, "title": body["title"].strip(), "markdown": body["markdown"].strip(), "createdAt": now, "publishedAt": now, "publicationStatus": "human-authored", "reviewStatus": "not-reviewed", "notice": "", "readerReferences": None, "details": {"authorship": "human", "previousChapterId": body["previousChapterId"], "review": {}, "revisionHistory": [], "sourceKeys": body["sourceKeys"], "artifact": {"key": key}}}
            chapter.update(seriesId=series_id, version=version, sessionId="chapter-" + series_id[:24])
            raw = json.dumps({"schemaVersion": 1, "entityType": "UserChapter", "gameId": game, "chapterId": identity, "seriesId": series_id, "version": version, "title": chapter["title"], "markdown": chapter["markdown"], "sourceKeys": body["sourceKeys"], "previousChapterId": body["previousChapterId"]}).encode()
            previous_key = previous.get("assetKey") or previous.get("details", {}).get("artifact", {}).get("key") if previous else None
            lineage = list(dict.fromkeys([*body["sourceKeys"], *([previous_key] if previous_key else [])]))
            meta = {"kind": "novel-chapter", "contentType": "application/json", "title": chapter["title"], "sourceKeys": lineage}
            with store.connect() as db:
                saved = db.execute("SELECT payload,response FROM operations WHERE id=?", (operation,)).fetchone()
                if saved:
                    if json.loads(saved[0]) != body:
                        raise FileExistsError("Operation reused with different chapter")
                    return self.send(json.loads(saved[1]))
                response = {"chapterId": identity, "assetKey": key}
                db.execute("INSERT INTO objects VALUES (?,?,?,?,?)", (key, game, json.dumps(meta), raw, datetime.now(timezone.utc).isoformat()))
                db.execute("INSERT INTO records VALUES ('chapter',?,?,?)", (identity, game, json.dumps(chapter)))
                db.execute("INSERT INTO operations VALUES (?,?,?)", (operation, json.dumps(body), json.dumps(response)))
            return self.send(response, status=201)
        if path == "/transcript-summaries":
            return self.send(store.submit_transcript_summary(body))
        if path.startswith("/transcript-summaries/"):
            return self.send({"error": "This summary operation is unavailable. Your transcript is saved."}, status=501)
        if path == "/asset-generation":
            return self.send(store.submit_asset_generation(body))
        if path == "/assets/rename":
            return self.send(store.rename_asset(body))
        if path.startswith("/asset-generation/"):
            return self.send({"error": "This generation operation is unavailable. Your request is saved."}, status=501)
        if path == "/uploads":
            key = store.upload_request(body)
            identity = uuid.uuid4().hex
            store.put("upload", identity, body, body["gameId"])
            return self.send({"key": key, "url": self.origin + "/development/upload/" + identity, "headers": {"Content-Type": body["contentType"], "x-amz-checksum-sha256": body["sha256"], "If-None-Match": "*"}})
        if path == "/narration-jobs":
            return self.send(store.generation_job_view(store.submit_narration(body), "narration"))
        if path == "/episode-renders":
            return self.send(store.generation_job_view(store.submit_episode_render(body), "episode-render"))
        if path == "/scene-renders":
            return self.send(store.generation_job_view(store.submit_scene_render(body), "scene-render"))
        if path == "/browser-recording/live-session":
            from dev_live_transcription import create
            return self.send(create(store, body))
        if path == "/browser-recording/live-events":
            from dev_live_transcription import save_events
            return self.send(save_events(store, body))
        if path == "/browser-transcriptions":
            return self.send(store.submit_transcription(body))
        if path == "/browser-recording/complete":
            job = store.browser_playback_job(body["gameId"], body["recordingKey"], body["manifestSha256"])
            existing = store.get("playback", job["jobId"])
            if not existing:
                store.put("playback", job["jobId"], job, body["gameId"])
            return self.send({"jobId": job["jobId"], "workflowVersion": 2})
        return self.send({"error": "This operation requires the live Panther service."}, status=501)

    def do_PUT(self):
        if self.headers.get("Origin") not in (None, self.origin):
            return self.send({"error": "Same-origin requests required"}, status=403)
        store = self.server.store
        upload = store.get("upload", self.path.rsplit("/", 1)[-1])
        if not upload:
            return self.send({"error": "Upload not found"}, status=404)
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 <= size <= 100 * 1024**2 or size != upload["size"]:
            return self.send({"error": "Invalid upload size"}, status=400)
        raw = self.rfile.read(size)
        if len(raw) != size or base64.b64encode(hashlib.sha256(raw).digest()).decode() != upload["sha256"]:
            return self.send({"error": "Upload checksum mismatch"}, status=400)
        key = f"games/{upload['gameId']}/assets/{upload['assetId']}/original/{upload['filename']}"
        production_asset_views()
        import asset_metadata
        metadata = asset_metadata.defaults(upload["kind"], upload.get("metadata", {}), upload["filename"], upload["contentType"], key)
        meta = {**metadata, "kind": upload["kind"], "contentType": upload["contentType"]}
        try:
            with store.connect() as db:
                db.execute("INSERT INTO objects VALUES (?,?,?,?,?)", (key, upload["gameId"], json.dumps(meta), raw, datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError:
            return self.send({"error": "Asset already exists"}, status=412)
        self.send({})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path.home() / ".local/state/panther/development.sqlite")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--seed", action="store_true", help="Explicitly populate demonstration records in the database")
    args = parser.parse_args()
    store = Store(args.database)
    if args.seed:
        store.seed()
    server = Server(("127.0.0.1", args.port), store)
    print(f"Panther development: http://127.0.0.1:{server.server_port}/account", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
