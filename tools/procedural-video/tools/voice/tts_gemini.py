#!/usr/bin/env python3
"""Gemini TTS via OpenRouter -> one 24 kHz mono 16-bit WAV per line in lines.json.

Key: read from env OPENROUTER_API_KEY (never hardcoded/printed).
Usage: tts_gemini.py lines.json voices.json outdir [--only L01,L02] [--cap-usd 1.0]
voices.json maps speaker -> {"voice": "<Gemini preset>", "instructions": "<tone/pace>"}
Writes outdir/<id>.wav and outdir/tts-report.json (generation ids, cost, durations).
"""
import json, os, sys, time, wave, urllib.request, urllib.error, argparse

API = "https://openrouter.ai/api/v1"
MODEL = os.environ.get("TTS_MODEL", "google/gemini-3.8-flash-tts")
VERBATIM = ("Read the text exactly verbatim, word for word; do not add, drop or change any words "
            "and do not speak these directions aloud. ")

def req(url, key, body=None, timeout=120):
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                               headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    return urllib.request.urlopen(r, timeout=timeout)

def gen_cost(key, gid):
    for _ in range(8):
        try:
            with req(f"{API}/generation?id={gid}", key, timeout=30) as r:
                d = json.load(r)["data"]
                return float(d.get("total_cost") or 0.0)
        except urllib.error.HTTPError:
            time.sleep(2)
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lines"); ap.add_argument("voices"); ap.add_argument("outdir")
    ap.add_argument("--only", default=""); ap.add_argument("--cap-usd", type=float, default=1.0)
    a = ap.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key: sys.exit("OPENROUTER_API_KEY not set")
    lines = json.load(open(a.lines)); vmap = json.load(open(a.voices))
    os.makedirs(a.outdir, exist_ok=True)
    rp = os.path.join(a.outdir, "tts-report.json")
    report = json.load(open(rp)) if os.path.exists(rp) else {"model": MODEL, "lines": {}, "total_cost_usd": 0.0}
    only = set(x for x in a.only.split(",") if x)
    for ln in lines:
        if only and ln["id"] not in only: continue
        v = vmap.get(ln["speaker"]) or vmap["_default"]
        spent = sum((x.get("cost_usd") or 0) for x in report["lines"].values())
        if spent >= a.cap_usd * 0.9: sys.exit(f"stopping: spent ${spent:.4f} near cap ${a.cap_usd}")
        instr = VERBATIM + v["instructions"] + (" " + ln["delivery"] if ln.get("delivery") else "")
        body = {"model": MODEL, "input": ln["text"], "voice": v["voice"], "instructions": instr,
                "response_format": "pcm"}
        if ln.get("seed") is not None: body["provider"] = {"options": {"google-ai-studio": {"seed": ln["seed"]}}}
        try:
            with req(f"{API}/audio/speech", key, body) as r:
                pcm = r.read(); gid = r.headers.get("x-generation-id")
        except urllib.error.HTTPError as e:
            print(ln["id"], "HTTP", e.code, e.read()[:300].decode(errors="replace")); continue
        out = os.path.join(a.outdir, f"{ln['id']}.wav")
        with wave.open(out, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
        dur = len(pcm) / 2 / 24000
        cost = gen_cost(key, gid) if gid else None
        report["lines"][ln["id"]] = {"speaker": ln["speaker"], "voice": v["voice"], "generation_id": gid,
                                     "duration_s": round(dur, 3), "cost_usd": cost, "text": ln["text"]}
        report["total_cost_usd"] = round(sum((x.get("cost_usd") or 0) for x in report["lines"].values()), 6)
        json.dump(report, open(rp, "w"), indent=1)
        print(f"{ln['id']} {ln['speaker']:<14} {v['voice']:<12} {dur:5.2f}s cost={cost}")
    print("total_cost_usd", report["total_cost_usd"])

if __name__ == "__main__": main()
