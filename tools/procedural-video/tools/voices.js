#!/usr/bin/env node
// Optional voice step: text-to-speech for every line, then word-level alignment. Network calls happen only here,
// and only when OPENROUTER_API_KEY is set in the environment (never stored in files).
//   SESSION=sessions/<name> npm run voices            (extra args go to tts_gemini.py, e.g. -- --only L01,L02)
const cp = require('child_process'), path = require('path'), { session } = require('./session');
const SES = session();
if (!process.env.OPENROUTER_API_KEY) { console.log('voices: OPENROUTER_API_KEY is not set - skipping TTS + alignment (render will use existing clips, or captions only).'); process.exit(0); }
const lines = path.join(SES.dir, 'lines.json'), cast = path.join(SES.dir, 'voices.json'), out = path.join(SES.dir, 'voices'), extra = process.argv.slice(2).filter((a, i, arr) => a !== '--session' && arr[i - 1] !== '--session');
const run = (script, args) => { const r = cp.spawnSync('python3', [path.join(__dirname, 'voice', script), ...args], { stdio: 'inherit' }); if (r.status) process.exit(r.status); };
run('tts_gemini.py', [lines, cast, out, ...extra]);
run('align_whisper.py', [lines, out]);
