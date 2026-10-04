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
from dev_asset_title import ensure_title  # noqa: E402
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


def metadata(job, key, kind, mime, sources, evidence, model, request=None, response=None, dimensions=None):
    is_fal = (request or {}).get("provider") == "fal"
    result = asset_metadata.defaults(kind, {"kind": kind, "contentType": mime, "title": job["name"],
        "characterIds": job.get("characterIds") or ([job["characterId"]] if job.get("characterId") else []), "sourceKeys": sources,
        "extra": {"artifactType": kind, "jobId": job["jobId"], **({"titleGeneration": job["titleGeneration"]} if job.get("titleGeneration") else {}), "generation": {"schemaVersion": 1, "method": "ai",
                  "provider": "fal" if is_fal else "OpenAI", "model": model, "inference": "remote", "execution": "local", "tool": "fal queue API" if is_fal else "OpenAI Images API",
                  "cost": {"status": "unknown"}, "evidence": evidence}}}, key.rsplit("/", 1)[-1], mime, key)
    from panther_journal import cost_estimates
    result = cost_estimates.annotate(result, request, response)
    if is_fal:
        result['extra']['endpoint'] = model
        result['extra']['requestId'] = job.get('requestId')
        price = job.get('modelContract', {}).get('priceEstimate')
        if price and kind != 'image-provenance' and dimensions:
            estimate = cost_estimates.fal_image(price, *dimensions)
            if estimate:
                result['extra']['costEstimate'] = estimate
    asset_metadata.validate_generation(result["extra"]["generation"])
    storage_layout.location(key, kind, result)
    return result


def publish(store, job, response, request, *, raw_image=None):
    from PIL import Image
    if raw_image is None:
        if not isinstance(response.get("data"), list) or len(response["data"]) != 1:
            raise ValueError("The image provider returned no complete image.")
        raw = base64.b64decode(response["data"][0]["b64_json"], validate=True)
    else:
        raw = raw_image
    if len(raw) > 100 * 1024**2:
        raise ValueError("Generated image exceeds the upload limit.")
    with Image.open(BytesIO(raw)) as image:
        formats = {'PNG': ('png', 'image/png'), 'JPEG': ('jpg', 'image/jpeg'), 'WEBP': ('webp', 'image/webp')}
        if image.format not in formats or (raw_image is None and image.format != 'PNG'):
            raise ValueError("The image provider returned an unexpected format.")
        extension, image_mime = formats[image.format]
        dimensions = (image.width, image.height)
        image.verify()
    prefix = f"games/{job['gameId']}/assets/generated-{job['jobId'][:32]}/original/"
    request_key, response_key, image_key = [prefix + name for name in ("generation-request.json", "provider-response.json", "image." + extension)]
    reference_key = prefix + "character-reference.json" if job.get("characterReference") else None
    model = request["endpoint"] if request.get("provider") == "fal" else response.get("model") or request["model"]
    entries = [(request_key, "image-provenance", "application/json", json.dumps(request).encode(), [reference_key] if reference_key else []),
               (response_key, "image-provenance", "application/json", json.dumps(response).encode(), [request_key]),
               (image_key, job["type"], image_mime, raw, [request_key, response_key])]
    if reference_key:
        entries.insert(0, (reference_key, "image-provenance", "application/json", json.dumps(job["characterReference"]).encode(), []))
    updated = {**job, "status": "PUBLISHED", "assetKey": image_key, "publishedAt": now(), "message": None,
               "providerRequestId": job.get("requestId") if request.get("provider") == "fal" else response.get("_request_id"), "costStatus": "unknown", "model": model}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for key, kind, mime, content, sources in entries:
            meta = metadata(job, key, kind, mime, sources, response_key, model, request, response, dimensions)
            if kind == "image-provenance":
                meta["extra"]["relationshipRole"] = "intermediate"
            existing = db.execute("SELECT data FROM objects WHERE key=?", (key,)).fetchone()
            if existing and existing[0] != content:
                raise ValueError("Image publication collision; refusing overwrite.")
            if not existing:
                db.execute("INSERT INTO objects VALUES (?,?,?,?,?)", (key, job["gameId"], json.dumps(meta), content, now()))
        if reference_key and job.get("selectAsPortrait") is True:
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


def process(store, identity, root, client, model, *, fal=None, downloader=None):
    job = store.get("asset-generation", identity)
    # Revalidate a completed title after a contract repair. There must be no
    # evidence of any media dispatch; neither title inference nor media is retried.
    folder = root / identity
    retained_title = bool(job and job.get('status') == 'ATTENTION' and job.get('titlePhase') == 'GENERATING'
        and not job.get('outcomeUnknown') and not job.get('requestId') and not job.get('dispatchStarted')
        and (folder / 'title-response.json').is_file()
        and not any((folder / name).exists() for name in ('request.json', 'submission.json', 'provider-response.json')))
    if not job or job.get("mediaType", "image") != "image" or (job.get("status") not in {"QUEUED", "GENERATING", "SUBMITTED", "IN_QUEUE", "IN_PROGRESS"} and not retained_title):
        return False
    try:
        if not re.fullmatch(r"[a-f0-9]{64}", identity) or job.get("generationAuthorized") is not True or job.get("type") not in {"image", "map", "blueprint", "location", "portrait"}:
            raise ValueError("Invalid or unauthorized image request.")
        store.game(job["gameId"])
        folder = private_root(root) / identity
        folder.mkdir(mode=0o700, exist_ok=True)
        if folder.is_symlink():
            raise ValueError("Symlinked image checkpoint rejected.")
        ensure_title(store, "asset-generation", identity, job, folder, client)
        model = job.get("model", model)
        if job.get('provider') == 'fal':
            return process_fal(store, identity, job, folder, fal, downloader)
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


def download_fal_image(url, target):
    from dev_video_worker import download
    download(url, target)  # Approved delivery hosts, no credentials/redirects, bounded response.


def process_fal(store, identity, job, folder, fal, downloader=None):
    from panther_journal import video as v
    downloader = downloader or download_fal_image
    request_file, submission_file, response_file, image_file = [folder / name for name in ('request.json', 'submission.json', 'provider-response.json', 'image-original')]
    for file in (request_file, submission_file, response_file, image_file):
        if file.is_symlink():
            raise ValueError('Symlinked image checkpoint rejected')
    try:
        pinned = job['modelContract']
        endpoint = pinned['endpoint']
        if endpoint != job['model'] or pinned.get('provider') != 'fal' or pinned.get('schemaVersion') != 1:
            raise ValueError('Selected image model contract mismatch')
        expected = {'provider': 'fal', 'endpoint': endpoint, 'model': endpoint, 'payload': {**pinned['defaults'], 'prompt': request_for(job, endpoint)['prompt']}, 'contractHash': pinned['schemaHash']}
        if request_file.exists():
            request = json.loads(request_file.read_bytes())
            if request != expected or request.get('endpoint') != endpoint or request.get('contractHash') != pinned['schemaHash']:
                raise ValueError('Pinned image request changed')
        else:
            request = expected
            retain(request_file, json.dumps(request).encode())
        if not response_file.exists():
            if fal is None:
                raise ValueError('fal generation is not configured')
            if not job.get('requestId'):
                if submission_file.exists():
                    submission = json.loads(submission_file.read_bytes())
                else:
                    if job.get('dispatchStarted'):
                        job['outcomeUnknown'] = True
                        raise ValueError('Image submission outcome unknown; no automatic paid retry')
                    job.update(status='GENERATING', dispatchStarted=now(), outcomeUnknown=True)
                    store.put('asset-generation', identity, job, job['gameId'])
                    submission = fal.request('POST', v.QUEUE + '/' + endpoint, json=request['payload'], headers={'X-Fal-No-Retry': '1', 'X-Fal-Disable-Fallback': 'true', 'X-Fal-Store-IO': '0'})
                    retain(submission_file, json.dumps(submission).encode())
                rid = submission.get('request_id')
                if not isinstance(rid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', rid):
                    raise ValueError('Image submission identity unknown')
                job.update(requestId=rid, status='SUBMITTED', outcomeUnknown=False)
                store.put('asset-generation', identity, job, job['gameId'])
                job['urls'] = {kind: v.queue_url(submission[kind + '_url'], rid, endpoint, kind) for kind in ('status', 'response')}
                store.put('asset-generation', identity, job, job['gameId'])
            rid = job['requestId']
            if not job.get('urls') and submission_file.exists():
                submission = json.loads(submission_file.read_bytes())
                job['urls'] = {kind: v.queue_url(submission[kind + '_url'], rid, endpoint, kind) for kind in ('status', 'response')}
                store.put('asset-generation', identity, job, job['gameId'])
            try:
                status = fal.request('GET', v.queue_url(job['urls']['status'], rid, endpoint, 'status'))
            except Exception:
                job.update(status='SUBMITTED', message='Provider status is temporarily unavailable. Checking again.', updatedAt=time.time())
                store.put('asset-generation', identity, job, job['gameId'])
                return False
            if status.get('request_id') not in {None, rid}:
                raise ValueError('Image queue identity mismatch')
            if status.get('status') in {'IN_QUEUE', 'IN_PROGRESS'}:
                job.update(status=status['status'], updatedAt=time.time(), message=None)
                store.put('asset-generation', identity, job, job['gameId'])
                return False
            if status.get('status') != 'COMPLETED':
                raise ValueError('Unknown image queue state')
            response = fal.request('GET', v.queue_url(job['urls']['response'], rid, endpoint, 'response'), completed_result=True)
            retain(response_file, json.dumps(response).encode())
        response = json.loads(response_file.read_bytes())
        outputs = response.get('images') if pinned['outputShape'] == 'images' else [response.get('image')]
        if not isinstance(outputs, list) or len(outputs) != 1 or not isinstance(outputs[0], dict):
            raise ValueError('Provider did not return one complete image')
        source_url = v.media_url(outputs[0]['url'])
        if not image_file.exists():
            downloader(source_url, image_file)
        publish(store, job, response, request, raw_image=image_file.read_bytes())
        return True
    except Exception as error:
        import click
        code = getattr(error, 'status_code', None)
        if isinstance(error, click.ClickException):
            matched = re.fullmatch(r'fal returned HTTP (\d{3}); no automatic retry was made\.', str(error))
            if matched:
                code = int(matched[1])
        if code in {400, 401, 403, 422, 429} and not job.get('requestId'):
            job.update(errorCode=code, outcomeUnknown=False)
        # Provider request methods sanitize HTTP failures. Unknown third-party
        # exceptions can contain URLs/credentials, so retain type without raw text.
        diagnostic = str(error) if isinstance(error, click.ClickException) or type(error) is ValueError else 'Image worker failed at ' + type(error).__name__
        try:
            retain(folder / f'worker-error-{time.time_ns()}.json', json.dumps({'type': type(error).__name__, 'message': diagnostic, 'errorCode': code, 'requestId': job.get('requestId'), 'billingStatus': 'unknown'}).encode())
        except (OSError, ValueError):
            pass
        if response_file.is_file() and not response_file.is_symlink():
            job.update(publicationRecoveryAvailable=True, outcomeUnknown=False)
        job.update(status='ATTENTION', message='Image generation could not be confirmed.' if job.get('outcomeUnknown') else 'Image generation is unavailable.', updatedAt=time.time())
        store.put('asset-generation', identity, job, job['gameId'])
        return False


def run(database, work_dir, *, key_file=None, env_file=None, model="gpt-image-2", once=False, client=None, fal=None):
    os.umask(0o077)
    store, root = Store(database), private_root(work_dir)
    configured_client = client is None
    try:
        if client is None:
            from openai import OpenAI
            key = load_key(key_file, env_file)
            model = os.environ.get("PANTHER_IMAGE_MODEL", model)
            client = OpenAI(api_key=key, max_retries=0, timeout=600)
    except Exception:
        store.put("service", "images", {"status": "BLOCKED", "updatedAt": time.time(), "message": "Image generation is unavailable. Check the server configuration."})
        raise
    if configured_client and fal is None:
        try:
            from dev_video_worker import Fal
            fal = Fal(env_file)
        except ValueError:
            fal = None
    with store.path.with_name(store.path.name + ".images.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        migrate_legacy(store)
        # Restarting can safely finish publication of a retained provider receipt;
        # it never issues another inference request for that job.
        for job in store.list("asset-generation"):
            if job.get("mediaType", "image") == "image" and job.get("status") == "ATTENTION" and job.get("publicationRecoveryAvailable"):
                receipt = root / job["jobId"] / "provider-response.json"
                if receipt.is_file() and not receipt.is_symlink():
                    store.put("asset-generation", job["jobId"], {**job, "status": "GENERATING", "message": None}, job["gameId"])
        stop = threading.Event()
        def pulse():
            while not stop.is_set():
                store.put("service", "images", {"status": "RUNNING", "updatedAt": time.time(), "model": model, "falAvailable": fal is not None})
                stop.wait(10)
        thread = threading.Thread(target=pulse, daemon=True)
        thread.start()
        def discover():
            from dev_fal_image_catalog import refresh
            while not stop.is_set():
                try:
                    refresh(store, fal)
                except Exception:
                    store.put('model-catalog-health', 'fal-text-to-image-v1', {'status': 'UNAVAILABLE', 'updatedAt': time.time()})
                stop.wait(21600)
        catalog_thread = threading.Thread(target=discover, daemon=True) if fal is not None else None
        if catalog_thread:
            catalog_thread.start()
        try:
            while True:
                for job in reversed(store.list("asset-generation")):
                    process(store, job["jobId"], root, client, model, fal=fal)
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
    parser.add_argument("--model", default="gpt-image-2")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    run(args.database, args.work_dir, key_file=args.api_key_file, env_file=args.env_file, model=args.model, once=args.once)
