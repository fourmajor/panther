#!/usr/bin/env node
// Mixes out/score.wav with the session's voice clips (placed from out/timing.json) -> out/mix.wav.
//  - sidechain ducking: an envelope follower on the dialogue bus (look-ahead, fast attack, slow release) pulls the
//    score down by up to DUCK_DB (default 9 dB) while someone is speaking;
//  - master: BS.1770 integrated loudness to TARGET_LUFS (default -14), 4x-oversampled true-peak limiting to
//    CEILING_DBTP (default -1.2 dBTP).
// Usage: SESSION=sessions/<name> node tools/mix.js
const fs = require('fs'), path = require('path'), cp = require('child_process'), wav = require('./wav'), { session } = require('./session');
const SES = session(), root = SES.root, TM = JSON.parse(fs.readFileSync(path.join(root, 'out', 'timing.json'), 'utf8')), SR = 48000;
const FF = fs.existsSync('/opt/homebrew/bin/ffmpeg') ? '/opt/homebrew/bin/ffmpeg' : 'ffmpeg';
const DUCK_DB = +(process.env.DUCK_DB || 9), TARGET = +(process.env.TARGET_LUFS || -14), CEIL_DB = +(process.env.CEILING_DBTP || -1.2);
const sc = wav.read(path.join(root, 'out', 'score.wav')), N = sc.L.length, L = Float32Array.from(sc.L), R = Float32Array.from(sc.R);
const vL = new Float32Array(N), vR = new Float32Array(N); let voiced = 0;
for (const l of TM.lines) { const f = path.join(SES.dir, l.audio || `voices/${l.id}.wav`); if (!fs.existsSync(f)) continue;
  const tmp = path.join(root, 'out', `.voice-${l.id}.wav`); cp.execFileSync(FF, ['-y', '-v', 'error', '-i', f, '-ar', String(SR), '-ac', '2', '-c:a', 'pcm_s16le', tmp]); const v = wav.read(tmp); fs.unlinkSync(tmp);
  const i0 = Math.floor((l.clipOffset || 0) * SR), i1 = Math.min(v.L.length, i0 + Math.ceil((l.end - l.start) * SR)); let rms = 0; for (let i = i0; i < i1; i++) rms += v.L[i] * v.L[i]; rms = Math.sqrt(rms / Math.max(1, i1 - i0)); const g = rms > 1e-5 ? 0.12 / rms : 1;   // level-match clips on their spoken span
  const s0 = Math.round((l.start - (l.clipOffset || 0)) * SR); for (let i = Math.max(0, -s0); i < v.L.length && s0 + i < N; i++) { vL[s0 + i] += v.L[i] * g; vR[s0 + i] += v.R[i] * g; }
  voiced++; }
// sidechain: dialogue level -> smoothed gain reduction on the score
const duck = new Float32Array(N).fill(1); let maxGR = 0;
if (voiced) { const win = Math.floor(0.03 * SR), lev = new Float32Array(N); let acc = 0; for (let i = 0; i < N; i++) { acc += vL[i] * vL[i]; if (i >= win) acc -= vL[i - win] * vL[i - win]; lev[i] = Math.sqrt(Math.max(acc, 0) / win); }
  const hold = Math.floor(0.35 * SR), key = new Float32Array(N); let pk = 0, cnt = 0;   // peak-hold bridges the gaps between words
  for (let i = 0; i < N; i++) { if (lev[i] >= pk) { pk = lev[i]; cnt = hold; } else if (--cnt <= 0) pk = Math.max(lev[i], pk * 0.9997); key[i] = pk; }
  const la = Math.floor(0.12 * SR), aA = 1 - Math.exp(-1 / (0.09 * SR)), aR = 1 - Math.exp(-1 / (0.45 * SR)); let g = 0;
  for (let i = 0; i < N; i++) { const k = key[Math.min(N - 1, i + la)], want = Math.min(1, Math.max(0, (k - 0.004) / 0.03)); g += (want > g ? aA : aR) * (want - g); maxGR = Math.max(maxGR, g * DUCK_DB); duck[i] = Math.pow(10, -DUCK_DB * g / 20); } }
for (let i = 0; i < N; i++) { L[i] = L[i] * duck[i] + vL[i]; R[i] = R[i] * duck[i] + vR[i]; }
// integrated loudness (ITU-R BS.1770 K-weighting, 400 ms blocks, absolute + relative gating)
function kweight(x) { const y = new Float32Array(x.length); const st = [[1.53512485958697, -2.69169618940638, 1.19839281085285, -1.69065929318241, 0.73248077421585], [1.0, -2.0, 1.0, -1.99004745483398, 0.99007225036621]]; let src = x;
  for (const [b0, b1, b2, a1, a2] of st) { let x1 = 0, x2 = 0, y1 = 0, y2 = 0; const o = new Float32Array(x.length); for (let i = 0; i < x.length; i++) { const v = b0 * src[i] + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2; x2 = x1; x1 = src[i]; y2 = y1; y1 = v; o[i] = v; } src = o; } return src; }
function lufs(l, r) { const kl = kweight(l), kr = kweight(r), bl = Math.floor(0.4 * SR), hop = Math.floor(0.1 * SR), z = []; for (let s = 0; s + bl <= l.length; s += hop) { let e = 0; for (let i = s; i < s + bl; i++) e += kl[i] * kl[i] + kr[i] * kr[i]; z.push(e / bl); }
  const lk = e => -0.691 + 10 * Math.log10(e + 1e-12); let g = z.filter(e => lk(e) > -70); if (!g.length) return -70; const rel = lk(g.reduce((a, b) => a + b, 0) / g.length) - 10; g = g.filter(e => lk(e) > rel); return lk(g.reduce((a, b) => a + b, 0) / g.length); }
// 4x oversampled peak estimate (windowed-sinc interpolation) for true-peak limiting
const TAPS = 12, PH = [1, 2, 3].map(p => { const h = new Float32Array(TAPS * 2); for (let k = -TAPS + 1; k <= TAPS; k++) { const x = k - p / 4, w = 0.5 + 0.5 * Math.cos(Math.PI * x / TAPS); h[k + TAPS - 1] = (Math.abs(x) < 1e-9 ? 1 : Math.sin(Math.PI * x) / (Math.PI * x)) * w; } return h; });
function truePeakEnv(x, env) { for (let i = 0; i < x.length; i++) { let m = Math.abs(x[i]); if (m > 0.25) for (const h of PH) { let s = 0; for (let k = 0; k < TAPS * 2; k++) { const j = i + k - TAPS + 1; if (j >= 0 && j < x.length) s += x[j] * h[k]; } m = Math.max(m, Math.abs(s)); } if (m > env[i]) env[i] = m; } }
const CEIL = Math.pow(10, CEIL_DB / 20); let gain = Math.pow(10, (TARGET - lufs(L, R)) / 20), oL, oR;
for (let pass = 0; pass < 3; pass++) { // gain -> look-ahead true-peak limiter -> re-measure and trim
  oL = new Float32Array(N); oR = new Float32Array(N); for (let i = 0; i < N; i++) { oL[i] = L[i] * gain; oR[i] = R[i] * gain; }
  const env = new Float32Array(N); truePeakEnv(oL, env); truePeakEnv(oR, env);
  const la = Math.floor(0.004 * SR), need = new Float32Array(N).fill(1); for (let i = 0; i < N; i++) if (env[i] > CEIL) { const g = CEIL / env[i]; for (let k = Math.max(0, i - la); k <= Math.min(N - 1, i + 2); k++) if (g < need[k]) need[k] = g; }
  let cur = 1; const aA = 1 - Math.exp(-1 / (0.0012 * SR)), aR = 1 - Math.exp(-1 / (0.12 * SR)); for (let i = 0; i < N; i++) { const w = need[i]; cur += (w < cur ? aA : aR) * (w - cur); const g = Math.min(cur, need[i]); oL[i] *= g; oR[i] *= g; }
  const err = TARGET - lufs(oL, oR); if (Math.abs(err) < 0.05) break; gain *= Math.pow(10, err / 20); }
const chk = new Float32Array(N); truePeakEnv(oL, chk); truePeakEnv(oR, chk); let pk = 0; for (let i = 0; i < N; i++) pk = Math.max(pk, chk[i]);
wav.write(path.join(root, 'out', 'mix.wav'), oL, oR, SR);
console.log(`mix: ${voiced} voice clip(s), sidechain duck up to ${maxGR.toFixed(1)} dB, ${lufs(oL, oR).toFixed(1)} LUFS, true peak ~${(20 * Math.log10(pk)).toFixed(2)} dBTP -> out/mix.wav`);
