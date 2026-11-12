#!/usr/bin/env node
// Generic procedural orchestra: instruments, sequencing helpers and hall reverb, all synthesised in code (no samples,
// no models). Loads <session>/score.js (the composition) and renders out/score.wav (48 kHz stereo) against
// out/timing.json. Instruments: string sections (detuned band-limited saws + vibrato), Karplus-Strong pizzicato/harp,
// additive brass (brightness follows envelope), woodwinds (additive + breath noise), modal timpani with pitch glide,
// formant choir (ah/oh/oo), inharmonic bells, celesta, bass drum, tam-tam/cymbal, and an 8-line FDN hall reverb.
// Usage: SESSION=sessions/<name> node tools/score-engine.js
const fs = require('fs'), path = require('path'), wav = require('./wav'), { session } = require('./session');
const SES = session(), root = SES.root, TM = JSON.parse(fs.readFileSync(path.join(root, 'out', 'timing.json'), 'utf8'));
const SR = 48000, TOTAL = TM.total, N = Math.ceil(TOTAL * SR), TAU = Math.PI * 2;
const dryL = new Float32Array(N), dryR = new Float32Array(N), wet = new Float32Array(N);
let seed = 1234567; const rng = () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
const midi = s => { const m = /^([A-G])([#b]?)(-?\d)$/.exec(s); if (!m) throw new Error('bad note ' + s); return { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }[m[1]] + (m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0) + 12 * (+m[3] + 1); };
const hz = n => 440 * Math.pow(2, ((typeof n === 'string' ? midi(n) : n) - 69) / 12);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
function put(buf, t, gain = 1, pan = 0, send = 0.3) { let s = Math.round(t * SR); const gl = gain * Math.cos((pan + 1) * Math.PI / 4), gr = gain * Math.sin((pan + 1) * Math.PI / 4);
  for (let i = 0; i < buf.length; i++, s++) { if (s < 0) continue; if (s >= N) break; const v = buf[i]; dryL[s] += v * gl; dryR[s] += v * gr; wet[s] += v * gain * send; } }
const blep = (t, dt) => t < dt ? (t /= dt, t + t - t * t - 1) : t > 1 - dt ? (t = (t - 1) / dt, t * t + t + t + 1) : 0;
function env(len, att, rel, curve = 1) { const e = new Float32Array(len), a = Math.max(1, att * SR), r = Math.max(1, rel * SR); for (let i = 0; i < len; i++) { let v = 1; if (i < a) v = Math.pow(Math.sin(i / a * Math.PI / 2), 2 * curve); if (i > len - r) v *= Math.pow(Math.cos((i - (len - r)) / r * Math.PI / 2), 2); e[i] = v; } return e; }
function lp(buf, fc, passes = 2) { const a = 1 - Math.exp(-TAU * fc / SR); for (let p = 0; p < passes; p++) { let y = 0; for (let i = 0; i < buf.length; i++) { y += a * (buf[i] - y); buf[i] = y; } } return buf; }
function hp(buf, fc) { const a = 1 - Math.exp(-TAU * fc / SR); let y = 0; for (let i = 0; i < buf.length; i++) { y += a * (buf[i] - y); buf[i] -= y; } return buf; }
function bpf(src, F, Q, out, g) { const w = TAU * F / SR, al = Math.sin(w) / (2 * Q), a0 = 1 + al, b0 = al / a0, a1 = -2 * Math.cos(w) / a0, a2 = (1 - al) / a0; let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  for (let i = 0; i < src.length; i++) { const x = src[i], y = b0 * x - b0 * x2 - a1 * y1 - a2 * y2; x2 = x1; x1 = x; y2 = y1; y1 = y; out[i] += y * g; } }
// ---------- instruments (each returns a mono buffer) ----------
function strings(note, dur, vel = 0.5, o = {}) { const f = hz(note), att = o.att ?? 0.22, rel = o.rel ?? 0.4, n = o.n ?? 4, len = Math.floor((dur + rel) * SR), out = new Float32Array(len);
  for (let v = 0; v < n; v++) { const det = Math.pow(2, (rng() - 0.5) * (o.detune ?? 22) / 1200), vr = 4.8 + rng() * 1.4, vp = rng() * TAU, vd = (o.vib ?? 0.0045) * (0.6 + 0.8 * rng()); let ph = rng();
    for (let i = 0; i < len; i++) { const t = i / SR, inc = f * det * (1 + vd * Math.min(1, t / 0.6) * Math.sin(TAU * vr * t + vp)) / SR; ph += inc; if (ph >= 1) ph -= 1; out[i] += 2 * ph - 1 - blep(ph, inc); } }
  lp(out, Math.min(9000, f * (o.bright ?? 3.2) * (0.55 + 0.9 * vel) + 300), 2); const e = env(len, att, rel), tr = o.trem ? 11 + rng() * 3 : 0, tp = rng() * TAU, cr = o.cresc ?? 0;
  for (let i = 0; i < len; i++) { let g = e[i] * vel / Math.sqrt(n) * 0.5; if (tr) g *= 0.35 + 0.65 * Math.pow(0.5 + 0.5 * Math.sin(TAU * tr * i / SR + tp), 2); if (cr) g *= Math.pow(clamp(i / len / 0.85), cr); out[i] *= g; } return out; }
function pluck(note, vel = 0.5, o = {}) { const f = hz(note), P = SR / f, Pi = Math.floor(P), fr = P - Pi, len = Math.floor((o.dur ?? 1.4) * SR), out = new Float32Array(len), d = new Float32Array(Pi + 2); let y = 0; const br = o.bright ?? 0.5;
  for (let i = 0; i < d.length; i++) { y += br * ((rng() * 2 - 1) - y); d[i] = y; } let idx = 0, prev = 0; const damp = o.damp ?? 0.996;
  for (let i = 0; i < len; i++) { const a = d[idx], b = d[(idx + 1) % d.length], s = a + fr * (b - a); out[i] = s; const nv = damp * 0.5 * (s + prev); prev = s; d[idx] = nv; idx = (idx + 1) % (Pi + 1); }
  const e = env(len, 0.001, 0.08); for (let i = 0; i < len; i++) out[i] *= e[i] * vel * 1.6; return out; }
function brass(note, dur, vel = 0.6, o = {}) { const f = hz(note), att = o.att ?? 0.09, rel = o.rel ?? 0.16, len = Math.floor((dur + rel) * SR), out = new Float32Array(len), K = Math.min(o.K ?? 20, Math.floor(7000 / f)), e = env(len, att, rel, 0.7), base = o.dark ?? 0.34, vp = rng() * TAU; let ph = rng() * TAU;
  for (let i = 0; i < len; i++) { const t = i / SR, scoop = 1 - 0.012 * Math.exp(-t / 0.035), vib = 1 + 0.003 * clamp((t - 0.35) / 0.5) * Math.sin(TAU * 5.3 * t + vp); ph += TAU * f * scoop * vib / SR; if (ph > TAU) ph -= TAU;
    const b = base + (0.58 - base * 0.4) * e[i] * vel * (o.cresc ? Math.pow(clamp(i / len / 0.8), o.cresc) : 1); let s = 0, a = 1; for (let k = 1; k <= K; k++) { s += a * Math.sin(k * ph) / Math.sqrt(k); a *= b; if (a < 1e-4) break; }
    out[i] = s * e[i] * vel * 0.3 * (o.cresc ? Math.pow(clamp(i / len / 0.8), o.cresc) : 1); } return out; }
function wind(note, dur, vel = 0.5, kind = 'flute', o = {}) { const f = hz(note), att = o.att ?? (kind === 'flute' ? 0.07 : 0.04), rel = o.rel ?? 0.12, len = Math.floor((dur + rel) * SR), out = new Float32Array(len), e = env(len, att, rel), vp = rng() * TAU;
  const H = kind === 'flute' ? [1, 0.42, 0.12, 0.05, 0.02] : kind === 'clar' ? [1, 0.04, 0.5, 0.03, 0.3, 0.02, 0.16, 0, 0.08] : kind === 'oboe' ? [0.6, 0.9, 1, 0.75, 0.5, 0.3, 0.2, 0.12, 0.06] : [1, 0.7, 0.45, 0.5, 0.25, 0.2, 0.1, 0.08]; let ph = 0;
  const nz = new Float32Array(len); for (let i = 0; i < len; i++) nz[i] = rng() * 2 - 1; const br = new Float32Array(len); bpf(nz, Math.min(9000, f * (kind === 'flute' ? 2.5 : 4)), 1.2, br, kind === 'flute' ? 0.5 : 0.12);
  for (let i = 0; i < len; i++) { const t = i / SR, vib = 1 + (kind === 'clar' ? 0.0012 : 0.004) * clamp((t - 0.25) / 0.4) * Math.sin(TAU * 5.1 * t + vp); ph += TAU * f * vib / SR; if (ph > TAU) ph -= TAU; let s = 0; for (let k = 0; k < H.length; k++) if ((k + 1) * f < 11000) s += H[k] * Math.sin((k + 1) * ph);
    out[i] = (s * 0.3 + br[i] * (0.6 + 0.4 * e[i])) * e[i] * vel * 0.55; } return out; }
function timp(note, vel = 0.7, o = {}) { const f = hz(note), len = Math.floor((o.dur ?? 2.2) * SR), out = new Float32Array(len), R = [1, 1.504, 1.742, 2.0, 2.245, 2.494, 2.8], D = [1.5, 1.0, 0.7, 0.55, 0.4, 0.3, 0.22], A = [1, 0.62, 0.34, 0.3, 0.2, 0.13, 0.08];
  for (let m = 0; m < R.length; m++) { let ph = rng() * 0.3; const fm = f * R[m]; for (let i = 0; i < len; i++) { const t = i / SR; ph += TAU * fm * (1 + 0.07 * vel * Math.exp(-t / 0.035)) / SR; out[i] += A[m] * Math.sin(ph) * Math.exp(-t / (D[m] * (o.ring ?? 1))); } }
  let y = 0; for (let i = 0; i < Math.min(len, SR * 0.05); i++) { y += 0.06 * ((rng() * 2 - 1) - y); out[i] += y * 5 * Math.exp(-i / SR / 0.012) * vel; }
  for (let i = 0; i < len; i++) out[i] *= vel * 0.42 * Math.min(1, i / 40); return out; }
function bdrum(vel = 0.8) { const len = SR * 1.6, out = new Float32Array(len); let ph = 0, y = 0; for (let i = 0; i < len; i++) { const t = i / SR; ph += TAU * (36 + 46 * Math.exp(-t / 0.045)) / SR; y += 0.03 * ((rng() * 2 - 1) - y); out[i] = (Math.sin(ph) * Math.exp(-t / 0.5) + y * 6 * Math.exp(-t / 0.02)) * vel * 0.9 * Math.min(1, i / 30); } return out; }
function choir(note, dur, vel = 0.4, vowel = 'ah', o = {}) { const f = hz(note), att = o.att ?? 0.55, rel = o.rel ?? 0.8, len = Math.floor((dur + rel) * SR), src = new Float32Array(len), n = o.n ?? 5;
  for (let v = 0; v < n; v++) { const det = Math.pow(2, (rng() - 0.5) * 36 / 1200), vr = 4.6 + rng() * 1.3, vp = rng() * TAU, dr = rng() * TAU; let ph = rng();
    for (let i = 0; i < len; i++) { const t = i / SR, inc = f * det * (1 + 0.006 * Math.sin(TAU * vr * t + vp) + 0.003 * Math.sin(TAU * 0.37 * t + dr)) / SR; ph += inc; if (ph >= 1) ph -= 1; src[i] += 2 * ph - 1 - blep(ph, inc); } }
  for (let i = 0; i < len; i++) src[i] += (rng() * 2 - 1) * 0.25;
  const F = vowel === 'ah' ? [[720, 1], [1150, 0.6], [2700, 0.28], [3400, 0.16]] : vowel === 'oh' ? [[440, 1], [800, 0.5], [2650, 0.14], [3300, 0.08]] : [[320, 1], [760, 0.3], [2400, 0.1], [3300, 0.06]];
  const out = new Float32Array(len); for (const [fc, g] of F) bpf(src, fc * (f > 380 ? 1.12 : 1), fc / (70 + fc * 0.035), out, g);
  const e = env(len, att, rel), cr = o.cresc ?? 0; for (let i = 0; i < len; i++) out[i] *= e[i] * vel * 2.4 / Math.sqrt(n) * (cr ? Math.pow(clamp(i / len / 0.85), cr) : 1); return out; }
function bell(note, vel = 0.5, o = {}) { const f = hz(note), len = Math.floor((o.dur ?? 5) * SR), out = new Float32Array(len), R = [0.5, 1, 1.183, 1.506, 2, 2.514, 2.662, 3.011, 4.166, 5.433], A = [0.5, 1, 0.55, 0.4, 0.7, 0.3, 0.25, 0.3, 0.18, 0.1];
  for (let m = 0; m < R.length; m++) { const fm = f * R[m] * (1 + (o.sour ?? 0) * (rng() - 0.5)); if (fm > 14000) continue; const dec = (o.ring ?? 2.6) / Math.pow(R[m], 0.9), p = rng() * TAU, bt = 1 + (rng() - 0.5) * 0.004; for (let i = 0; i < len; i++) { const t = i / SR; out[i] += A[m] * (Math.sin(TAU * fm * t + p) + 0.6 * Math.sin(TAU * fm * bt * t)) * Math.exp(-t / dec); } }
  for (let i = 0; i < len; i++) out[i] *= vel * 0.16 * Math.min(1, i / 48) * (o.flutter ? 0.6 + 0.4 * Math.sin(TAU * (6 + 3 * Math.sin(i / SR * 2)) * i / SR) : 1); return out; }
function celesta(note, vel = 0.4) { const f = hz(note), len = SR * 1.3, out = new Float32Array(len); for (let i = 0; i < len; i++) { const t = i / SR; out[i] = (Math.sin(TAU * f * t) * Math.exp(-t / 0.5) + 0.3 * Math.sin(TAU * f * 3.01 * t) * Math.exp(-t / 0.12) + 0.15 * Math.sin(TAU * f * 6.3 * t) * Math.exp(-t / 0.05)) * vel * 0.4 * Math.min(1, i / 30); } return out; }
function wash(dur, vel = 0.4, o = {}) { const len = Math.floor(dur * SR), out = new Float32Array(len), lo = o.lo ?? 90, hi = o.hi ?? 3200, peak = o.peak ?? 0.7; // tam-tam / cymbal: dense inharmonic partials + noise
  for (let m = 0; m < 46; m++) { const fm = lo * Math.pow(hi / lo, rng()), p = rng() * TAU, a = 0.3 + rng(); for (let i = 0; i < len; i++) out[i] += a * Math.sin(TAU * fm * i / SR + p + 0.8 * Math.sin(TAU * fm * 0.503 * i / SR)); }
  const nz = new Float32Array(len); for (let i = 0; i < len; i++) nz[i] = rng() * 2 - 1; hp(nz, o.hpf ?? 1500);
  for (let i = 0; i < len; i++) { const u = i / len, e = u < peak ? Math.pow(u / peak, o.rise ?? 2) : Math.exp(-(u - peak) / (1 - peak) * 4); out[i] = (out[i] * 0.03 + nz[i] * (o.noise ?? 0.25)) * e * vel; } return out; }
// ---------- sequencing helpers ----------
const SEC = { vn1: [-0.45, 0.34], vn2: [-0.2, 0.34], va: [0.15, 0.32], vc: [0.4, 0.3], cb: [0.5, 0.26], hn: [-0.28, 0.4], tb: [0.32, 0.36], tp: [0.12, 0.36], ww: [-0.06, 0.34], ww2: [0.1, 0.34], tm: [-0.1, 0.38], ch: [0, 0.5], pc: [-0.3, 0.45], hp: [-0.35, 0.3] };
const P = (sec, buf, t, g = 1) => put(buf, t, g, SEC[sec][0], SEC[sec][1]);
// seq: notes = [[name|null, beats, vel?]...]; fn(note, durSeconds, vel) -> buffer
function seq(sec, t, beat, notes, fn, vel = 0.5, legato = 1) { for (const [nm, b, v] of notes) { if (nm) P(sec, fn(nm, b * beat * legato, v ?? vel), t); t += b * beat; } return t; }
const chord = (sec, t, names, dur, vel, fn) => names.forEach(nm => P(sec, fn(nm, dur, vel), t));
const S = Object.fromEntries(TM.shots.map(s => [s.name, s])), Bt = Object.fromEntries(TM.beats.map(b => [b.name, b.t])), Ln = Object.fromEntries(TM.lines.map(l => [l.id, l]));
const hit = (t, v = 1) => { P('tm', bdrum(0.9 * v), t); P('tm', timp('D2', 0.9 * v), t); };
// ---------- composition ----------
const api = { S, Bt, Ln, TM, TOTAL, SR, P, put, seq, chord, hit, midi, hz, rng, SEC, strings, pluck, brass, wind, timp, bdrum, choir, bell, celesta, wash };
const scoreFile = path.join(SES.dir, 'score.js');
if (fs.existsSync(scoreFile)) require(scoreFile)(api);
else { // fallback when a session has no score.js: a pedal per shot, a hit on every cut and a bell on every beat
  for (const s of TM.shots) { hit(s.start, 0.6); chord('vc', s.start, ['D2', 'A2', 'D3'], s.end - s.start, 0.3, (n, d, v) => strings(n, d, v, { att: 0.6, rel: 0.8 })); }
  for (const b of TM.beats) P('pc', bell('D5', 0.4), b.t);
}
// ================= hall reverb (8-line FDN, Householder feedback, damped) =================
function reverb(x) { const LEN = [1553, 1871, 2203, 2609, 3011, 3463, 3907, 4409], d = LEN.map(n => new Float32Array(n)), idx = new Int32Array(8), lpf = new Float32Array(8), g = LEN.map(n => Math.pow(10, -3 * n / SR / 2.9)), oL = new Float32Array(x.length), oR = new Float32Array(x.length);
  const pre = Math.floor(0.028 * SR), ap = [347, 113, 37].map(n => ({ b: new Float32Array(n), i: 0 })); const o = new Float32Array(8);
  for (let i = 0; i < x.length; i++) { let v = i >= pre ? x[i - pre] : 0; for (const a of ap) { const bo = a.b[a.i], y = -0.6 * v + bo; a.b[a.i] = v + 0.6 * y; a.i = (a.i + 1) % a.b.length; v = y; }
    let sum = 0; for (let k = 0; k < 8; k++) { o[k] = d[k][idx[k]]; sum += o[k]; } sum *= 0.25;
    for (let k = 0; k < 8; k++) { let fb = (o[k] - sum) * g[k]; lpf[k] += 0.42 * (fb - lpf[k]); d[k][idx[k]] = v + lpf[k]; idx[k] = (idx[k] + 1) % LEN[k]; }
    oL[i] = o[0] - o[2] + o[4] - o[6]; oR[i] = o[1] - o[3] + o[5] - o[7]; } return [oL, oR]; }
const [wl, wr] = reverb(wet);
// dynamics: -3 dB arrangement dip under caption-only lines; lines with a voice clip are ducked by the sidechain in tools/mix.js
const duck = new Float32Array(N).fill(1), depth = 1 - Math.pow(10, -3 / 20);
for (const l of TM.lines) { if (l.hasVoice) continue; const a = Math.floor((l.start - 0.3) * SR), b = Math.floor((l.end + 0.45) * SR); for (let i = Math.max(0, a); i < Math.min(N, b); i++) { const u = Math.min(1, (i - a) / (0.3 * SR), (b - i) / (0.45 * SR)), w = u * u * (3 - 2 * u); duck[i] = Math.min(duck[i], 1 - depth * w); } }
let peak = 0; const L = new Float32Array(N), R = new Float32Array(N);
for (let i = 0; i < N; i++) { const t = i / SR, f = Math.min(1, t / 0.4) * Math.min(1, Math.max(0, (TOTAL - t) / 1.4)); L[i] = Math.tanh((dryL[i] + wl[i] * 0.55) * duck[i] * f * 0.9); R[i] = Math.tanh((dryR[i] + wr[i] * 0.55) * duck[i] * f * 0.9); peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i])); }
const gn = 0.7 / Math.max(peak, 1e-6); for (let i = 0; i < N; i++) { L[i] *= gn; R[i] *= gn; }
wav.write(path.join(root, 'out', 'score.wav'), L, R, SR);
console.log(`score: ${TOTAL.toFixed(2)}s -> out/score.wav (pre-normalise peak ${peak.toFixed(3)})`);
