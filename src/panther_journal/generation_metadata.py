"""Explicit creation metadata. Omitted facts mean unknown, never inferred from appearance."""


def unknown():
    return {"schemaVersion": 1, "method": "unknown", "cost": {"status": "unknown"}}


def subscription(tool="Codex CLI", *, execution="local"):
    # Codex's configured default model can change; do not claim an unobserved model version.
    return {"schemaVersion": 1, "method": "ai-assisted", "provider": "OpenAI",
            "inference": "remote", "execution": execution, "tool": tool,
            "cost": {"status": "subscription"}}


def local(tool, *, method="procedural"):
    return {"schemaVersion": 1, "method": method, "tool": tool, "execution": "local",
            "inference": "local" if method == "ai" else "not-applicable",
            "cost": {"status": "not-applicable"}}


def fal(endpoint, request_id, billed=None):
    models = {
        "fal-ai/veo3.1/fast": "Veo 3.1 Fast",
        "fal-ai/kling-video/v3/pro/text-to-video": "Kling 3 Pro",
        "bytedance/seedance-2.0/text-to-video": "Seedance 2.0",
        "fal-ai/veo3.1/fast/image-to-video": "Veo 3.1 Fast",
        "fal-ai/kling-video/v3/pro/image-to-video": "Kling 3 Pro",
        "bytedance/seedance-2.0/image-to-video": "Seedance 2.0",
    }
    result = {"schemaVersion": 1, "method": "ai", "provider": "fal",
              "inference": "remote", "execution": "remote", "cost": {"status": "unknown"}}
    if endpoint in models:
        result["model"] = models[endpoint]
    if billed is not None:
        result["cost"] = {"status": "billed", "amount": str(billed), "currency": "USD"}
        result["evidence"] = f"fal billing event {request_id}"
    return result
