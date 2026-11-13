// Lip-sync driver. Turns the word timings in out/timing.json (Whisper-aligned, canonical text) plus each clip's
// amplitude envelope (out/envelopes.json, written by tools/envelope.js) into a mouth state for any speaker at time t:
//   { active, jaw 0..1, wide 0..1, round 0..1, lowerIn 0..1, emph 0..1 }
// Visemes are derived from spelling (vowel groups open/round/spread the mouth, m/b/p close it, f/v tuck the lower
// lip), spread across each word's spoken span, and gated/scaled by the measured loudness so silences close the mouth.
import { clamp, lerp, sstep } from './util.js';
const VIS = { a: [0.85, 0.25, 0], e: [0.5, 0.6, 0], i: [0.32, 0.8, 0], o: [0.7, 0, 0.7], u: [0.35, 0, 1], y: [0.3, 0.7, 0],
  m: [0, 0, 0], b: [0, 0, 0], p: [0, 0, 0], f: [0.12, 0.1, 0, 1], v: [0.12, 0.1, 0, 1], w: [0.25, 0, 0.9], r: [0.3, 0, 0.35], l: [0.35, 0.2, 0], t: [0.2, 0.3, 0], d: [0.22, 0.3, 0], n: [0.2, 0.25, 0],
  s: [0.14, 0.45, 0], z: [0.14, 0.45, 0], c: [0.25, 0.3, 0], k: [0.3, 0.2, 0], g: [0.3, 0.15, 0], h: [0.4, 0.15, 0], j: [0.22, 0, 0.5], q: [0.3, 0, 0.6], x: [0.2, 0.4, 0] };
const DI = { oo: [0.35, 0, 1], ou: [0.6, 0, 0.75], ow: [0.6, 0, 0.8], ee: [0.3, 0.9, 0], ea: [0.4, 0.75, 0], th: [0.2, 0.25, 0], sh: [0.2, 0, 0.6], ch: [0.2, 0, 0.55], wh: [0.3, 0, 0.9], ai: [0.6, 0.55, 0], ay: [0.6, 0.55, 0], oa: [0.65, 0, 0.7] };
export function visemes(word) { const w = word.toLowerCase().replace(/[^a-z]/g, ''), out = [];
  for (let i = 0; i < w.length; i++) { const d = DI[w.slice(i, i + 2)]; if (d) { out.push(d); i++; continue; } if (w[i] === 'e' && i === w.length - 1 && w.length > 3) continue; const v = VIS[w[i]]; if (v) out.push(v); }
  return out.length ? out : [[0.3, 0.2, 0]]; }
// TM: timing.json; ENV: { <lineId>: { rate, v: [...] } } or null
export function makeSpeech(TM, ENV) {
  const lines = TM.lines.map(l => ({ ...l, vis: l.words.map(w => visemes(w.w)), env: ENV && ENV[l.id] ? ENV[l.id] : null }));
  const envAt = (l, t) => { if (!l.env) return 0.7; const x = (t - l.start + (l.clipOffset || 0)) * l.env.rate, i = Math.floor(x), v = l.env.v; if (i < 0 || i >= v.length - 1) return 0; return lerp(v[i], v[i + 1], x - i); };
  const NONE = { active: false, jaw: 0, wide: 0, round: 0, lowerIn: 0, emph: 0 };
  const shape = (l, t) => { let j = 0, wd = 0, rd = 0, li = 0; const W = l.words;
    for (let k = 0; k < W.length; k++) { const w = W[k], e = Math.max(w.e, w.t + 0.08); if (t < w.t - 0.06 || t > e + 0.08) continue; const vs = l.vis[k], x = clamp((t - w.t) / (e - w.t)) * vs.length - 0.5, i0 = clamp(Math.floor(x), 0, vs.length - 1), i1 = clamp(i0 + 1, 0, vs.length - 1), fr = sstep(0, 1, clamp(x - i0)), a = vs[i0], b = vs[i1];
      const g = sstep(w.t - 0.06, w.t + 0.03, t) * sstep(e + 0.08, e - 0.02, t); j = Math.max(j, lerp(a[0], b[0], fr) * g); wd = Math.max(wd, lerp(a[1], b[1], fr) * g); rd = Math.max(rd, lerp(a[2], b[2], fr) * g); li = Math.max(li, lerp(a[3] || 0, b[3] || 0, fr) * g); }
    return [j, wd, rd, li]; };
  return (t, speaker) => { const l = lines.find(x => x.speaker === speaker && t >= x.start - 0.12 && t <= x.end + 0.15); if (!l) return NONE;
    const [j, wd, rd, li] = shape(l, t), a = (envAt(l, t - 0.02) + envAt(l, t) + envAt(l, t + 0.02)) / 3, gate = sstep(0.04, 0.16, a), loud = lerp(0.55, 1.2, clamp(a));
    return { active: true, jaw: clamp((j * 0.75 + 0.25 * a) * gate * loud), wide: wd * gate, round: rd * gate, lowerIn: li * gate, emph: sstep(0.6, 0.95, a), line: l.id }; };
}
