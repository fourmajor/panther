"""Word-level placement of a dialogue take on its locked line.

Adapted from claudia_kit.sync (MIT License, (c) 2026 claudia.gallery contributors): log-mel features
every 10 ms and a subsequence DTW per spoken phrase. Models move the silences and run 10-25% fast or
slow, so sync is a map (line time -> clip time), not one offset.
"""

import subprocess

import numpy as np

SR, HOP, NFFT, NM = 16000, 160, 512, 40


def load_audio(path, start=0.0):
    cmd = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-ss",
        str(start),
        "-i",
        str(path),
        "-ac",
        "1",
        "-ar",
        str(SR),
    ]
    pcm = subprocess.run([*cmd, "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768


def melfb():
    def hz2m(f):
        return 2595 * np.log10(1 + f / 700)

    def m2hz(m):
        return 700 * (10 ** (m / 2595) - 1)

    pts = m2hz(np.linspace(hz2m(120), hz2m(6500), NM + 2))
    bins = np.fft.rfftfreq(NFFT, 1 / SR)
    fb = np.zeros((NM, len(bins)))
    for i in range(NM):
        lo, c, hi = pts[i : i + 3]
        fb[i] = np.clip(np.minimum((bins - lo) / (c - lo), (hi - bins) / (hi - c)), 0, None)
    return fb


def feats(x):
    n = 1 + (len(x) - NFFT) // HOP
    if n < 10:
        return np.zeros((0, NM))
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    m = np.log((np.abs(np.fft.rfft(x[idx] * np.hanning(NFFT), axis=1)) ** 2) @ melfb().T + 1e-9)
    return m - m.mean(1, keepdims=True)


def subdtw(r, t, step=0.06):
    """Align all of r somewhere inside t; returns the t frame for each r frame and the mean cost."""
    rn = r / (np.linalg.norm(r, axis=1, keepdims=True) + 1e-9)
    tn = t / (np.linalg.norm(t, axis=1, keepdims=True) + 1e-9)
    cost = 1 - rn @ tn.T
    n, m = cost.shape
    d = np.full((n, m), np.inf, np.float32)
    back = np.zeros((n, m), np.int8)
    d[0] = cost[0]
    for i in range(1, n):
        diag = np.r_[np.inf, d[i - 1, :-1]]
        up = d[i - 1] + step
        row = np.minimum(diag, up) + cost[i]
        back[i] = up < diag
        for j in range(1, m):
            v = row[j - 1] + cost[i, j] + step
            if v < row[j]:
                row[j] = v
                back[i, j] = 2
        d[i] = row
    j, i = int(np.argmin(d[-1])), n - 1
    total = float(d[-1, j]) / n
    path, count = np.zeros(n), np.zeros(n)
    while True:
        path[i] += j
        count[i] += 1
        if i == 0:
            break
        b = back[i, j]
        if b == 0:
            i, j = i - 1, j - 1
        elif b == 1:
            i -= 1
        else:
            j -= 1
        j = max(j, 0)
    return path / np.maximum(count, 1), total


def phrases(x, gap=0.25, floor_db=30):
    """Voiced spans of the line in seconds, split at silences longer than gap."""
    e = x[: len(x) // HOP * HOP].reshape(-1, HOP)
    db = 20 * np.log10(np.sqrt((e**2).mean(1)) + 1e-9)
    voiced = db > db.max() - floor_db
    spans, start, quiet = [], None, 0
    for k, v in enumerate(voiced):
        if v:
            start = k if start is None else start
            quiet = 0
        elif start is not None:
            quiet += 1
            if quiet * HOP / SR >= gap:
                spans.append((start / 100, (k - quiet + 1) / 100))
                start, quiet = None, 0
    if start is not None:
        spans.append((start / 100, len(voiced) / 100))
    return [(a, b) for a, b in spans if b - a >= 0.15]


def line_map(take, line_audio):
    """Knots [[line seconds, clip seconds], ...] and the mean phrase cost (0 = same sound)."""
    tx, rx = load_audio(take), load_audio(line_audio)
    t, r = feats(tx), feats(rx)
    knots, costs = [], []
    for a, b in phrases(rx):
        i0, i1 = max(0, int((a - 0.05) * 100)), min(len(r), int((b + 0.05) * 100))
        j0, j1 = max(0, i0 - 150), min(len(t), i1 + 150)
        if i1 - i0 < 15 or j1 <= j0:
            continue
        path, cost = subdtw(r[i0:i1], t[j0:j1])
        clip = (path + j0) / 100.0
        k = min(25, len(clip))
        smooth = np.convolve(
            np.pad(clip, (k // 2, k - 1 - k // 2), mode="edge"), np.ones(k) / k, mode="valid"
        )
        for q in list(range(0, i1 - i0, 10)) + [i1 - i0 - 1]:
            knots.append([round((i0 + q) / 100.0, 3), round(float(smooth[q]), 3)])
        costs.append(cost)
    knots.sort()
    clean = []
    for a, c in knots:
        if not clean or (a > clean[-1][0] + 1e-6 and c >= clean[-1][1]):
            if clean:
                rate = (c - clean[-1][1]) / (a - clean[-1][0])
                c = clean[-1][1] + min(1.4, max(0.7, rate)) * (a - clean[-1][0])
            clean.append([a, round(c, 3)])
    return clean, (round(float(np.mean(costs)), 3) if costs else None)


def at(knots, t):
    """Clip time for line time t, straight at 1x outside the knots."""
    if not knots:
        return t
    xs, ys = [a for a, _ in knots], [b for _, b in knots]
    if t < xs[0]:
        return ys[0] - (xs[0] - t)
    if t > xs[-1]:
        return ys[-1] + (t - xs[-1])
    return float(np.interp(t, xs, ys))
