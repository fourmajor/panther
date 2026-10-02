"""The development UI reads persistent state, not route-specific fixtures."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("panther_development", Path(__file__).parents[1] / "tools/dev_server.py")
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)


def test_empty_database_stays_empty_until_explicit_seed(tmp_path):
    store = dev.Store(tmp_path / "development.sqlite")
    assert store.list("game") == []
    assert dev.Store(store.path).list("game") == []
    store.seed()
    assert len(dev.Store(store.path).list("game")) == 2
    assert store.game("preview-campaign")["gameSettings"]["description"] == ""
    with store.connect() as db:
        db.execute("INSERT INTO objects VALUES ('retained','preview-campaign','{}',X'0102','now')")
    store.seed()
    assert store.object("retained")[1] == b"\x01\x02"


def test_character_changes_are_durable_guarded_and_have_history(tmp_path):
    store = dev.Store(tmp_path / "development.sqlite")
    store.seed()
    character = store.get("character", "preview-campaign:lantern-guide")
    updated = {**character["details"], "overview": "A recorded character fact."}
    body = {"gameId": "preview-campaign", "characterId": "lantern-guide", "expectedRevision": character["revision"], "name": "Lantern Keeper", "details": updated, "reason": "Updated background"}
    result = store.edit_character(body)["character"]
    assert dev.Store(store.path).get("character", "preview-campaign:lantern-guide") == result
    assert len(store.list("history", "preview-campaign:lantern-guide")) == 2
    with pytest.raises(FileExistsError):
        store.edit_character(body)
    history = store.list("history", "preview-campaign:lantern-guide")[0]
    assert history["previousName"] == "The Lantern Guide"
    assert history["previousDetails"] == character["details"]


def test_development_database_cannot_write_inside_repository():
    with pytest.raises(ValueError, match="outside"):
        dev.Store(dev.ROOT / "development.sqlite")
