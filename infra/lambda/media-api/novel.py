"""Read-only, game-scoped projection of completed novel stages; never modifies artifacts."""

import base64
import json
import re

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
import editorial_jobs as jobs


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
    # Same two-person group access as the editorial/catalog APIs; memberships are game roles,
    # not authorization grants. Future multi-group access must change this policy explicitly.
    if not claims.get("sub") or claims.get("cognito:username") not in {"stu", "other_stu"}:
        return jobs.response(403, {"error": "Owner or DM sign-in required"})
    q = event.get("queryStringParameters") or {}
    game = q.get("gameId", "")
    if not jobs.media._valid_slug(game) or len(game) > 96:
        return jobs.response(400, {"error": "Invalid game"})
    try:
        if event.get("routeKey") == "GET /novel-chapter":
            job_id = q.get("chapterId", "")
            if not re.fullmatch(r"[a-f0-9]{64}", job_id):
                return jobs.response(400, {"error": "Invalid chapter"})
            job = jobs.read("RUNS", job_id)
            result = chapter(job) if job and job["gameId"] == game else None
            return (
                jobs.response(200, result)
                if result
                else jobs.response(404, {"error": "Chapter not found"})
            )
        if event.get("routeKey") != "GET /novel":
            return jobs.response(404, {"error": "Unknown operation"})
        args = {
            "KeyConditionExpression": Key("pk").eq("RUNS"),
            "FilterExpression": Attr("gameId").eq(game),
            "ConsistentRead": True,
            "Limit": 20,
        }
        if q.get("cursor"):
            cursor = json.loads(base64.urlsafe_b64decode(q["cursor"]))
            if cursor.get("gameId") != game or not re.fullmatch(
                r"[a-f0-9]{64}", cursor.get("sk", "")
            ):
                raise ValueError("Invalid cursor")
            args["ExclusiveStartKey"] = {"pk": "RUNS", "sk": cursor["sk"]}
        page = jobs.table.query(**args)
        chapters = []
        for job in page.get("Items", []):
            result = chapter(job)
            if result:
                chapters.append(
                    {
                        k: v for k, v in result.items()
                        if k not in {"markdown", "details", "readerReferences"}
                    }
                )
        cursor = None
        if page.get("LastEvaluatedKey"):
            cursor = base64.urlsafe_b64encode(
                json.dumps({"gameId": game, "sk": page["LastEvaluatedKey"]["sk"]}).encode()
            ).decode()
        return jobs.response(200, {"chapters": chapters, "cursor": cursor})
    except (ValueError, TypeError, KeyError, AttributeError):
        return jobs.response(
            400, {"error": "Could not read the chapter or page; refresh and retry"}
        )
    except ClientError:
        return jobs.response(
            503, {"error": "Novel storage is temporarily unavailable; retry shortly"}
        )
