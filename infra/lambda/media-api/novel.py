"""Read-only, game-scoped projection of completed novel stages; never modifies artifacts."""

import re
from datetime import datetime
import time

import boto3

from botocore.exceptions import ClientError
import editorial_jobs as jobs
import browse_index


def committed_records(summaries):
    """Bounded projected batch reads; no manuscript reads and no task-token projection."""
    summaries = [s for s in summaries if s.get("authorship") != "human"]
    keys = [
        {"pk": prefix, "sk": s["id"] + (":novel-chapter" if prefix == "TASKS" else "")}
        for s in summaries
        for prefix in ("RUNS", "TASKS")
    ]
    keys = list({(k["pk"], k["sk"]): k for k in keys}.values())
    records = {}
    deadline = time.monotonic() + 20
    for offset in range(0, len(keys), 100):
        pending = {
            jobs.table.name: {
                "Keys": keys[offset : offset + 100],
                "ConsistentRead": True,
                "ProjectionExpression": "pk, sk, gameId, sessionId, createdAt, #s, #o",
                "ExpressionAttributeNames": {"#s": "status", "#o": "output"},
            }
        }
        for _ in range(20):
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "Chapter status reads timed out; no incomplete list was returned"
                )
            response = boto3.resource("dynamodb").batch_get_item(RequestItems=pending)
            records.update(
                {
                    (r["pk"], r["sk"]): r
                    for r in response.get("Responses", {}).get(jobs.table.name, [])
                }
            )
            pending = response.get("UnprocessedKeys", {})
            if not pending:
                break
        if pending:
            raise RuntimeError("Chapter status reads are incomplete; retry")
    return records


def chapter(job):
    task = jobs.read("TASKS", f"{job['jobId']}:novel-chapter")
    if not task or task.get("status") != "DONE":
        return None
    reference = task["output"]
    # Trust neither request keys nor stored content to cross the selected game boundary.
    if (
        not reference["key"].startswith(f"games/{job['gameId']}/assets/")
        or not jobs.media._valid_key(reference["key"])
        or not 0 < reference["size"] <= 2 * 1024**2
    ):
        raise ValueError("Invalid chapter reference")
    artifact = jobs.document(reference)
    if (
        artifact.get("entityType") != "EditorialArtifact"
        or artifact.get("gameId") != job["gameId"]
        or artifact.get("jobId") != job["jobId"]
        or artifact.get("sessionId") != job["sessionId"]
        or artifact.get("stage") != "novel-chapter"
        or artifact.get("publicationStatus") not in {"accepted", "accepted-with-notes"}
        or not isinstance(artifact.get("payload", {}).get("chapter"), str)
    ):
        raise ValueError("Invalid chapter envelope")
    manuscript = artifact["payload"]["chapter"].strip()
    # A legacy, explicitly labeled pre-title notice belongs in the chrome, not the prose.
    # Do not split on arbitrary headings: a story may legitimately mention editorial notes.
    notice = ""
    legacy_notice = "**Adapted from fictional microphone-test material; not campaign canon.**"
    if manuscript.startswith(legacy_notice + "\n"):
        notice, manuscript = legacy_notice.strip("*"), manuscript[len(legacy_notice) :].lstrip()
    heading = re.match(r"^# ([^\n]+)(?:\n|$)", manuscript)
    title = heading[1].strip() if heading else "Untitled chapter"
    prose = manuscript[heading.end() :].lstrip() if heading else manuscript
    published = jobs.media.s3.head_object(Bucket=jobs.media.BUCKET_NAME, Key=reference["key"])
    return {
        "id": job["jobId"],
        "gameId": job["gameId"],
        "sessionId": job["sessionId"],
        "title": title,
        "createdAt": job["createdAt"],
        "publishedAt": int(jobs.media._asset_created_at(published).timestamp()),
        "publicationStatus": artifact["publicationStatus"],
        "reviewStatus": artifact.get("reviewStatus", "ai-reviewed-unverified"),
        "notice": notice,
        "markdown": prose,
        # Optional typed mentions are separate from prose. The reader resolves only known,
        # same-game targets; arbitrary URLs and unknown future target types never become links.
        "readerReferences": artifact["payload"].get("readerReferences"),
        "details": {
            "review": artifact["payload"].get("review", {}),
            "revisionHistory": artifact.get("revisionHistory", []),
            "sourceKeys": artifact.get("sourceKeys", []),
            "rawReference": artifact.get("rawReference"),
            "artifact": reference,
            "workflowVersion": artifact.get("workflowVersion"),
        },
    }


def handler(event, _context):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    # Reading uses the private catalog-reader capability; publication remains separate.
    from access_policy import authorized

    if not authorized(claims, "CATALOG_READERS"):
        return jobs.response(403, {"error": "This account cannot access the novel library"})
    q = event.get("queryStringParameters") or {}
    game = q.get("gameId", "")
    if not jobs.media._valid_slug(game) or len(game) > 96:
        return jobs.response(400, {"error": "Invalid game"})
    try:
        if event.get("routeKey") == "GET /novel-chapter":
            job_id = q.get("chapterId", "")
            if not re.fullmatch(r"[a-f0-9]{64}", job_id):
                return jobs.response(400, {"error": "Invalid chapter"})
            import manual_chapters

            authored = manual_chapters.read(game, job_id, jobs.media)
            if authored:
                return jobs.response(200, authored)
            job = jobs.read("RUNS", job_id)
            result = chapter(job) if job and job["gameId"] == game else None
            return (
                jobs.response(200, result)
                if result
                else jobs.response(404, {"error": "Chapter not found"})
            )
        if event.get("routeKey") != "GET /novel":
            return jobs.response(404, {"error": "Unknown operation"})
        page = browse_index.page(game, "novels", q.get("cursor"))
        summaries = [
            a["novel"] for a in page["assets"] if a.get("novel", {}).get("state") == "available"
        ]
        records = committed_records(summaries)
        chapters = []
        for asset in page["assets"]:
            summary = asset.get("novel", {})
            if summary.get("state") != "available":
                continue
            if summary.get("authorship") == "human":
                import manual_chapters

                authored = manual_chapters.record(game, summary["id"])
                if authored and authored["assetKey"] == asset["key"]:
                    chapters.append(
                        {
                            **summary,
                            "gameId": game,
                            "createdAt": authored["createdAt"],
                            "publishedAt": authored["createdAt"],
                            "notice": "",
                            "generation": asset.get("metadata", {})
                            .get("extra", {})
                            .get("generation"),
                        }
                    )
                continue
            task = records.get(("TASKS", f"{summary['id']}:novel-chapter"))
            job = records.get(("RUNS", summary["id"]))
            if (
                not task
                or task.get("status") != "DONE"
                or task.get("output", {}).get("key") != asset["key"]
                or not job
                or job.get("gameId") != game
                or job.get("sessionId") != summary["sessionId"]
            ):
                continue  # Uploaded candidates are not committed completed chapters.
            timestamp = int(
                datetime.fromisoformat(summary["publishedAt"].replace("Z", "+00:00")).timestamp()
            )
            chapters.append(
                {
                    **summary,
                    "gameId": game,
                    "createdAt": job["createdAt"],
                    "publishedAt": timestamp,
                    "notice": "",
                    "generation": asset.get("metadata", {}).get("extra", {}).get("generation"),
                }
            )
        return jobs.response(200, {"chapters": chapters, "cursor": page["cursor"]})
    except browse_index.IndexNotReady as error:
        return jobs.response(503, {"error": str(error)})
    except RuntimeError:
        return jobs.response(
            503, {"error": "Chapter status reads are incomplete; refresh to retry"}
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return jobs.response(
            400, {"error": "Could not read the chapter or page; refresh and retry"}
        )
    except ClientError:
        return jobs.response(
            503, {"error": "Novel storage is temporarily unavailable; retry shortly"}
        )
