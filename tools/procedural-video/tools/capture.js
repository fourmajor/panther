#!/usr/bin/env node
// Puppeteer capture. Steps t = i/fps, calls window.renderFrame(t), streams JPEG frames straight into ffmpeg.
//   SESSION=sessions/<name> node tools/capture.js                 full render -> out/<timeline.output> (muxes out/mix.wav)
//   SESSION=sessions/<name> node tools/capture.js --stills 3,10.5 stills -> contact sheet out/contact-<tag>.png
const http = require('http'), fs = require('fs'), path = require('path'), cp = require('child_process');
const puppeteer = require('puppeteer'), { session } = require('./session');
const SES = session();
const root = path.join(__dirname, '..'), FF = fs.existsSync('/opt/homebrew/bin/ffmpeg') ? '/opt/homebrew/bin/ffmpeg' : 'ffmpeg';
const args = process.argv.slice(2), arg = n => { const i = args.indexOf(n); return i < 0 ? null : (args[i + 1] ?? true); };
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.mjs': 'text/javascript' };
const server = http.createServer((req, res) => { const p = path.normalize(path.join(root, decodeURIComponent(req.url.split('?')[0]))); if (!p.startsWith(root) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); } res.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream', 'Cache-Control': 'no-store' }); fs.createReadStream(p).pipe(res); });
(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r)); const port = server.address().port;
  const browser = await puppeteer.launch({ headless: true, args: ['--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist', '--enable-webgl', '--hide-scrollbars', '--force-device-scale-factor=1', '--window-size=1920,1080', '--disable-background-timer-throttling', '--force-color-profile=srgb'] });
  const page = await browser.newPage(); await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
  const errs = []; page.on('console', m => { const t = m.text(); if (m.type() === 'error' || /THREE|WebGL|shader/i.test(t)) { if (errs.length < 30) console.log('[page]', t.slice(0, 600)); errs.push(t); } }); page.on('pageerror', e => { console.log('[pageerror]', e.message); });
  await page.goto(`http://127.0.0.1:${port}/scene/index.html?session=${encodeURIComponent(SES.rel)}`, { waitUntil: 'load' });
  await page.waitForFunction('window.READY===true', { timeout: 120000 });
  const info = await page.evaluate(() => ({ dur: window.DURATION, frames: window.FRAMES, fps: window.TIMING.fps, output: window.TIMING.output, gl: (() => { const g = document.createElement('canvas').getContext('webgl2'); const e = g.getExtension('WEBGL_debug_renderer_info'); return e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : 'n/a'; })() }));
  console.log(`ready: ${info.dur.toFixed(2)}s, ${info.frames} frames, GL: ${info.gl}`);
  if (arg('--eval')) await page.evaluate(String(arg('--eval')));
  const cdp = await page.createCDPSession();
  const shot = async (t, fmt, q) => { await page.evaluate(t => window.renderFrame(t), t); const r = await cdp.send('Page.captureScreenshot', { format: fmt, quality: q, optimizeForSpeed: true }); return Buffer.from(r.data, 'base64'); };
  const t0 = Date.now();
  if (arg('--stills')) {
    const tag = arg('--tag') || 'a', dir = path.join(root, 'out', 'stills'); fs.rmSync(dir, { recursive: true, force: true }); fs.mkdirSync(dir, { recursive: true }); const keep = args.includes('--keep');
    let ts = String(arg('--stills')); ts = ts === 'auto' ? Array.from({ length: 12 }, (_, i) => +(info.dur * (i + 0.5) / 12).toFixed(2)) : ts.split(',').map(Number);
    for (let i = 0; i < ts.length; i++) fs.writeFileSync(path.join(dir, `s-${String(i).padStart(2, '0')}.png`), await shot(ts[i], 'png'));
    const cols = +(arg('--cols') || 3), rows = Math.ceil(ts.length / cols), w = +(arg('--w') || 640);
    cp.execFileSync(FF, ['-y', '-v', 'error', '-framerate', '1', '-i', path.join(dir, 's-%02d.png'), '-vf', `scale=${w}:-1,tile=${cols}x${rows}:padding=4`, '-frames:v', '1', '-pix_fmt', 'rgb24', path.join(root, 'out', `contact-${tag}.png`)]);
    if (!keep) fs.rmSync(dir, { recursive: true, force: true });
    console.log(`stills ${ts.join(', ')} -> out/contact-${tag}.png (${((Date.now() - t0) / 1000).toFixed(1)}s)`);
  } else {
    const out = path.join(root, 'out', arg('--out') || info.output), mixf = path.join(root, 'out', 'mix.wav'), hasA = fs.existsSync(mixf);
    const from = +(arg('--from') || 0), to = Math.min(info.frames, +(arg('--to') || info.frames));
    const fa = ['-y', '-v', 'error', '-f', 'image2pipe', '-c:v', 'mjpeg', '-framerate', String(info.fps), '-i', 'pipe:0'];
    if (hasA) fa.push('-i', mixf);
    fa.push('-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-maxrate', '24M', '-bufsize', '48M', '-pix_fmt', 'yuv420p', '-vf', 'scale=in_range=pc:out_range=tv,format=yuv420p', '-color_range', 'tv', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-r', String(info.fps));
    if (hasA) fa.push('-c:a', 'aac', '-b:a', '320k', '-ar', '48000', '-ac', '2', '-shortest');
    fa.push('-movflags', '+faststart', out);
    const ff = cp.spawn(FF, fa, { stdio: ['pipe', 'inherit', 'inherit'] }); const done = new Promise(r => ff.on('close', r));
    for (let i = from; i < to; i++) { const b = await shot(i / info.fps, 'jpeg', 96); if (!ff.stdin.write(b)) await new Promise(r => ff.stdin.once('drain', r));
      if (i % 150 === 0) console.log(`frame ${i}/${to}  ${((Date.now() - t0) / 1000).toFixed(0)}s`); }
    ff.stdin.end(); const code = await done; const secs = (Date.now() - t0) / 1000;
    fs.writeFileSync(path.join(root, 'out', 'render-log.json'), JSON.stringify({ frames: to - from, seconds: +secs.toFixed(1), fps: +((to - from) / secs).toFixed(2), gl: info.gl, audio: hasA, ffmpegExit: code }, null, 1));
    console.log(`video: ${out} (${to - from} frames in ${secs.toFixed(0)}s, ffmpeg exit ${code})`);
  }
  await browser.close(); server.close();
})().catch(e => { console.error(e); process.exit(1); });
