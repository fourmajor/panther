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
import time
from urllib.parse import parse_qs, urlparse
import uuid

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web/media-explorer"
STYLES = ["photorealistic", "anime", "illustrated-fantasy", "comic-book", "watercolor", "oil-painting", "stylized-3d", "pixel-art"]


def details():
    return {"schemaVersion": 1, "aliases": [], "pronouns": None, "role": None, "status": None, "overview": None, "subtitle": None, "backstory": None, "notes": None, "statistics": [], "relationships": [], "thumbnailAssetKey": None}


class Store:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        if self.path.is_relative_to(ROOT):
            raise ValueError("Keep the development database outside the repository")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, game TEXT, payload TEXT, PRIMARY KEY(kind,id)); CREATE TABLE IF NOT EXISTS objects (key TEXT PRIMARY KEY, game TEXT, metadata TEXT, data BLOB, created TEXT); CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, payload TEXT, response TEXT);")
        self.path.chmod(0o600)

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
        return {"game": {k: v for k, v in record.items() if k not in ("description", "descriptionRevision")}, "gameSettings": {k: record.get(k) for k in ("description", "descriptionRevision")}, "canEditGame": True, "visualStyles": [{"id": v, "label": v.replace("-", " ").title()} for v in STYLES], "players": self.list("player", identity), "memberships": self.list("membership", identity), "characters": self.list("character", identity)}

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
        expected_fields = {"gameId", "id", "name", "description", "expectedRevision", "operationId"} | ({"episodeId", "type"} if kind == "scene" else set())
        if set(body) != expected_fields:
            raise ValueError("Invalid episode or scene edit")
        if kind not in ("episode", "scene") or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identity) or not re.fullmatch(r"[a-f0-9]{32}", operation):
            raise ValueError("Invalid episode, scene or operation ID")
        if not isinstance(body.get("name"), str) or not 1 <= len(body["name"].strip()) <= 160 or not isinstance(body.get("description", ""), str) or len(body.get("description", "")) > 4000:
            raise ValueError("Enter a title and a description under 4000 characters")
        episode_id = body.get("episodeId") if kind == "scene" else None
        if kind == "scene" and (not isinstance(episode_id, str) or not self.get("episode", game + ":" + episode_id) or body.get("type") not in {"general", "opener", "travel", "action", "dialogue"}):
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
            record = {"schemaVersion": 1, "entityType": "Episode" if kind == "episode" else "Scene", "gameId": game, "id": identity, "name": body["name"].strip(), "description": body.get("description", "").strip(), "revision": uuid.uuid4().hex, "updatedAt": datetime.now(timezone.utc).isoformat()}
            record["createdAt"] = previous["createdAt"] if previous else record["updatedAt"]
            if kind == "episode":
                record["position"] = previous["position"] if previous else int(time.time() * 1000)
            if kind == "scene":
                count = db.execute("SELECT count(*) FROM records WHERE kind='scene' AND game=? AND json_extract(payload,'$.episodeId')=?", (game, episode_id)).fetchone()[0]
                record.update(episodeId=episode_id, type=body["type"], position=previous["position"] if previous else count)
            db.execute("INSERT INTO records VALUES (?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload", (kind, key, game, json.dumps(record)))
            history = {"record": record, "previousRecord": previous, "recordedAt": record["updatedAt"]}
            db.execute("INSERT INTO records VALUES (?,?,?,?)", (kind + "-history", key + ":" + record["revision"], game, json.dumps(history)))
            response = {"record": record}
            db.execute("INSERT INTO operations VALUES (?,?,?)", (operation, kind + ":" + payload, json.dumps(response)))
        return response

    def objects(self, game):
        with self.connect() as db:
            rows = db.execute("SELECT key,metadata,length(data),created FROM objects WHERE game=? ORDER BY created DESC", (game,)).fetchall()
        return [{"key": key, "name": key.rsplit("/", 1)[-1], "metadata": json.loads(meta), "contentType": json.loads(meta).get("contentType", "application/octet-stream"), "kind": json.loads(meta).get("kind", "other"), "size": size, "lastModified": created} for key, meta, size, created in rows]

    def object(self, key):
        with self.connect() as db:
            row = db.execute("SELECT metadata,data FROM objects WHERE key=?", (key,)).fetchone()
        if not row:
            raise LookupError("Asset not found")
        return json.loads(row[0]), row[1]


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
            elif path == "/game":
                result = store.game(game)
            elif path == "/dashboard-recent":
                assets = store.objects(game)
                groups = {"characters": store.list("character", game), "transcripts": [a for a in assets if "transcript" in a["kind"]], "videos": [a for a in assets if a["contentType"].startswith("video/")], "chapters": store.list("chapter", game)}
                for values in groups.values():
                    values.sort(key=lambda value: str(value.get("updatedAt", value.get("publishedAt", value.get("lastModified", "")))), reverse=True)
                result = {"complete": True, "groups": {k: v[:5] for k, v in groups.items()}, "counts": {k: len(v) for k, v in groups.items()}}
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
                result = {"assets": [a for a in assets if section == "all" or section == "audio" and a["contentType"].startswith("audio/") or section == "transcripts" and "transcript" in a["kind"] or section == "videos" and a["contentType"].startswith("video/") or section == "images" and a["contentType"].startswith("image/")], "cursor": None}
            elif path == "/objects":
                prefix = q["prefix"]
                game = prefix.split("/")[1]
                assets = [a for a in store.objects(game) if a["key"].startswith(prefix)]
                result = {"objects": [a for a in assets if "/" not in a["key"][len(prefix):]], "prefixes": sorted({prefix + a["key"][len(prefix):].split("/")[0] + "/" for a in assets if "/" in a["key"][len(prefix):]}), "nextCursor": None}
            elif path == "/asset-document":
                meta, raw = store.object(q["key"])
                result = {"key": q["key"], "kind": meta.get("kind", "other"), "metadata": meta, "document": json.loads(raw)}
            elif path == "/object-url":
                meta, raw = store.object(q["key"])
                result = {"url": self.origin + "/development/object?key=" + q["key"], "size": len(raw), "metadata": meta, "expiresIn": None, "contentType": meta.get("contentType", "application/octet-stream")}
            elif path == "/browser-recording/capabilities":
                result = {"canRecord": True, "transcriptionAvailable": False, "model": "gpt-transcribe", "chunkSeconds": 15, "maxParts": 1000}
            elif path == "/browser-transcriptions":
                job = store.get("playback", q.get("playbackJobId", ""))
                result = {"jobs": [], "transcriptKey": None, **({"playback": job} if job else {})}
            elif path == "/novel":
                result = {"chapters": store.list("chapter", game), "cursor": None}
            elif path == "/novel-chapter":
                result = store.get("chapter", q["chapterId"])
                if not result or result["gameId"] != game:
                    raise LookupError("Chapter not found")
            elif path == "/editorial-jobs":
                result = {"jobs": store.list("editorial", game), "cursor": None} if "jobId" not in q else {"job": store.get("editorial", q["jobId"]), "tasks": []}
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
            if not video and (creation.get("schemaVersion") != 1 or creation.get("target") != "novel" or not 1 <= len(creation["sourceKeys"]) <= 8):
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
            identity = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            job = store.get("editorial", identity) or {"jobId": identity, "gameId": game, "creation": creation, "workflowVersion": 4 if video else 3, "status": "SUBMITTED", "createdAt": int(time.time()), "videoGenerationAuthorized": False, **({"selectedScene": scene, "sourceMode": "transcript" if creation["sourceKeys"] else "prompt"} if video else {})}
            store.put("editorial", identity, job, game)
            return self.send(job)
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
            chapter = {"id": identity, "gameId": game, "sessionId": "chapter-" + identity[:24], "assetKey": key, "title": body["title"].strip(), "markdown": body["markdown"].strip(), "createdAt": now, "publishedAt": now, "publicationStatus": "human-authored", "reviewStatus": "not-reviewed", "notice": "", "readerReferences": None, "details": {"authorship": "human", "previousChapterId": body["previousChapterId"], "review": {}, "revisionHistory": [], "sourceKeys": body["sourceKeys"], "artifact": {"key": key}}}
            raw = json.dumps({"schemaVersion": 1, "entityType": "UserChapter", "gameId": game, "chapterId": identity, "seriesId": previous.get("seriesId", previous["id"]) if previous else identity, "version": previous.get("version", 1) + 1 if previous else 1, "title": chapter["title"], "markdown": chapter["markdown"], "sourceKeys": body["sourceKeys"], "previousChapterId": body["previousChapterId"]}).encode()
            meta = {"kind": "novel-chapter", "contentType": "application/json", "title": chapter["title"], "sourceKeys": body["sourceKeys"]}
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
        if path == "/uploads":
            identity = uuid.uuid4().hex
            store.put("upload", identity, body, body["gameId"])
            return self.send({"url": self.origin + "/development/upload/" + identity, "headers": {"Content-Type": body["contentType"]}})
        if path == "/browser-recording/complete":
            meta, raw = store.object(body["recordingKey"])
            doc = json.loads(raw)
            for part in doc["parts"]:
                _, audio = store.object(body["recordingKey"].rsplit("/", 1)[0] + "/" + part["file"])
                if hashlib.sha256(audio).hexdigest() != part["sha256"]:
                    raise ValueError("Audio checksum mismatch")
            identity = hashlib.sha256(raw).hexdigest()
            # Source recording is durable. Real derivatives need the laptop playback worker.
            store.put("playback", identity, {"status": "SUBMITTED"}, body["gameId"])
            return self.send({"jobId": identity, "workflowVersion": 2})
        return self.send({"error": "This operation requires the live Panther service."}, status=501)

    def do_PUT(self):
        if self.headers.get("Origin") not in (None, self.origin):
            return self.send({"error": "Same-origin requests required"}, status=403)
        store = self.server.store
        upload = store.get("upload", self.path.rsplit("/", 1)[-1])
        if not upload:
            return self.send({"error": "Upload not found"}, status=404)
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 25 * 1024**2:
            return self.send({"error": "Invalid upload size"}, status=400)
        raw = self.rfile.read(size)
        key = f"games/{upload['gameId']}/assets/{upload['assetId']}/original/{upload['filename']}"
        meta = {**upload.get("metadata", {}), "kind": upload["kind"], "contentType": upload["contentType"]}
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
