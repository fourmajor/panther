"""Optional, versioned creative inputs owned by an editable scene."""

import re


def normalize(value, game):
    if value is None:
        return {"schemaVersion": 1, "characterIds": [], "sourceKeys": [], "contextKeys": []}
    fields = {"schemaVersion", "characterIds", "sourceKeys", "contextKeys"}
    if not isinstance(value, dict) or set(value) != fields or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise ValueError("Invalid scene inputs")
    result = {"schemaVersion": 1}
    for field in fields - {"schemaVersion"}:
        items = value[field]
        if not isinstance(items, list) or len(items) > 50 or any(not isinstance(item, str) for item in items) or len(set(items)) != len(items):
            raise ValueError("Choose distinct scene characters and sources")
        for item in items:
            if field == "characterIds":
                if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", item):
                    raise ValueError("Choose a character from this game")
            elif not item.startswith(f"games/{game}/") or any(part in {"", ".", ".."} for part in item.split("/")) or any(ord(char) < 32 for char in item):
                raise ValueError("Choose a source from this game")
        result[field] = list(items)
    if set(result["sourceKeys"]) & set(result["contextKeys"]):
        raise ValueError("Choose each source only once")
    if len(result["sourceKeys"]) + len(result["contextKeys"]) > 40:
        raise ValueError("Choose up to 40 scene sources")
    return result


def asset_keys(record):
    inputs = record.get("generationInputs") or {}
    return [*inputs.get("sourceKeys", []), *inputs.get("contextKeys", []), *[take["assetKey"] for take in record.get("shotTakes", {}).values()]]
