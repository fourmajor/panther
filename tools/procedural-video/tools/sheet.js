#!/usr/bin/env node
// Contact sheet from image files:  node tools/sheet.js out.jpg --cols 2 --w 1000 [--crop w:h:x:y] a.png b.png ...
// Each input is (optionally cropped and) scaled to --w wide; rows are padded to equal height. Used for review loops.
const cp = require('child_process'), fs = require('fs');
const a = process.argv.slice(2), out = a.shift(), opt = { cols: 2, w: 1000, crop: null }, files = [];
for (let i = 0; i < a.length; i++) { if (a[i] === '--cols') opt.cols = +a[++i]; else if (a[i] === '--w') opt.w = +a[++i]; else if (a[i] === '--crop') opt.crop = a[++i]; else files.push(a[i]); }
const FF = fs.existsSync('/opt/homebrew/bin/ffmpeg') ? '/opt/homebrew/bin/ffmpeg' : 'ffmpeg', n = files.length, rows = Math.ceil(n / opt.cols), H = Math.round(opt.w * 9 / 16);
const pre = files.map((_, i) => `[${i}]${opt.crop ? `crop=${opt.crop},` : ''}scale=${opt.w}:${opt.crop ? Math.round(opt.w * (+opt.crop.split(':')[1]) / (+opt.crop.split(':')[0])) : -2},setsar=1[s${i}]`).join(';');
const lay = files.map((_, i) => `${(i % opt.cols) ? Array.from({ length: i % opt.cols }, (_, k) => 'w' + k).join('+') : 0}_${Math.floor(i / opt.cols) ? Array.from({ length: Math.floor(i / opt.cols) }, (_, k) => 'h' + k * opt.cols).join('+') : 0}`).join('|');
cp.execFileSync(FF, ['-y', '-v', 'error', ...files.flatMap(f => ['-i', f]), '-filter_complex', n > 1 ? `${pre};${files.map((_, i) => `[s${i}]`).join('')}xstack=inputs=${n}:layout=${lay}:fill=black` : pre.replace('[s0]', ''), '-frames:v', '1', '-q:v', '3', out], { stdio: 'inherit' });
console.log(`sheet: ${n} images -> ${out}`);
