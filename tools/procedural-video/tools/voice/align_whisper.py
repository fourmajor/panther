#!/usr/bin/env python3
"""Word-level alignment of each voice clip with Whisper via OpenRouter /audio/transcriptions.
Usage: align_whisper.py lines.json voicedir  -> voicedir/alignment.json {id: {"words":[{word,start,end}], "text":...}}
Key from env OPENROUTER_API_KEY. Model: env STT_MODEL (default openai/whisper-large-v3-turbo)."""
import json, os, sys, base64, urllib.request, urllib.error
API = "https://openrouter.ai/api/v1"; MODEL = os.environ.get("STT_MODEL", "openai/whisper-large-v3-turbo")
key = os.environ.get("OPENROUTER_API_KEY") or sys.exit("OPENROUTER_API_KEY not set")
lines = json.load(open(sys.argv[1])); vd = sys.argv[2]; out = {}
for ln in lines:
    p = os.path.join(vd, ln["id"] + ".wav")
    if not os.path.exists(p): continue
    body = {"model": MODEL, "input_audio": {"data": base64.b64encode(open(p, "rb").read()).decode(), "format": "wav"},
            "language": "en", "temperature": 0, "response_format": "verbose_json", "timestamp_granularities": ["word"]}
    r = urllib.request.Request(f"{API}/audio/transcriptions", data=json.dumps(body).encode(),
                               headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(r, timeout=90))
    except urllib.error.HTTPError as e:
        print(ln["id"], "HTTP", e.code, e.read()[:300].decode(errors="replace")); continue
    out[ln["id"]] = {"text": d.get("text"), "words": d.get("words") or [], "usage": d.get("usage")}
    print(ln["id"], len(out[ln["id"]]["words"]), "words |", (d.get("text") or "").strip()[:80])
json.dump(out, open(os.path.join(vd, "alignment.json"), "w"), indent=1)
