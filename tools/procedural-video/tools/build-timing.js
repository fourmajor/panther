#!/usr/bin/env node
// Audio-first timing. Resolves <session>/timeline.json + lines.json into out/timing.json:
//  - each line's length comes from its voice clip (<session>/voices/<id>.wav) when present, else target_duration;
//  - speech in/out and per-word times come from Whisper word timestamps (<session>/voices/alignment.json), mapped
//    back onto the canonical lines.json text (the caption always shows the canonical words);
//  - shot boundaries re-flow around the lines; story beats resolve to absolute times.
// Usage: SESSION=sessions/<name> node tools/build-timing.js
const fs = require('fs'), path = require('path'), cp = require('child_process'), { session } = require('./session');
const SES = session(), root = SES.root;
const TL = JSON.parse(fs.readFileSync(path.join(SES.dir, 'timeline.json'), 'utf8'));
const LINES = JSON.parse(fs.readFileSync(path.join(SES.dir, 'lines.json'), 'utf8'));
const alignFile = path.join(SES.dir, 'voices', 'alignment.json'), ALIGN = fs.existsSync(alignFile) ? JSON.parse(fs.readFileSync(alignFile, 'utf8')) : {};
const GAP = 0.3, TAIL = 0.45, LEAD = 0.25, END_TAIL = 1.7;
const bin = n => fs.existsSync('/opt/homebrew/bin/' + n) ? '/opt/homebrew/bin/' + n : n;
function probe(f) { try { return parseFloat(cp.execFileSync(bin('ffprobe'), ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f]).toString()); } catch (e) { return NaN; } }
// speech span of a clip from its audio alone (leading/trailing silence)
function span(f, d) { let a = 0, b = d;
  try { const r = cp.spawnSync(bin('ffmpeg'), ['-hide_banner', '-i', f, '-af', 'silencedetect=noise=-42dB:d=0.1', '-f', 'null', '-'], { encoding: 'utf8' }).stderr;
    const st = [...r.matchAll(/silence_start: ([-\d.]+)/g)].map(m => +m[1]), en = [...r.matchAll(/silence_end: ([\d.]+)/g)].map(m => +m[1]);
    if (st.length && st[0] <= 0.06 && en[0]) a = Math.max(0, en[0] - 0.05);
    if (st.length && (en.length < st.length || en[en.length - 1] >= d - 0.02)) b = Math.min(d, st[st.length - 1] + 0.12);
  } catch (e) {}
  return b - a > 0.2 ? [a, b] : [0, d]; }
// Map recognised words (with times) onto the canonical tokens: LCS alignment on normalised words; canonical tokens
// with no match (e.g. a contraction the recogniser expanded) take the times of the unmatched recognised words in the
// same gap, or are interpolated between their neighbours.
const norm = w => w.toLowerCase().replace(/[^a-z0-9']/g, '').replace(/'/g, '');
function mapWords(text, rec, a, b) {
  const can = text.split(/\s+/).filter(Boolean), cn = can.map(norm), rn = rec.map(r => norm(r.word)), n = cn.length, m = rn.length;
  const L = Array.from({ length: n + 1 }, () => new Int16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = cn[i] && cn[i] === rn[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const match = new Array(n).fill(-1); for (let i = 0, j = 0; i < n && j < m;) { if (cn[i] && cn[i] === rn[j]) { match[i] = j; i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) i++; else j++; }
  const t = new Array(n).fill(null); for (let i = 0; i < n; i++) if (match[i] >= 0) t[i] = [rec[match[i]].start, rec[match[i]].end];
  for (let i = 0; i < n;) { if (t[i]) { i++; continue; } let e = i; while (e < n && !t[e]) e++;
    const j0 = i > 0 ? match[i - 1] + 1 : 0, j1 = e < n ? match[e] : m, free = rec.slice(j0, j1), cnt = e - i;
    const t0 = free.length ? free[0].start : (i > 0 ? t[i - 1][1] : a), t1 = free.length ? free[free.length - 1].end : (e < n ? t[e][0] : b);
    for (let k = 0; k < cnt; k++) { if (free.length) { const f0 = free[Math.floor(k * free.length / cnt)], f1 = free[Math.max(Math.floor(k * free.length / cnt), Math.ceil((k + 1) * free.length / cnt) - 1)]; t[i + k] = [f0.start, f1.end]; } else t[i + k] = [t0 + (t1 - t0) * k / cnt, t0 + (t1 - t0) * (k + 1) / cnt]; }
    match.fill(-2, i, e); i = e; }
  let prev = a; return can.map((w, i) => { const s = Math.min(Math.max(t[i][0], prev, a), b); prev = s; return { w, s, e: Math.min(Math.max(t[i][1], s), b), matched: match[i] >= 0 }; });
}
// even spread by word length when there is no alignment
const spread = (text, a, b) => { const can = text.split(/\s+/).filter(Boolean), tot = can.reduce((x, w) => x + w.length + 1, 0); let c = 0; return can.map(w => { const s = a + (b - a) * c / tot; c += w.length + 1; return { w, s, e: a + (b - a) * c / tot, matched: false }; }); };

let t = 0; const base = {}; for (const s of TL.shots) { base[s.name] = t; t += s.duration; }
const shots = TL.shots.map(s => ({ ...s, lines: [] })), byName = Object.fromEntries(shots.map(s => [s.name, s]));
let voiced = 0, aligned = 0, remapped = 0;
for (const l of LINES) {
  const s = byName[l.shot]; if (!s) throw new Error('line ' + l.id + ' references unknown shot ' + l.shot);
  const wavf = path.join(SES.dir, l.audio || ('voices/' + l.id + '.wav'));
  let a = 0, b = l.target_duration, hasVoice = false, words;
  if (fs.existsSync(wavf)) { const d = probe(wavf); if (d > 0.05) { hasVoice = true; voiced++; [a, b] = span(wavf, d);
    const rec = ((ALIGN[l.id] || {}).words || []).filter(w => w.end > w.start);
    if (rec.length) { aligned++; a = Math.min(Math.max(a, rec[0].start), a + 0.6); b = Math.max(a + 0.3, Math.min(b, rec[rec.length - 1].end + 0.12)); words = mapWords(l.text, rec, a, b); remapped += words.filter(w => !w.matched).length; } } }
  if (!words) words = spread(l.text, a, b);
  s.lines.push({ ...l, off: Math.max(LEAD, l.start - base[s.name]), dur: b - a, clipOffset: a, hasVoice, words });
}
const last = shots[shots.length - 1];
function layout(k) { // k (0..1) squeezes the pauses before/between lines toward their minimum
  for (const s of shots) { let cur = LEAD; s.lines.sort((x, y) => x.off0 - y.off0);
    for (const l of s.lines) { const want = Math.max(l.off0, cur); l.off = want + (cur - want) * k; cur = l.off + l.dur + GAP; }
    s.needed = s.lines.length ? cur - GAP + (s === last ? END_TAIL : TAIL) : 0; s.len = Math.max(s.duration, s.needed); }
  return shots.reduce((x, s) => x + s.len, 0); }
for (const s of shots) for (const l of s.lines) l.off0 = l.off;
// total_range = [min, soft max]; hard_max is the absolute ceiling. Above the soft max, shots give back unused slack;
// pauses are squeezed only if the total would still exceed hard_max.
const [lo, soft] = TL.total_range, hard = TL.hard_max || soft, fl = s => Math.max(s.min || 2, s.needed);
const shrink = cap => { const tot = shots.reduce((x, s) => x + s.len, 0), slack = shots.reduce((x, s) => x + Math.max(0, s.len - fl(s)), 0), f = Math.min(1, Math.max(0, tot - cap) / Math.max(slack, 1e-6)); for (const s of shots) s.len -= Math.max(0, s.len - fl(s)) * f; return shots.reduce((x, s) => x + s.len, 0); };
let total = layout(0), squeeze = 0;
if (total > soft) total = shrink(soft);
for (let k = 0.05; total > hard + 1e-6 && k <= 1.0001; k += 0.05) { layout(squeeze = k); total = shrink(hard); }
if (total > hard + 1e-6) console.warn(`WARNING: lines are too long; total ${total.toFixed(2)}s exceeds hard_max ${hard}s.`);
if (total < lo) { const k = lo / total; for (const s of shots) s.len *= k; }
const r3 = x => +x.toFixed(3), labels = TL.speaker_labels || {};
const out = { session: SES.rel, title: TL.title, subtitle: TL.subtitle, title_card: TL.title_card || null, end_card: TL.end_card || null, output: TL.output || SES.name + '.mp4', fps: TL.fps, width: TL.width, height: TL.height, letterbox: TL.letterbox, shots: [], lines: [], beats: [], voiced, aligned };
t = 0; const lineAbs = {};
for (const s of shots) { const start = t, end = t + s.len;
  for (const l of s.lines) { const a = start + l.off; lineAbs[l.id] = a;
    out.lines.push({ id: l.id, speaker: l.speaker, text: l.text, source: l.source, shot: s.name, start: r3(a), end: r3(a + l.dur), hasVoice: l.hasVoice, clipOffset: r3(l.clipOffset), audio: l.audio || `voices/${l.id}.wav`, words: l.words.map(w => ({ w: w.w, t: r3(a + w.s - l.clipOffset), e: r3(a + w.e - l.clipOffset) })) }); }
  out.shots.push({ name: s.name, set: s.set, start: r3(start), end: r3(end), transition: s.transition, slug: s.slug, camera: s.camera }); t = end; }
for (const s of out.shots) for (const b of byName[s.name].beats || []) { let bt = b.line ? (lineAbs[b.line] ?? s.start) + (b.offset || 0) : (b.at >= 0 ? s.start + b.at : s.end + b.at); bt = Math.min(Math.max(bt, s.start), s.end - 0.05); out.beats.push({ name: b.name, shot: s.name, t: r3(bt), motif: b.motif || null }); }
// caption label per line: speaker_labels[speaker] = "Label" | [{ until_beat, label }, ..., { label }]
const beatT = Object.fromEntries(out.beats.map(b => [b.name, b.t]));
for (const l of out.lines) { const m = labels[l.speaker]; l.label = !m ? l.speaker : typeof m === 'string' ? m : (m.find(x => !x.until_beat || l.start < (beatT[x.until_beat] ?? Infinity)) || { label: l.speaker }).label; }
out.total = Math.round(t * TL.fps) / TL.fps; out.frames = Math.round(t * TL.fps);
fs.mkdirSync(path.join(root, 'out'), { recursive: true }); fs.writeFileSync(path.join(root, 'out', 'timing.json'), JSON.stringify(out, null, 1));
console.log(`timing [${SES.rel}]: ${out.shots.length} shots, ${out.lines.length} lines (${voiced} voiced, ${aligned} word-aligned, ${remapped} canonical words re-mapped), pause squeeze ${squeeze.toFixed(2)}, total ${out.total.toFixed(2)}s`);
