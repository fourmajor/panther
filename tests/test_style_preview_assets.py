"""Settings previews are actual inspectable UI bitmaps with truthful provenance."""

import hashlib
import importlib.util
import json
from pathlib import Path


def test_style_previews_have_exact_common_prompt_registered_urls_and_hashes():
    root = Path(__file__).parents[1]
    folder = root / "web/media-explorer/style-previews"
    manifest = json.loads((folder / "manifest.json").read_text())
    spec = importlib.util.spec_from_file_location(
        "preview_visual_styles", root / "infra/lambda/media-api/visual_styles.py"
    )
    styles = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(styles)
    assert {row["id"] for row in manifest["previews"]} == {row["id"] for row in styles.STYLES}
    for preview in manifest["previews"]:
        data = (folder / preview["file"]).read_bytes()
        assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
        assert hashlib.sha256(data).hexdigest() == preview["sha256"]
        assert preview["basePrompt"] == manifest["basePrompt"]
        assert (
            preview["prompt"]
            == manifest["basePrompt"] + "\nStyle/medium: " + preview["stylePrompt"]
        )
        assert preview["width"] > preview["height"] > 0
        assert preview["generation"].get("model") is None
        assert preview["generation"]["inference"] == "remote"
        assert preview["generation"]["cost"] == {"status": "unknown"}
        assert styles.BY_ID[preview["id"]]["previewImage"] == "/style-previews/" + preview["file"]
