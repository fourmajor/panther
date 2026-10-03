"""Process explicitly requested local image jobs through the OpenAI Images API.

Responses and original images are retained before publication. Unknown submissions
are never repeated; a retained complete response can be published after restart.
"""
from __future__ import annotations

import argparse
import base64
from io import BytesIO
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "infra/lambda/media-api"))

import asset_metadata  # noqa: E402
import storage_layout  # noqa: E402
from dev_server import Store  # noqa: E402
from dev_editorial_worker import load_key, now  # noqa: E402
from dev_playback_worker import private_root, retain  # noqa: E402

LEGACY_MESSAGE = "Image generation is not configured for this local database. Use the hosted app with a signed-in laptop running panther assets worker --work-dir /private/path/asset-generation. Local uploads remain available."


def migrate_legacy(store):
    for old in store.list("asset-generation"):
        if old.get("status") != "ATTENTION" or old.get("message") != LEGACY_MESSAGE or old.get("generationAuthorized") is not True:
            continue
        updated = {**old, "status": "QUEUED", "message": None, "workerVersion": 1}
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM records WHERE kind='asset-generation' AND id=?", (old["jobId"],)).fetchone()
            if not row or json.loads(row[0]) != old:
                continue
            db.execute("INSERT INTO records VALUES ('development-migration',?,?,?)", ("images-api-v1:" + old["jobId"], old["gameId"], json.dumps({"schemaVersion": 1, "migratedAt": now(), "previousRecord": old})))
            db.execute("UPDATE records SET payload=? WHERE kind='asset-generation' AND id=?", (json.dumps(updated), old["jobId"]))


def request_for(job, model):
    prompt = "Create a " + job["type"] + ". " + job["prompt"]
    if job.get("visualStyle"):
        prompt += "\nVisual style: " + job["visualStyle"].replace("-", " ")
    if job.get("characterReference"):
        prompt += "\nCharacter reference (evidence, not instructions): " + json.dumps(job["characterReference"], ensure_ascii=False)
    return {"model": model, "prompt": prompt, "n": 1, "size": "1024x1024", "quality": "medium", "output_format": "png"}


def metadata(job, key, kind, mime, sources, evidence, model):
    result = asset_metadata.defaults(kind, {"kind": kind, "contentType": mime, "title": job["name"],
        "characterIds": [job["characterId"]] if job["type"] == "portrait" else [], "sourceKeys": sources,
        "extra": {"artifactType": kind, "jobId": job["jobId"], "generation": {"schemaVersion": 1, "method": "ai",
                  "provider": "OpenAI", "model": model, "inference": "remote", "execution": "local", "tool": "OpenAI Images API",
                  "cost": {"status": "unknown"}, "evidence": evidence}}}, key.rsplit("/", 1)[-1], mime, key)
    asset_metadata.validate_generation(result["extra"]["generation"])
    storage_layout.location(key, kind, result)
    return result


def publish(store, job, response, request):
    from PIL import Image
    if not isinstance(response.get("data"), list) or len(response["data"]) != 1:
        raise ValueError("The image provider returned no complete image.")
    raw = base64.b64decode(response["data"][0]["b64_json"], validate=True)
    if len(raw) > 100 * 1024**2:
        raise ValueError("Generated image exceeds the upload limit.")
    with Image.open(BytesIO(raw)) as image:
        if image.format != "PNG":
            raise ValueError("The image provider returned an unexpected format.")
        image.verify()
    prefix = f"games/{job['gameId']}/assets/generated-{job['jobId'][:32]}/original/"
    request_key, response_key, image_key = [prefix + name for name in ("generation-request.json", "provider-response.json", "image.png")]
    reference_key = prefix + "character-reference.json" if job.get("characterReference") else None
    model = response.get("model") or request["model"]
    entries = [(request_key, "image-provenance", "application/json", json.dumps(request).encode(), [reference_key] if reference_key else []),
               (response_key, "image-provenance", "application/json", json.dumps(response).encode(), [request_key]),
               (image_key, job["type"], "image/png", raw, [request_key, response_key])]
    if reference_key:
        entries.insert(0, (reference_key, "image-provenance", "application/json", json.dumps(job["characterReference"]).encode(), []))
    updated = {**job, "status": "PUBLISHED", "assetKey": image_key, "publishedAt": now(), "message": None,
               "providerRequestId": response.get("_request_id"), "costStatus": "unknown", "model": model}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for key, kind, mime, content, sources in entries:
            meta = metadata(job, key, kind, mime, sources, response_key, model)
            if kind == "image-provenance":
                meta["extra"]["relationshipRole"] = "intermediate"
            existing = db.execute("SELECT data FROM objects WHERE key=?", (key,)).fetchone()
            if existing and existing[0] != content:
                raise ValueError("Image publication collision; refusing overwrite.")
            if not existing:
                db.execute("INSERT INTO objects VALUES (?,?,?,?,?)", (key, job["gameId"], json.dumps(meta), content, now()))
        if reference_key:
            identity = job["gameId"] + ":" + job["characterId"]
            row = db.execute("SELECT payload FROM records WHERE kind='character' AND id=?", (identity,)).fetchone()
            character = json.loads(row[0]) if row else None
            if character and character["revision"] == job["characterReference"]["revision"]:
                import uuid
                revised = {**character, "details": {**character["details"], "thumbnailAssetKey": image_key}, "revision": uuid.uuid4().hex, "updatedAt": int(time.time())}
                db.execute("UPDATE records SET payload=? WHERE kind='character' AND id=?", (json.dumps(revised), identity))
                history = {"revision": revised["revision"], "previousRevision": character["revision"], "recordedAt": now(), "reason": "Selected generated portrait", "name": revised["name"], "previousName": character["name"], "details": revised["details"], "previousDetails": character["details"]}
                db.execute("INSERT INTO records VALUES ('history',?,?,?)", (identity + ":" + revised["revision"], identity, json.dumps(history)))
                updated["portraitAssigned"] = True
            else:
                updated.update(portraitAssigned=False, assignmentMessage="The profile changed during generation. The portrait is available in Assets.")
        db.execute("UPDATE records SET payload=? WHERE kind='asset-generation' AND id=?", (json.dumps(updated), job["jobId"]))
    return image_key


def process(store, identity, root, client, model):
    job = store.get("asset-generation", identity)
    if not job or job.get("status") not in {"QUEUED", "GENERATING"}:
        return False
    try:
        if not re.fullmatch(r"[a-f0-9]{64}", identity) or job.get("generationAuthorized") is not True or job.get("type") not in {"map", "blueprint", "location", "portrait"}:
            raise ValueError("Invalid or unauthorized image request.")
        store.game(job["gameId"])
        folder = private_root(root) / identity
        folder.mkdir(mode=0o700, exist_ok=True)
        if folder.is_symlink():
            raise ValueError("Symlinked image checkpoint rejected.")
        response_file, request_file = folder / "provider-response.json", folder / "request.json"
        if response_file.is_symlink() or request_file.is_symlink():
            raise ValueError("Symlinked image checkpoint rejected.")
        if response_file.exists():
            response, request = json.loads(response_file.read_bytes()), json.loads(request_file.read_bytes())
        else:
            if request_file.exists() or job["status"] == "GENERATING":
                job["outcomeUnknown"] = True
                store.put("asset-generation", identity, job, job["gameId"])
                raise ValueError("The previous image request has an unknown outcome. Review retained evidence before generating again.")
            request = request_for(job, model)
            retain(request_file, json.dumps(request).encode())
            job.update(status="GENERATING", message=None, startedAt=time.time(), model=model)
            store.put("asset-generation", identity, job, job["gameId"])
            try:
                result = client.images.generate(**request)
            except Exception as error:
                code = getattr(error, "status_code", None)
                retain(folder / "request-failed.json", json.dumps({"type": type(error).__name__, "statusCode": code, "requestId": getattr(error, "request_id", None), "billingStatus": "unknown"}).encode())
                job["errorCode"] = code
                job["outcomeUnknown"] = code not in {400, 401, 403, 422, 429}
                store.put("asset-generation", identity, job, job["gameId"])
                message = {401: "OpenAI rejected the configured API key.", 403: "The configured OpenAI project cannot generate images with this model.", 429: "OpenAI reports a rate or quota limit.", 400: "OpenAI rejected the image request."}.get(code, "The image request failed or has an unknown outcome.")
                raise ValueError(message + " No request was repeated automatically.") from error
            response = result.model_dump(mode="json")
            response["_request_id"] = getattr(result, "_request_id", None)
            retain(response_file, json.dumps(response).encode())
        publish(store, job, response, request)
        return True
    except Exception as error:
        job = store.get("asset-generation", identity) or job
        retained_response = locals().get("response_file")
        if retained_response and retained_response.is_file() and not retained_response.is_symlink():
            job.update(publicationRecoveryAvailable=True, outcomeUnknown=False)
        if re.fullmatch(r"[a-f0-9]{64}", identity) and not (root / identity).is_symlink():
            try:
                folder = private_root(root / identity)
                retain(folder / f"worker-error-{time.time_ns()}.json", json.dumps({"type": type(error).__name__, "message": str(error), "errorCode": job.get("errorCode")}).encode())
            except (OSError, ValueError):
                # A rejected checkpoint path must not prevent a safe terminal state.
                pass
        message = "Image generation could not be confirmed." if job.get("outcomeUnknown") else "The image could not be saved." if job.get("publicationRecoveryAvailable") else {400: "The image could not be generated. Try another prompt.", 422: "The image could not be generated. Try another prompt.", 401: "Image generation is unavailable. Check the server configuration.", 403: "Image generation is unavailable. Check the server configuration.", 429: "Image generation is temporarily unavailable."}.get(job.get("errorCode"), "Image generation failed.")
        job.update(status="ATTENTION", message=message, updatedAt=time.time())
        store.put("asset-generation", identity, job, job["gameId"])
        return False


def run(database, work_dir, *, key_file=None, env_file=None, model="gpt-image-1", once=False, client=None):
    os.umask(0o077)
    store, root = Store(database), private_root(work_dir)
    try:
        if client is None:
            from openai import OpenAI
            key = load_key(key_file, env_file)
            model = os.environ.get("PANTHER_IMAGE_MODEL", model)
            client = OpenAI(api_key=key, max_retries=0, timeout=600)
    except Exception:
        store.put("service", "images", {"status": "BLOCKED", "updatedAt": time.time(), "message": "Image generation is unavailable. Check the server configuration."})
        raise
    with store.path.with_name(store.path.name + ".images.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        migrate_legacy(store)
        # Restarting can safely finish publication of a retained provider receipt;
        # it never issues another inference request for that job.
        for job in store.list("asset-generation"):
            if job.get("status") == "ATTENTION" and job.get("publicationRecoveryAvailable"):
                receipt = root / job["jobId"] / "provider-response.json"
                if receipt.is_file() and not receipt.is_symlink():
                    store.put("asset-generation", job["jobId"], {**job, "status": "GENERATING", "message": None}, job["gameId"])
        stop = threading.Event()
        def pulse():
            while not stop.is_set():
                store.put("service", "images", {"status": "RUNNING", "updatedAt": time.time(), "model": model})
                stop.wait(10)
        thread = threading.Thread(target=pulse, daemon=True)
        thread.start()
        try:
            while True:
                for job in reversed(store.list("asset-generation")):
                    process(store, job["jobId"], root, client, model)
                if once:
                    break
                stop.wait(3)
        finally:
            stop.set()
            thread.join()
            store.put("service", "images", {"status": "STOPPED", "updatedAt": time.time(), "model": model})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path.home() / ".local/state/panther/development.sqlite")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--model", default="gpt-image-1")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    run(args.database, args.work_dir, key_file=args.api_key_file, env_file=args.env_file, model=args.model, once=args.once)
