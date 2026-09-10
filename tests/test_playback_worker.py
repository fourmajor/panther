import base64
import hashlib
import json
from pathlib import Path
import shutil

import click
import pytest
import requests

from panther_journal import recording as audio, playback_worker as worker
from test_recording_resilience import source  # noqa: F401


def test_worker_builds_only_from_completed_pinned_cloud_set(source, tmp_path, monkeypatch):  # noqa: F811
    folder, header = source
    record = audio.finish_capture(folder, header, "complete")
    refs = []
    for name in ["recording.json", "part-0000.flac"]:
        file = folder / name
        refs.append({"key": f"games/{record.gameId}/assets/{record.id}/original/{name}",
                     "size": file.stat().st_size,
                     "sha256": base64.b64encode(bytes.fromhex(audio.digest(file))).decode()})
    jid = hashlib.sha256(b"synthetic job").hexdigest()
    claim = {"job": {"jobId": jid, "gameId": record.gameId, "chunkSetId": record.id,
                     "workflowVersion": 1, "setStatus": "COMPLETE", "recording": refs[0], "chunks": refs[1:]},
             "lease": "synthetic-lease"}
    root = tmp_path / "worker"
    root.mkdir()
    events = []
    def download(config, ref, destination):
        events.append(("download", ref["key"]))
        shutil.copyfile(folder / destination.name, destination)
    def api(config, method, route, **kwargs):
        assert kwargs["json"]["lease"] == "synthetic-lease"
        events.append(("api", route))
        if route.endswith("/complete"):
            assert len([e for e in events if e[0] == "upload"]) == 2
        return {"jobId": jid, "status": "DONE"}
    def upload(config, file, record, kind, **kwargs):
        events.append(("upload", kind))
        if kind == "recording-playback":
            assert kwargs["source_keys"] == ["manifest-key"]
        return "manifest-key" if file.suffix == ".json" else "audio-key"
    monkeypatch.setattr(worker, "download", download)
    monkeypatch.setattr(worker.cloud, "api", api)
    monkeypatch.setattr(audio, "upload_one", upload)
    assert worker.process({}, claim, root)["status"] == "DONE"
    saved = json.loads(next((root / jid).glob("playback-*.json")).read_text())
    assert saved["sourceKeys"] == [ref["key"] for ref in refs]
    assert saved["inputSamples"] == 28800
    assert audio.digest(root / jid / "part-0000.flac") == record.parts[0].sha256
    assert not list(folder.glob("playback-*"))  # Uploading machine's local files are not used for output.
    with pytest.raises(click.ClickException, match="completed"):
        worker.process({}, {**claim, "job": {**claim["job"], "setStatus": "UPLOADING"}}, root)
    def failed_download(*args):
        raise requests.HTTPError("https://example.invalid/?X-Amz-Signature=DO-NOT-LOG")
    monkeypatch.setattr(worker, "download", failed_download)
    with pytest.raises(click.ClickException, match="download failed") as caught:
        worker.process({}, claim, root)
    assert "DO-NOT-LOG" not in str(caught.value) and caught.value.__suppress_context__


def test_lost_lease_is_not_silently_ignored(monkeypatch):
    claim = {"job": {"jobId": "a" * 64}, "lease": "synthetic"}
    lease = worker.Lease({}, claim)
    lease.error = True
    with pytest.raises(click.ClickException, match="lease lost"):
        lease.check()


def test_playback_installer_pins_worker_without_ai_or_aws(tmp_path):
    import runpy
    install = runpy.run_path(str(Path(__file__).parents[1] / "ops/playback-worker/install.py"))
    definition = install["service_definition"](tmp_path / "release", tmp_path / "state", tmp_path / "home")
    assert definition["Label"] == "place.panther.playback-worker"
    assert definition["ProgramArguments"][1:4] == ["recording", "playback", "worker"]
    assert definition["StartInterval"] == 60 and definition["Umask"] == 0o077
    assert not any("AWS" in k or "CODEX" in k for k in definition["EnvironmentVariables"])
