"""Explicit, resumable metadata migration plans through Panther authentication."""

import json
import os
import copy
import hashlib
import re
from pathlib import Path

import click

from panther_journal import cloud, generation_metadata as generation


@click.group()
def assets():
    """Audit assets and apply version-guarded metadata migrations."""


@assets.command("catalog")
@click.option("--game", required=True)
def catalog(game):
    """List the complete game asset catalog, including exact recorded provenance."""
    config = cloud.configuration()
    records, cursor = [], None
    while True:
        page = cloud.api(
            config, "GET", "/assets", params={"gameId": cloud.slug(game), "cursor": cursor}
        )
        records.extend(page["assets"])
        cursor = page.get("cursor")
        if not cursor:
            break
    click.echo(json.dumps({"gameId": game, "assets": records}, indent=2))


@assets.command("rebuild-index")
@click.option("--mode", type=click.Choice(["dry-run", "apply", "verify"]), default="dry-run")
@click.option("--report", required=True, type=click.Path(path_type=Path))
def rebuild_index(mode, report):
    """Rebuild/verify the browsing projection for ALL games; never change source files."""
    config = cloud.configuration()
    failures = 0
    with report.open("x") as stream:
        report.chmod(0o600)
        for game in cloud.api(config, "GET", "/games")["games"]:
            cursor, seen, count = None, set(), 0
            while True:
                page = cloud.api(
                    config,
                    "POST",
                    "/asset-index/rebuild",
                    json={"gameId": game["id"], "mode": mode, "cursor": cursor},
                )
                stream.write(json.dumps(page) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
                count += len(page["records"])
                failures += sum(r["status"] == "mismatch" for r in page["records"])
                click.echo(f"{game['id']}: {count} records {mode}", err=True)
                cursor = page.get("cursor")
                if not cursor:
                    break
                if cursor in seen:
                    raise click.ClickException("Repeated maintenance cursor; stopped")
                seen.add(cursor)
    if failures:
        raise click.ClickException(f"{failures} index mismatches; inspect the private report")
    if mode == "verify":
        cloud.api(config, "POST", "/asset-index/rebuild", json={"mode": "activate"})
        click.echo("All games verified; indexed browsing is active.")


def generation_plan(records, facts):
    """Version-1 backfill: preserve metadata/bytes; only explicitly evidenced facts enrich defaults."""
    if not isinstance(facts, dict) or set(facts) - {r["key"] for r in records}:
        raise click.ClickException("Generation facts must reference inventoried assets only")
    migrations = []
    for record in records:
        details = copy.deepcopy(record["metadata"])
        extra = details.setdefault("extra", {})
        desired = facts.get(record["key"], extra.get("generation", generation.unknown()))
        if not isinstance(desired, dict) or desired.get("schemaVersion") != 1:
            raise click.ClickException("Generation facts require schemaVersion 1")
        if extra.get("generation") == desired:
            continue
        extra["generation"] = desired
        migrations.append(
            {
                "schemaVersion": 1,
                "key": record["key"],
                "expectedVersionId": record["versionId"],
                "kind": record["kind"],
                "metadata": details,
                "reason": "Generation metadata v1: explicit evidence or unknown; original bytes and provenance retained",
            }
        )
    return {"schemaVersion": 1, "migrations": migrations}


def model_output_plan(records, jobs, input_keys):
    """Backfill exact model-job inputs and distinguish rejected candidates from artwork."""
    from panther_journal.model_workflow import VIEWS

    known = {record["key"] for record in records}
    by_id = {job["jobId"]: job for job in jobs}
    migrations = []
    for record in records:
        metadata = copy.deepcopy(record["metadata"])
        extra = metadata.setdefault("extra", {})
        if extra.get("modelInputManifest") is True:
            continue
        job_id = extra.get("jobId")
        if job_id is None:
            if "/assets/model-job-" in record["key"]:
                raise click.ClickException(
                    "Model output has no explicit job identity; migration blocked"
                )
            continue
        job = by_id.get(job_id)
        if job is None and "/assets/model-job-" not in record["key"]:
            continue  # Other workflow types can also record a jobId.
        if job is None or set(job.get("views", {})) != set(VIEWS):
            raise click.ClickException(
                "Model output lacks its complete recorded job; migration blocked"
            )
        inputs = [job["views"][view]["key"] for view in VIEWS]
        prefix = f"games/{job['gameId']}/assets/"
        if not record["key"].startswith(prefix) or any(
            key not in known or not key.startswith(prefix) for key in inputs
        ):
            raise click.ClickException("Model job input inventory is incomplete or crosses games")
        input_key = input_keys.get(job_id)
        if (
            not isinstance(input_key, str)
            or input_key not in known
            or not input_key.startswith(prefix)
        ):
            raise click.ClickException(
                "Verified model input manifest is missing; migration blocked"
            )
        metadata["sourceKeys"] = list(dict.fromkeys([*metadata.get("sourceKeys", []), input_key]))
        extra["relationshipRole"] = (
            "finished"
            if job["status"] == "PUBLISHED" and record["kind"] == "model-3d"
            else "intermediate"
        )
        if metadata == record["metadata"]:
            continue
        migrations.append(
            {
                "schemaVersion": 1,
                "key": record["key"],
                "expectedVersionId": record["versionId"],
                "kind": record["kind"],
                "metadata": metadata,
                "reason": "Model output v1: exact pinned references; unpublished candidates and inspection evidence are intermediate",
            }
        )
    return {"schemaVersion": 1, "migrations": migrations}


def model_output_inventory(config):
    from panther_journal.character_details import pages

    records = []
    for game in cloud.api(config, "GET", "/games")["games"]:
        for asset in pages(config, "/assets", {"gameId": game["id"]}, "assets"):
            if (
                asset.get("metadata", {}).get("extra", {}).get("jobId")
                or "/assets/model-job-" in asset["key"]
            ):
                info = cloud.api(config, "GET", "/object-url", params={"key": asset["key"]})
                records.append({k: info[k] for k in ("key", "versionId", "kind", "metadata")})
            else:
                records.append({"key": asset["key"], "metadata": asset.get("metadata", {})})
    jobs, cursor, seen = [], None, set()
    while True:
        page = cloud.api(config, "GET", "/model-jobs", params={"cursor": cursor})
        jobs.extend(page["jobs"])
        cursor = page.get("nextCursor")
        if not cursor:
            break
        if cursor in seen:
            raise click.ClickException("Repeated job cursor; inventory is incomplete")
        seen.add(cursor)
    return records, jobs


@assets.command("model-output-inputs")
@click.option("--directory", required=True, type=click.Path(path_type=Path))
def prepare_model_inputs(directory):
    """Prepare private input manifests for explicit CLI upload; no cloud writes."""
    from panther_journal.character_details import private_file
    from panther_journal.model_workflow import VIEWS

    records, jobs = model_output_inventory(cloud.configuration())
    wanted = {
        r.get("metadata", {}).get("extra", {}).get("jobId")
        for r in records
        if "/assets/model-job-" in r["key"]
    }
    by_id = {j["jobId"]: j for j in jobs}
    if None in wanted or wanted - set(by_id):
        raise click.ClickException("Missing recorded model job; cannot prepare lineage")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    mapping = {}
    for job_id in sorted(wanted):
        job = by_id[job_id]
        if set(job.get("views", {})) != set(VIEWS):
            raise click.ClickException("Incomplete job references")
        asset_id = f"model-inputs-{job_id[:32]}"
        file = directory / f"{job_id}.json"
        private_file(
            file,
            {
                "schemaVersion": 1,
                "jobId": job_id,
                "sourceKeys": [job["views"][v]["key"] for v in VIEWS],
                "views": job["views"],
            },
        )
        private_file(
            directory / f"{job_id}.metadata.json",
            {
                "title": "Recorded model workflow inputs",
                "category": "reference",
                "characterIds": [job["characterId"]],
                "sourceKeys": [],
                "extra": {
                    "jobId": job_id,
                    "modelInputManifest": True,
                    "relationshipRole": "intermediate",
                    "appearanceId": job["appearanceId"],
                    "generation": generation.local("Panther metadata migration"),
                },
            },
        )
        mapping[job_id] = f"games/{job['gameId']}/assets/{asset_id}/original/{file.name}"
    private_file(directory / "input-map.json", mapping)
    click.echo(
        f"Prepared {len(mapping)} private manifests. Upload each using its metadata, model-provenance kind and input-map asset ID."
    )


@assets.command("model-output-plan")
@click.option("--input-map", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--output", required=True, type=click.Path(path_type=Path))
def plan_model_outputs(input_map, output):
    """Verify uploaded lineage and prepare an all-game guarded metadata plan."""
    import tempfile
    from panther_journal.character_details import private_file
    from panther_journal.model_workflow import VIEWS, download

    config = cloud.configuration()
    records, jobs = model_output_inventory(config)
    mapping = json.loads(input_map.read_text())
    by_id = {j["jobId"]: j for j in jobs}
    with tempfile.TemporaryDirectory(prefix="panther-model-input-verify-") as folder:
        for job_id, key in mapping.items():
            if job_id not in by_id:
                raise click.ClickException("Input map references an unknown model job")
            info = cloud.api(config, "GET", "/object-url", params={"key": key})
            if info.get("size", 0) > 64000:
                raise click.ClickException("Input manifest is too large")
            path = Path(folder) / f"{job_id}.json"
            download(config, info, path)
            document = json.loads(path.read_text())
            expected = [by_id[job_id]["views"][v]["key"] for v in VIEWS]
            if document.get("jobId") != job_id or document.get("sourceKeys") != expected:
                raise click.ClickException("Uploaded model inputs do not match the pinned job")
    plan = model_output_plan(records, jobs, mapping)
    private_file(output, plan)
    click.echo(
        f"Inventoried {len(records)} assets in all games; {len(plan['migrations'])} model metadata repairs."
    )


def version_plan(records, appearances):
    """Preserve explicit version families; appearance membership is not revision order."""
    known = {record["key"]: record for record in records}
    if len(known) != len(records):
        raise click.ClickException("Duplicate asset inventory")
    for keys in appearances.values():
        for key in keys:
            if key not in known:
                raise click.ClickException(f"Official appearance is missing from inventory: {key}")
    migrations = []
    versions = {}
    for record in records:
        details = copy.deepcopy(record["metadata"])
        extra = details.setdefault("extra", {})
        if not isinstance(extra, dict):
            raise click.ClickException(f"Invalid explicit asset metadata: {record['key']}")
        version = extra.get("version")
        if version is not None:
            if (
                not isinstance(version, dict)
                or set(version) - {"schemaVersion", "seriesId", "number", "previousKey"}
                or type(version.get("schemaVersion")) is not int
                or version.get("schemaVersion") != 1
                or type(version.get("number")) is not int
                or not 1 <= version["number"] <= 10000
                or not isinstance(version.get("seriesId"), str)
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", version["seriesId"])
                or len(version["seriesId"]) > 96
                or (version["number"] == 1 and version.get("previousKey") is not None)
                or (
                    version["number"] > 1
                    and (
                        not isinstance(version.get("previousKey"), str)
                        or version["previousKey"] == record["key"]
                        or not re.fullmatch(
                            r"games/[a-z0-9-]+/assets/[a-z0-9-]+/(?:original|derived/[a-z0-9-]+|metadata)/[^/]+",
                            version["previousKey"],
                        )
                        or not version["previousKey"].startswith(
                            "/".join(record["key"].split("/")[:2]) + "/assets/"
                        )
                    )
                )
            ):
                raise click.ClickException(f"Invalid explicit asset version: {record['key']}")
            versions[record["key"]] = version
            continue
        version = {
            "schemaVersion": 1,
            "seriesId": hashlib.sha256(record["key"].encode()).hexdigest()[:24],
            "number": 1,
        }
        versions[record["key"]] = extra["version"] = version
        migrations.append(
            {
                "schemaVersion": 1,
                "key": record["key"],
                "expectedVersionId": record["versionId"],
                "kind": record["kind"],
                "metadata": details,
                "reason": "Asset versions v1: explicit singleton where no revision evidence exists; existing families and original bytes retained",
            }
        )
    for key, version in versions.items():
        if version.get("previousKey") is None:
            continue
        predecessor = version["previousKey"]
        prior = versions.get(predecessor)
        if (
            not prior
            or predecessor == key
            or prior["seriesId"] != version["seriesId"]
            or prior["number"] != version["number"] - 1
            or known[predecessor]["kind"] != known[key]["kind"]
            or predecessor.split("/")[1] != key.split("/")[1]
        ):
            raise click.ClickException(f"Unresolvable explicit version predecessor: {key}")
    return {"schemaVersion": 1, "migrations": migrations}


@assets.command("version-plan")
@click.option("--output", required=True, type=click.Path(path_type=Path))
def plan_versions(output):
    """Inventory ALL games and prepare a private, version-pinned appearance backfill."""
    from panther_journal.character_details import pages, private_file

    config = cloud.configuration()
    records, appearances = [], {}
    for game in cloud.api(config, "GET", "/games")["games"]:
        game_id = game["id"]
        cursor = None
        while True:
            page = cloud.api(config, "GET", "/assets", params={"gameId": game_id, "cursor": cursor})
            for asset in page["assets"]:
                info = cloud.api(config, "GET", "/object-url", params={"key": asset["key"]})
                records.append({k: info[k] for k in ("key", "versionId", "kind", "metadata")})
            cursor = page.get("cursor")
            if not cursor:
                break
        characters = pages(config, "/characters", {"gameId": game_id}, "characters")
        profiles = pages(
            config,
            "/character-appearance-migration/game-inventory",
            {"gameId": game_id},
            "characters",
        )
        if set(profiles) - {c["id"] for c in characters}:
            raise click.ClickException(
                "Unregistered artwork profile; reconcile the all-game character inventory first."
            )
        for character in characters:
            history = cloud.api(
                config,
                "GET",
                "/character-versions",
                params={"gameId": game_id, "characterId": character["id"]},
            )
            if history.get("schemaVersion") != 2 or not isinstance(history.get("selections"), list):
                raise click.ClickException("Complete typed appearance history is required")
            for kind, field in (("model", "modelKey"), ("portrait", "portraitKey")):
                keys = list(
                    dict.fromkeys(
                        item[field] for item in history["selections"] if item[field] is not None
                    )
                )
                if keys:
                    appearances[(game_id, character["id"], kind)] = keys
    try:
        plan = version_plan(records, appearances)
        private_file(output, plan)
    except (OSError, ValueError):
        raise click.ClickException(
            "Could not create a new private plan; never overwrite a prior plan"
        ) from None
    click.echo(
        f"Inventoried {len(records)} assets in all games; planned {len(plan['migrations'])} version records. Dry-run with assets migrate."
    )


@assets.command("generation-plan")
@click.option(
    "--facts",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Private JSON map of exact asset keys to evidence-backed generation records.",
)
@click.option("--output", required=True, type=click.Path(path_type=Path))
def plan_generation(facts, output):
    """Inventory ALL games and prepare a generation-v1 migration. No cloud writes."""
    config = cloud.configuration()
    records = []
    for game in cloud.api(config, "GET", "/games")["games"]:
        cursor = None
        while True:
            page = cloud.api(
                config, "GET", "/assets", params={"gameId": game["id"], "cursor": cursor}
            )
            for asset in page["assets"]:
                info = cloud.api(config, "GET", "/object-url", params={"key": asset["key"]})
                records.append({k: info[k] for k in ("key", "versionId", "kind", "metadata")})
            cursor = page.get("cursor")
            if not cursor:
                break
    try:
        supplied = json.loads(facts.read_text()) if facts else {}
        plan = generation_plan(records, supplied)
        with output.open("x") as stream:
            output.chmod(0o600)
            json.dump(plan, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError):
        raise click.ClickException(
            "Could not read facts or create a new private plan; never overwrite a prior plan"
        ) from None
    click.echo(
        f"Inventoried {len(records)} assets across all games; planned {len(plan['migrations'])} metadata updates. Dry-run with assets migrate."
    )


@assets.command("migrate")
@click.argument("plan", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--apply", is_flag=True, help="Apply the inspected plan; otherwise validate without writing."
)
@click.option(
    "--report",
    required=True,
    type=click.Path(path_type=Path),
    help="New private JSONL audit report; never overwrite an earlier report.",
)
def migrate(plan, apply, report):
    """Dry-run/apply a schemaVersion-1 plan with migrations[] and pinned expectedVersionId.

    Each entry contains schemaVersion, key, expectedVersionId, kind, metadata, and reason.
    File bytes are never accepted or replaced. Retries reuse the same plan.
    """
    run_migrations(plan, apply, report, "/asset-migrations")


def run_migrations(plan, apply, report, endpoint, extra=None):
    try:
        document = json.loads(plan.read_text())
        if document.get("schemaVersion") != 1 or not isinstance(document.get("migrations"), list):
            raise ValueError()
        records = document["migrations"]
        if not records or len(records) > 5000:
            raise ValueError()
        if len({r["key"] for r in records}) != len(records):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise click.ClickException("Invalid migration plan; expected unique pinned assets.")
    config = cloud.configuration()
    try:
        with report.open("x", encoding="utf-8") as output:
            report.chmod(0o600)
            for entry in records:
                try:
                    result = cloud.api(
                        config,
                        "POST",
                        endpoint,
                        json={**entry, **(extra or {}), "dryRun": not apply},
                    )
                except click.ClickException:
                    output.write(
                        json.dumps(
                            {"key": entry["key"], "status": "interrupted-inspect-before-retry"}
                        )
                        + "\n"
                    )
                    output.flush()
                    os.fsync(output.fileno())
                    raise
                output.write(
                    json.dumps(
                        {
                            "request": entry,
                            "endpoint": endpoint,
                            "operation": extra or {},
                            "dryRun": not apply,
                            "result": result,
                        }
                    )
                    + "\n"
                )
                output.flush()
                os.fsync(output.fileno())
                click.echo(f"{result['status']}: {entry['key']}")
    except FileExistsError:
        raise click.ClickException("Report already exists. Keep it and choose a new report path.")
    click.echo(f"Verified {len(records)} migration responses; report: {report}")
