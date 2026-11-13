#!/usr/bin/env node
// Amplitude envelopes for lip sync: for every line with a voice clip, the clip's RMS level sampled at 100 Hz and
// normalised to its own peak -> out/envelopes.json  { <lineId>: { rate: 100, v: [0..1, ...] } }.
// Usage: SESSION=sessions/<name> node tools/envelope.js
const fs = require('fs'), path = require('path'), wav = require('./wav'), { session } = require('./session');
const SES = session(), LINES = JSON.parse(fs.readFileSync(path.join(SES.dir, 'lines.json'), 'utf8')), RATE = 100, out = {};
for (const l of LINES) { const f = path.join(SES.dir, l.audio || `voices/${l.id}.wav`); if (!fs.existsSync(f)) continue;
  const { L, sr } = wav.read(f), hop = Math.round(sr / RATE), win = hop * 3, n = Math.ceil(L.length / hop), v = new Array(n); let pk = 1e-6;
  for (let i = 0; i < n; i++) { let s = 0, c = 0; for (let k = Math.max(0, i * hop - win / 2 | 0); k < Math.min(L.length, i * hop + win / 2); k++) { s += L[k] * L[k]; c++; } v[i] = Math.sqrt(s / Math.max(1, c)); pk = Math.max(pk, v[i]); }
  const sorted = [...v].sort((a, b) => a - b), ref = sorted[Math.floor(sorted.length * 0.95)] || pk;
  out[l.id] = { rate: RATE, v: v.map(x => +Math.min(1, x / ref).toFixed(3)) }; }
fs.mkdirSync(path.join(SES.root, 'out'), { recursive: true }); fs.writeFileSync(path.join(SES.root, 'out', 'envelopes.json'), JSON.stringify(out));
console.log(`envelopes [${SES.rel}]: ${Object.keys(out).length} clips -> out/envelopes.json`);
