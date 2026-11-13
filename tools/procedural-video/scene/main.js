// Deterministic renderer: window.renderFrame(t) draws the exact frame for time t (seconds).
// Generic shot loader: reads out/timing.json, imports <session>/scene/index.js (buildSets) and plays its shots.
import * as THREE from 'three';
import { Post } from './post.js';
import { clamp, sstep, ease } from './util.js';
import { makeSpeech } from './lipsync.js';

const W = 1920, H = 1080;
const TM = await (await fetch('../out/timing.json')).json();
const ENV = await fetch('../out/envelopes.json').then(r => r.ok ? r.json() : null).catch(() => null), speech = makeSpeech(TM, ENV);
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(1); renderer.setSize(W, H, false); renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFShadowMap; renderer.toneMapping = THREE.NoToneMapping;
const post = new Post(renderer, W, H);
const SESSION = new URLSearchParams(location.search).get('session') || TM.session;
const QS = new URLSearchParams(location.search), MODE = QS.get('mode') || 'film';   // mode=closeups builds only the session's close-up studio
const SMOD = await import(`../${SESSION}/scene/index.js`), sets = MODE === 'closeups' ? {} : await SMOD.buildSets(renderer);
const fns = {}; for (const k in sets) Object.assign(fns, sets[k].shots);
const beats = Object.fromEntries(TM.beats.map(b => [b.name, b.t])), lines = Object.fromEntries(TM.lines.map(l => [l.id, l]));
const $ = id => document.getElementById(id);
const TC = TM.title_card, EC = TM.end_card, Q = EC && EC.quote_line ? lines[EC.quote_line] : null;
for (const e of document.querySelectorAll('.ttl')) e.textContent = (TM.title || '').toUpperCase();
$('sub').textContent = (TM.subtitle || '').replace(/ · /g, '  ·  '); $('endq').textContent = Q ? '“' + Q.text + '”' : ''; $('credit').textContent = (EC && EC.credit) || '';
// caption DOM: one span per canonical word, revealed/emphasised on its spoken start time
let capId = null, capSpans = [];
function setCaption(L) { if (capId === L.id) return; capId = L.id; const c = $('cap'); c.textContent = ''; capSpans = [];
  const q = L.source === 'chapter' || L.source === 'narration' ? ['', ''] : ['“', '”'];
  L.words.forEach((w, i) => { const sp = document.createElement('span'); sp.textContent = (i === 0 ? q[0] : '') + w.w + (i === L.words.length - 1 ? q[1] : ''); c.appendChild(sp); if (i < L.words.length - 1) c.appendChild(document.createTextNode(' ')); capSpans.push(sp); }); }
const DIS = 0.9, DIP = 0.32;
function evalShot(i, t, slot, frame) {
  const s = TM.shots[i], lt = t - s.start, d = s.end - s.start;
  const ctx = { T: t, start: s.start, end: s.end, beat: n => beats[n] ?? s.start, line: id => (lines[id] ? lines[id].start : s.start), lineEnd: id => (lines[id] ? lines[id].end : s.start), speech: who => speech(t, who) };
  const P = fns[s.name](lt, d, ctx);
  P.camera.aspect = W / H; const py = P.camera.projectionMatrix;
  P.camera.updateProjectionMatrix();
  const px = H * 0.5 * P.camera.projectionMatrix.elements[5];
  for (const p of P.parts || []) p.u.uPx.value = px;
  post.shot(P.scene, P.camera, P, slot, t, frame);
  return P;
}
window.DURATION = TM.total; window.FRAMES = TM.frames; window.TIMING = TM;
window.renderFrame = function (t) {
  t = clamp(t, 0, TM.total - 1e-4); const frame = Math.round(t * TM.fps);
  let i = TM.shots.findIndex(s => t >= s.start && t < s.end); if (i < 0) i = TM.shots.length - 1;
  const s = TM.shots[i], lt = t - s.start, nx = TM.shots[i + 1];
  let mix = 0, fade = 1, flash = 0, P;
  if (s.transition === 'dissolve' && i > 0 && lt < DIS) { evalShot(i - 1, t, 0, frame); P = evalShot(i, t, 1, frame); mix = ease(lt / DIS); }
  else P = evalShot(i, t, 0, frame);
  if (s.transition === 'fade-in') fade = sstep(0.1, 1.6, lt);
  if (s.transition === 'dip') fade = sstep(0, DIP, lt);
  if (nx && nx.transition === 'dip') fade *= sstep(0, DIP, s.end - t);
  if (s.transition === 'flash') flash += 0.9 * Math.exp(-lt / 0.12);
  if (nx && nx.transition === 'flash') flash += 0.9 * sstep(0.1, 0, s.end - t);
  if (!nx) fade *= sstep(0, 1.3, s.end - t);
  flash += P.flash || 0;
  post.final(P, mix, fade, flash, frame);
  // typography overlay (DOM, composited over the canvas)
  const sl = $('slug'); if (s.slug) { sl.textContent = s.slug; sl.style.opacity = (sstep(0.3, 1.0, lt) * sstep(4.2, 3.4, lt) * 0.92).toFixed(3); } else sl.style.opacity = 0;
  const ts = TC && TM.shots.find(x => x.name === TC.shot), es = EC && TM.shots.find(x => x.name === EC.shot);
  $('title').style.opacity = ts ? (sstep(ts.start + 0.7, ts.start + 1.9, t) * sstep(ts.end + 0.5, ts.end - 0.5, t)).toFixed(3) : 0;
  $('title').style.transform = `scale(${(1 + 0.012 * (ts ? t - ts.start : 0)).toFixed(4)})`;
  $('end').style.opacity = es ? (sstep(es.start + 0.9, es.start + 2.0, t) * sstep(es.end - 0.2, es.end - 1.2, t)).toFixed(3) : 0;
  const L = TM.lines.find(l => t >= l.start - 0.15 && t < l.end + 0.4 && !(Q && l.id === Q.id));
  if (L) { const o = sstep(L.start - 0.15, L.start + 0.1, t) * sstep(L.end + 0.4, L.end + 0.05, t); setCaption(L); $('spk').textContent = L.label || L.speaker; $('spk').style.opacity = o.toFixed(3); $('cap').style.opacity = o.toFixed(3);
    L.words.forEach((w, i) => { const r = sstep(w.t - 0.05, w.t + 0.13, t), hot = r * sstep(w.e + 0.3, w.e, t), sp = capSpans[i];
      sp.style.opacity = (0.34 + 0.66 * r).toFixed(3); sp.style.color = `rgb(${Math.round(236 + 19 * hot)},${Math.round(230 + 10 * hot)},${Math.round(216 - 22 * hot)})`; sp.style.textShadow = hot > 0.02 ? `0 0 ${(14 * hot).toFixed(1)}px rgba(255,190,110,${(0.5 * hot).toFixed(3)})` : 'none'; }); }
  else { $('spk').style.opacity = 0; $('cap').style.opacity = 0; }
  return true;
};
// Close-ups: a session may export closeups(renderer) -> { names, render(name, variant, t, ctx) -> frame params }.
// window.renderCloseup(name, variant, t) draws one through the same post pipeline (no letterbox, no captions).
const CU = SMOD.closeups && MODE === 'closeups' ? await SMOD.closeups(renderer) : null; window.CLOSEUPS = CU ? CU.names : [];
window.renderCloseup = function (name, variant = 'front', t = 0) { for (const id of ['slug', 'title', 'end', 'spk', 'cap']) $(id).style.opacity = 0;
  const P = CU.render(name, variant, t, { T: t, speech: who => speech(t, who) }); P.camera.aspect = W / H; P.camera.updateProjectionMatrix();
  for (const p of P.parts || []) p.u.uPx.value = H * 0.5 * P.camera.projectionMatrix.elements[5];
  post.shot(P.scene, P.camera, P, 0, t, Math.round(t * TM.fps)); post.final({ bar: 0, ...P }, 0, 1, 0, Math.round(t * TM.fps)); return true; };
window.SETS = sets; window.READY = true;
