"""Optional OpenAI browser transcription. Durable outbox, exact inputs, no paid retries."""

import base64
import hashlib
import io
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
import uuid
import wave
from datetime import datetime, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError
import access_policy
import asset_metadata
import index as media
import playback_jobs

TABLE = boto3.resource("dynamodb").Table(os.environ["BROWSER_TRANSCRIPTION_TABLE"])
SECRET = os.environ.get("OPENAI_TRANSCRIPTION_SECRET_ARN", "")
MODEL = "gpt-transcribe"
MAX_BYTES = 24_000_000


def reply(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(
            body, default=lambda value: float(value) if isinstance(value, Decimal) else str(value)
        ),
    }


def identity(game, recording):
    if not media._valid_slug(game) or not re.fullmatch(r"recording-[a-f0-9]{32}", recording or ""):
        raise ValueError("Invalid browser recording")
    return f"{game}#{recording}"


def read(pk, sk):
    return TABLE.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item")


def entries(pk, mode):
    result, args = (
        [],
        {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(mode.upper() + "#"),
            "ConsistentRead": True,
        },
    )
    while True:
        page = TABLE.query(**args)
        result.extend(page.get("Items", []))
        if not page.get("LastEvaluatedKey"):
            return sorted(result, key=lambda item: item["start"])
        args["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def public(job):
    return {
        k: job[k]
        for k in ("id", "mode", "status", "start", "end", "text", "assetKey", "error")
        if k in job
    }


def source(game, recording, key, actor=None):
    prefix = f"games/{game}/assets/{recording}/original/"
    if not re.fullmatch(re.escape(prefix) + r"part-[0-9]{4}\.wav", key or ""):
        raise ValueError("Expected browser source part")
    head = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=key, ChecksumMode="ENABLED")
    checksum = head.get("ChecksumSHA256")
    if not checksum or len(base64.b64decode(checksum, validate=True)) != 32:
        raise ValueError("Missing source checksum")
    ref = {"key": key, "size": head["ContentLength"], "sha256": checksum}
    metadata = json.loads(base64.b64decode(head["Metadata"]["panther"]))
    if actor and head["Metadata"].get("uploaded-by") != actor:
        raise ValueError("Only the capturing account can submit this audio")
    part = metadata.get("extra", {}).get("browserPart")
    if (
        head["Metadata"].get("kind") != "recording"
        or not isinstance(part, dict)
        or part.get("recordingId") != recording
    ):
        raise ValueError("Not a browser capture source")
    if (
        part.get("sampleRate") != 32000
        or part.get("channels") != 1
        or part.get("bitsPerSample") != 16
        or not isinstance(part.get("start"), (int, float))
        or not isinstance(part.get("duration"), (int, float))
        or not math.isfinite(part["start"])
        or not math.isfinite(part["duration"])
        or not 0 < part["duration"] <= 15.01
        or part["start"] < 0
        or ref["size"] != 44 + round(part["duration"] * 32000) * 2
    ):
        raise ValueError("Invalid browser part")
    return {
        **ref,
        "start": part["start"],
        "duration": part["duration"],
        "sessionId": metadata.get("sessionId"),
    }


def create(game, recording, mode, refs, actor, recording_ref=None):
    pk = identity(game, recording)
    fingerprint = hashlib.sha256(
        json.dumps(
            {"refs": refs, "mode": mode, "recording": recording_ref}, sort_keys=True, default=float
        ).encode()
    ).hexdigest()
    sk = mode.upper() + "#" + fingerprint
    prior = read(pk, sk)
    if prior:
        return public(prior)
    if not refs or sum(r["size"] for r in refs) > MAX_BYTES or len(refs) > 18:
        raise ValueError("Transcription window exceeds supported bounds")
    offset = refs[0]["start"]
    for ref in refs:
        if abs(ref["start"] - offset) > 0.02 or ref["sessionId"] != refs[0]["sessionId"]:
            raise ValueError("Inputs must be ordered, contiguous and in one session")
        offset += ref["duration"]
    item = {
        "pk": pk,
        "sk": sk,
        "id": fingerprint,
        "schemaVersion": 1,
        "entityType": "BrowserTranscriptionJob",
        "gameId": game,
        "recordingId": recording,
        "sessionId": refs[0]["sessionId"],
        "mode": mode,
        "status": "SUBMITTED",
        "inputs": refs,
        "start": refs[0]["start"],
        "end": offset,
        "actor": actor,
        "createdAt": int(time.time()),
    }
    if recording_ref:
        item["recording"] = recording_ref
    try:
        TABLE.put_item(
            Item=json.loads(json.dumps(item, default=float), parse_float=Decimal),
            ConditionExpression="attribute_not_exists(pk)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return public(read(pk, sk))
    return public(item)


def live_request(event, actor):
    import live_transcription as live
    raw = event.get("body") or "{}"
    if len(raw) > 150000:
        raise ValueError("Request too large")
    body = json.loads(base64.b64decode(raw) if event.get("isBase64Encoded") else raw)
    pk, sk = live.identity(body)
    if event["routeKey"].endswith("live-events"):
        record = read(pk, sk)
        if not record or record["actor"] != actor:
            return reply(403, {"error": "Live session access denied"})
        receipt = live.events(body, record)
        batch_key = sk + "#EVENT#" + body["batchId"]
        try:
            TABLE.put_item(Item=json.loads(json.dumps({"pk": pk, "sk": batch_key, **receipt}), parse_float=Decimal), ConditionExpression="attribute_not_exists(pk)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            if read(pk, batch_key).get("sha256") != receipt["sha256"]:
                return reply(409, {"error": "Live event batch changed"})
        return reply(200, {"saved": True})
    if not SECRET:
        return reply(503, {"error": "Live transcription is unavailable"})
    secret = boto3.client("secretsmanager").get_secret_value(SecretId=SECRET)["SecretString"]
    if secret.startswith("{"):
        secret = json.loads(secret)["OPENAI_API_KEY"]
    record = {"pk": pk, "sk": sk, **live.intent(body, actor)}
    try:
        TABLE.put_item(Item=record, ConditionExpression="attribute_not_exists(pk)")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return reply(409, {"error": "Live connection already requested; it will not be repeated"})
    try:
        response = live.mint(secret, record)
    except Exception as exc:
        TABLE.put_item(Item=live.failure(record, exc))
        return reply(503, {"error": "Live transcription could not connect. Audio is retained."})
    TABLE.put_item(Item=json.loads(json.dumps(record), parse_float=Decimal))
    return reply(200, response)


def handler(event, _context):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not access_policy.authorized(claims, "CATALOG_READERS"):
        return reply(403, {"error": "Member sign-in required"})
    can_record = access_policy.authorized(claims, "CATALOG_READERS")
    try:
        route = event.get("routeKey")
        if route == "GET /browser-recording/capabilities":
            return reply(
                200,
                {
                    "canRecord": can_record,
                    "transcriptionAvailable": bool(SECRET) and can_record,
                    "transcriptionUnavailableReason": None if SECRET else "Server transcription is not configured.",
                    "model": MODEL,
                    "liveModel": "gpt-live-transcribe",
                    "liveTransport": "realtime",
                    "chunkSeconds": 15,
                    "maxParts": 1000,
                },
            )
        if not can_record:
            return reply(403, {"error": "Publishing access is required to record"})
        if route in {"POST /browser-recording/live-session", "POST /browser-recording/live-events"}:
            return live_request(event, claims["sub"])
        if route == "GET /browser-transcriptions":
            query = event.get("queryStringParameters") or {}
            pk = identity(query.get("gameId"), query.get("recordingId"))
            mode = query.get("mode", "live")
            if mode not in {"live", "final"}:
                raise ValueError("Invalid mode")
            jobs = entries(pk, mode)
            transcript = read(pk, "FINAL-TRANSCRIPT")
            playback = None
            if query.get("playbackJobId"):
                completed = playback_jobs.read(query["playbackJobId"])
                if (
                    not completed
                    or completed.get("workflowVersion") != 2
                    or completed["gameId"] != query["gameId"]
                    or completed["chunkSetId"] != query["recordingId"]
                ):
                    raise ValueError("Playback does not belong to this browser recording")
                playback = {"status": completed["status"]}
                if completed["status"] == "DONE":
                    playback["audioKey"] = completed["output"]["audio"]["key"]
            return reply(
                200,
                {
                    "jobs": [public(j) for j in jobs],
                    "playback": playback,
                    "transcriptKey": transcript.get("key") if transcript else None,
                },
            )
        if route == "POST /browser-recording/complete":
            raw = event.get("body") or "{}"
            if len(raw) > 5000:
                raise ValueError("Request too large")
            body = json.loads(base64.b64decode(raw) if event.get("isBase64Encoded") else raw)
            ref = playback_jobs.reference(body["recordingKey"])
            manifest = playback_jobs.document(ref)
            if (
                manifest.get("entityType") != "BrowserRecording"
                or manifest["gameId"] != body["gameId"]
            ):
                raise ValueError("Expected browser recording")
            prefix = body["recordingKey"].removesuffix("recording.json")
            if (
                not isinstance(manifest.get("parts"), list)
                or not 1 <= len(manifest["parts"]) <= 1000
            ):
                raise ValueError("Unsupported completed set")
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(
                    pool.map(
                        lambda part: source(
                            body["gameId"], manifest["id"], prefix + part["file"], claims["sub"]
                        ),
                        manifest["parts"],
                    )
                )
            return reply(200, playback_jobs.submit(body))
        if route != "POST /browser-transcriptions":
            return reply(404, {"error": "Unknown operation"})
        if not SECRET:
            return reply(
                503, {"error": "OpenAI transcription is not configured; audio is retained"}
            )
        raw = event.get("body") or "{}"
        if len(raw) > 5000:
            raise ValueError("Request too large")
        body = json.loads(base64.b64decode(raw) if event.get("isBase64Encoded") else raw)
        game, recording, mode = body["gameId"], body["recordingId"], body["mode"]
        identity(game, recording)
        if mode == "live" and set(body) == {"gameId", "recordingId", "mode", "inputKey"}:
            refs = [source(game, recording, body["inputKey"], claims["sub"])]
            return reply(200, {"jobs": [create(game, recording, mode, refs, claims["sub"])]})
        if mode != "final" or set(body) != {"gameId", "recordingId", "mode", "playbackJobId"}:
            raise ValueError("Expected completed set")
        completed = playback_jobs.read(body["playbackJobId"])
        if (
            not completed
            or completed.get("workflowVersion") != 2
            or completed.get("setStatus") != "COMPLETE"
            or completed["gameId"] != game
            or completed["chunkSetId"] != recording
        ):
            raise ValueError("Full transcription requires a server-verified completed browser set")
        manifest = playback_jobs.document(completed["recording"])
        with ThreadPoolExecutor(max_workers=8) as pool:
            refs = list(
                pool.map(
                    lambda ref: source(game, recording, ref["key"], claims["sub"]),
                    completed["chunks"],
                )
            )
        for ref, pinned, part in zip(refs, completed["chunks"], manifest["parts"], strict=True):
            if (
                ref["sha256"] != pinned["sha256"]
                or abs(ref["start"] - part["start"]) > 0.02
                or abs(ref["duration"] - part["duration"]) > 0.001
            ):
                raise ValueError("Completed source changed")
        groups = [refs[i : i + 18] for i in range(0, len(refs), 18)]
        plan = {
            "pk": identity(game, recording),
            "sk": "FINAL-PLAN",
            "schemaVersion": 1,
            "recording": completed["recording"],
            "groupCount": len(groups),
            "sessionName": manifest["sessionName"],
            "captureWarnings": manifest.get("captureWarnings", []),
            "captureStatus": manifest["status"],
        }
        old = read(plan["pk"], plan["sk"])
        if old and old["recording"] != plan["recording"]:
            return reply(409, {"error": "A different completed set was already committed"})
        if not old:
            TABLE.put_item(Item=plan, ConditionExpression="attribute_not_exists(pk)")
        return reply(
            200,
            {
                "jobs": [
                    create(game, recording, mode, group, claims["sub"], completed["recording"])
                    for group in groups
                ]
            },
        )
    except (ValueError, KeyError, TypeError):
        return reply(400, {"error": "Invalid or incomplete browser audio"})
    except ClientError:
        return reply(
            503, {"error": "Storage is unavailable. Retry the same request; do not rerecord."}
        )


def enqueue(event, _context):
    decoder, failures = TypeDeserializer(), []
    for record in event.get("Records", []):
        try:
            new = {
                k: decoder.deserialize(v) for k, v in record["dynamodb"].get("NewImage", {}).items()
            }
            old = {
                k: decoder.deserialize(v) for k, v in record["dynamodb"].get("OldImage", {}).items()
            }
            if new.get("status") == "SUBMITTED" and old.get("status") != "SUBMITTED":
                boto3.client("sqs").send_message(
                    QueueUrl=os.environ["BROWSER_TRANSCRIPTION_QUEUE"],
                    MessageBody=json.dumps({"pk": new["pk"], "sk": new["sk"]}),
                )
        except Exception:
            failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})
    return {"batchItemFailures": failures}


def publish(job, name, doc, kind, sources, generation):
    raw = json.dumps(
        doc, default=lambda v: float(v) if isinstance(v, Decimal) else str(v), ensure_ascii=False
    ).encode()
    ref = f"games/{job['gameId']}/assets/browser-asr-{job['id']}/original/{name}"
    metadata = asset_metadata.defaults(
        kind,
        {
            "sessionId": job["sessionId"],
            "title": "Full room transcript · " + job.get("sessionName", job["sessionId"])
            if name == "transcript.json"
            else f"{job['mode'].title()} room transcript · {job['start']}s",
            "characterIds": [],
            "sourceKeys": sources,
            "extra": {
                "relationshipRole": "finished" if kind == "raw-transcript" else "intermediate",
                "generation": generation,
            },
        },
        name,
        "application/json",
        ref,
    )
    asset_metadata.validate_generation(generation)
    encoded = base64.b64encode(
        json.dumps({"schemaVersion": 1, **metadata}, separators=(",", ":")).encode()
    ).decode()
    headers = {
        "kind": kind,
        "uploaded-by": job["actor"],
        "panther": encoded,
        "asset-created-at": datetime.now(timezone.utc).isoformat(),
    }
    if sum(len(k) + len(v) for k, v in headers.items()) > 1900:
        raise ValueError("Provenance exceeds metadata size")
    sha = base64.b64encode(hashlib.sha256(raw).digest()).decode()
    location = media.s3.reserve(ref, kind, metadata, sha, len(raw), headers["asset-created-at"])
    try:
        media.s3.raw.put_object(
            Bucket=media.BUCKET_NAME,
            Key=location,
            Body=raw,
            ContentType="application/json",
            Metadata=headers,
            ChecksumSHA256=sha,
            IfNoneMatch="*",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {
            "PreconditionFailed",
            "ConditionalRequestConflict",
        }:
            raise
        head = media.s3.head_object(Bucket=media.BUCKET_NAME, Key=ref, ChecksumMode="ENABLED")
        if head.get("ChecksumSHA256") != sha or head["ContentLength"] != len(raw):
            raise ValueError("Existing output differs; refusing overwrite")
    return ref


def transcribe(wav):
    secret = boto3.client("secretsmanager").get_secret_value(SecretId=SECRET)["SecretString"]
    if secret.startswith("{"):
        secret = json.loads(secret)["OPENAI_API_KEY"]
    if not isinstance(secret, str) or not secret.strip() or any(c in secret for c in "\r\n"):
        raise ValueError("Invalid credential")
    boundary = "panther-" + uuid.uuid4().hex
    fields = {"model": MODEL, "response_format": "json", "languages[]": "en"}
    body = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        for key, value in fields.items()
    )
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="room.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
        + wav
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=body,
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Provider response too large")
    result = json.loads(raw)
    if not isinstance(result.get("text"), str) or len(result["text"]) > 100_000:
        raise ValueError("Invalid transcript response")
    return result


def input_audio(job):
    pcm = bytearray()
    for ref in job["inputs"]:
        obj = media.s3.get_object(Bucket=media.BUCKET_NAME, Key=ref["key"])
        with obj["Body"] as stream:
            raw = stream.read(int(ref["size"]) + 1)
        if (
            len(raw) != ref["size"]
            or base64.b64encode(hashlib.sha256(raw).digest()).decode() != ref["sha256"]
        ):
            raise ValueError("Source pin mismatch")
        with wave.open(io.BytesIO(raw)) as audio:
            if (
                audio.getnchannels(),
                audio.getsampwidth(),
                audio.getframerate(),
                audio.getcomptype(),
            ) != (1, 2, 32000, "NONE"):
                raise ValueError("Invalid lossless browser source")
            if audio.getnframes() != round(float(ref["duration"]) * 32000):
                raise ValueError("Source sample count mismatch")
            pcm.extend(audio.readframes(audio.getnframes()))
    if len(pcm) + 44 > MAX_BYTES:
        raise ValueError("Transcription audio exceeds limit")
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(32000)
        audio.writeframes(pcm)
    return output.getvalue()


def finish(job):
    pk = job["pk"]
    plan = read(pk, "FINAL-PLAN")
    if job["mode"] != "final" or not plan or read(pk, "FINAL-TRANSCRIPT"):
        return
    jobs = entries(pk, "final")
    if len(jobs) != plan["groupCount"] or any(j["status"] != "DONE" for j in jobs):
        return
    sources = [plan["recording"]["key"], *[ref["key"] for j in jobs for ref in j["inputs"]]]
    evidence = [j["responseKey"] for j in jobs]
    doc = {
        "schemaVersion": 1,
        "entityType": "BrowserTranscript",
        "gameId": job["gameId"],
        "recordingId": job["recordingId"],
        "sessionId": job["sessionId"],
        "sessionName": plan["sessionName"],
        "mode": "final",
        "reviewStatus": "unreviewed",
        "requestedModel": MODEL,
        "players": [],
        "sourceKeys": sources,
        "inputArtifacts": {
            **{f"response-{index}": {"key": key} for index, key in enumerate(evidence)},
            "recording": plan["recording"],
        },
        "timestampPrecision": "window-boundary",
        "captureIntegrity": {
            "status": plan["captureStatus"],
            "warnings": plan["captureWarnings"],
            "coverage": "Browser PCM samples; hardware continuity and speaker attribution unverified.",
        },
        "segments": [
            {"start": j["start"], "end": j["end"], "text": j["text"], "playerId": None}
            for j in jobs
        ],
    }
    generation = {
        "schemaVersion": 1,
        "method": "ai",
        "provider": "OpenAI",
        "inference": "remote",
        "execution": "remote",
        "tool": "OpenAI audio transcriptions",
        "cost": {"status": "unknown"},
        "evidence": "Separate full pass requested gpt-transcribe; billed amount and snapshot not established.",
    }
    aggregate_job = {
        **job,
        "sessionName": plan["sessionName"],
        "id": hashlib.sha256(("browser-final:" + plan["recording"]["sha256"]).encode()).hexdigest(),
    }
    key = publish(
        aggregate_job,
        "transcript.json",
        doc,
        "raw-transcript",
        [plan["recording"]["key"]],
        generation,
    )
    try:
        TABLE.put_item(
            Item={"pk": pk, "sk": "FINAL-TRANSCRIPT", "key": key},
            ConditionExpression="attribute_not_exists(pk)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


def work(event, _context):
    failures = []
    for message in event.get("Records", []):
        job = None
        try:
            key = json.loads(message["body"])
            job = read(key["pk"], key["sk"])
            if not job:
                raise ValueError("Job missing")
            if job["status"] == "DONE":
                try:
                    finish(job)
                except Exception:
                    failures.append({"itemIdentifier": message["messageId"]})
                continue
            if job["status"] != "SUBMITTED":
                # A redelivery never repeats a possibly charged provider request.
                if job["status"] == "RUNNING":
                    TABLE.update_item(
                        Key=key,
                        UpdateExpression="SET #s=:s, #e=:e",
                        ExpressionAttributeNames={"#s": "status", "#e": "error"},
                        ExpressionAttributeValues={
                            ":s": "UNKNOWN",
                            ":e": "Provider outcome is unknown; source audio retained. No automatic paid retry.",
                        },
                    )
                continue
            TABLE.update_item(
                Key=key,
                UpdateExpression="SET #s=:running",
                ConditionExpression="#s=:submitted",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":running": "RUNNING", ":submitted": "SUBMITTED"},
            )
            audio = input_audio(job)
            result = transcribe(audio)
            generation = {
                "schemaVersion": 1,
                "method": "ai",
                "provider": "OpenAI",
                "inference": "remote",
                "execution": "remote",
                "tool": "OpenAI audio transcriptions",
                "cost": {"status": "unknown"},
                "evidence": "Requested gpt-transcribe; response preserved, billed charge unknown.",
            }
            if isinstance(result.get("model"), str):
                generation["model"] = result["model"]
            response_key = publish(
                job,
                "provider-response.json",
                {
                    "schemaVersion": 1,
                    "requestedModel": MODEL,
                    "requestAudioSha256": hashlib.sha256(audio).hexdigest(),
                    "sourceKeys": [r["key"] for r in job["inputs"]],
                    "response": result,
                },
                "asr-response",
                [],
                generation,
            )
            # Preserve the response before making any publication claim.
            text = result["text"]
            TABLE.update_item(
                Key=key,
                UpdateExpression="SET #s=:done, #t=:text, responseKey=:response",
                ExpressionAttributeNames={"#s": "status", "#t": "text"},
                ExpressionAttributeValues={
                    ":done": "DONE",
                    ":text": text,
                    ":response": response_key,
                },
            )
            job.update(status="DONE", text=text, responseKey=response_key)
            try:
                finish(job)
            except Exception:
                failures.append({"itemIdentifier": message["messageId"]})
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                failures.append({"itemIdentifier": message["messageId"]})
        except Exception:
            if job:
                TABLE.update_item(
                    Key={"pk": job["pk"], "sk": job["sk"]},
                    UpdateExpression="SET #s=:s, #e=:e",
                    ExpressionAttributeNames={"#s": "status", "#e": "error"},
                    ExpressionAttributeValues={
                        ":s": "UNKNOWN",
                        ":e": "Transcription did not complete. Audio is retained; no automatic paid retry.",
                    },
                )
            else:
                failures.append({"itemIdentifier": message["messageId"]})
    return {"batchItemFailures": failures}
