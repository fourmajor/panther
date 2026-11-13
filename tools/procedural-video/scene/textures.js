// Procedural PBR textures (albedo / normal / roughness) generated from seeded noise.
import * as THREE from 'three';
import { mulberry32, clamp, lerp, sstep } from './util.js';

function tileNoise(size, period, seed) {
  const r = mulberry32(seed), lat = new Float32Array(period * period); for (let i = 0; i < lat.length; i++) lat[i] = r();
  const out = new Float32Array(size * size);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const fx = x / size * period, fy = y / size * period, ix = Math.floor(fx), iy = Math.floor(fy);
    let ux = fx - ix, uy = fy - iy; ux = ux * ux * (3 - 2 * ux); uy = uy * uy * (3 - 2 * uy);
    const a = lat[(iy % period) * period + ix % period], b = lat[(iy % period) * period + (ix + 1) % period];
    const c = lat[((iy + 1) % period) * period + ix % period], d = lat[((iy + 1) % period) * period + (ix + 1) % period];
    out[y * size + x] = lerp(lerp(a, b, ux), lerp(c, d, ux), uy);
  }
  return out;
}
function fbmTile(size, seed, p0 = 4, oct = 5) {
  const out = new Float32Array(size * size); let amp = 0.5, tot = 0;
  for (let o = 0; o < oct; o++) { const n = tileNoise(size, p0 << o, seed + o * 17); for (let i = 0; i < out.length; i++) out[i] += n[i] * amp; tot += amp; amp *= 0.5; }
  for (let i = 0; i < out.length; i++) out[i] /= tot; return out;
}
function tex(data, size, srgb) {
  const t = new THREE.DataTexture(data, size, size, THREE.RGBAFormat); t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearMipmapLinearFilter; t.generateMipmaps = true; t.anisotropy = 8;
  if (srgb) t.colorSpace = THREE.SRGBColorSpace; t.needsUpdate = true; return t;
}
// Weathered masonry. kind: 'brick' | 'ashlar' (irregular coursed ashlar: uneven course heights and block lengths, rounded
// and chipped arrises, eroded mortar, spalled faces, tooling, cracks), 'flag' (floor slabs), 'rubble' (random stones in
// mortar), 'rough' (plain weathered stone). Returns albedo / normal / roughness maps (tileable).
export function masonry({ size = 768, rows = 8, cols = 4, seed = 1, kind = 'brick', tint = [0.42, 0.40, 0.38], lichen = 0, bump = 3.0, mortar = 0.035, grime = 0.6 }) {
  const N = size * size, h = new Float32Array(N), tone = new Float32Array(N), mort = new Float32Array(N), hue = new Float32Array(N), spall = new Float32Array(N);
  const f1 = fbmTile(size, seed + 1, 4, 6), f2 = fbmTile(size, seed + 2, 16, 4), f3 = fbmTile(size, seed + 3, 3, 4), f4 = fbmTile(size, seed + 4, 32, 3), r = mulberry32(seed * 91 + 7);
  if (kind === 'rough') { for (let i = 0; i < N; i++) { h[i] = f1[i] * 0.8 + f2[i] * 0.35; tone[i] = 0.5 + (f3[i] - 0.5) * 0.9; mort[i] = 1; hue[i] = f3[i]; } }
  else if (kind === 'rubble') { const gx = cols * 2, gy = rows, pts = []; for (let j = 0; j < gy; j++) for (let i = 0; i < gx; i++) pts.push([(i + 0.15 + 0.7 * r()) / gx, (j + 0.15 + 0.7 * r()) / gy, r(), r(), r(), 0.75 + 0.5 * r()]);
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) { const i = y * size + x, u = x / size + (f2[i] - 0.5) * 0.02, v = y / size + (f4[i] - 0.5) * 0.02, ci = Math.floor(u * gx), cj = Math.floor(v * gy); let d1 = 9, d2 = 9, best = null;
        for (let b = -1; b <= 1; b++) for (let a = -1; a <= 1; a++) { const p = pts[((cj + b + gy) % gy) * gx + (ci + a + gx) % gx]; let dx = u - p[0], dy = v - p[1]; dx -= Math.round(dx); dy -= Math.round(dy); const dd = Math.hypot(dx * gx, dy * gy) * p[5]; if (dd < d1) { d2 = d1; d1 = dd; best = p; } else if (dd < d2) d2 = dd; }
        const e = (d2 - d1), bev = sstep(0.03, 0.16 + mortar, e); mort[i] = bev; h[i] = bev * (0.55 + 0.4 * best[2]) * (1 - 0.25 * d1 * d1) + bev * (f1[i] - 0.5) * 0.5 + (f2[i] - 0.5) * 0.15; tone[i] = 0.3 + 0.55 * best[3] + (f3[i] - 0.5) * 0.4; hue[i] = best[4]; } }
  else { const flag = kind === 'flag', cy = [0], rowsB = [];
    for (let i = 0; i < rows; i++) cy.push(cy[i] + (flag ? 0.7 + 0.6 * r() : 0.55 + 0.95 * r() * r() + 0.25 * r())); const ty = cy[rows]; for (let i = 0; i <= rows; i++) cy[i] /= ty;
    for (let i = 0; i < rows; i++) { const xs = [0], n = Math.max(2, Math.round(cols * (0.7 + 0.7 * r()))); for (let k = 0; k < n; k++) xs.push(xs[k] + 0.45 + 1.3 * r() * (flag ? 1 : r() + 0.3)); const tx = xs[n], off = r(); rowsB.push({ xs: xs.map(v => v / tx), off, n, B: Array.from({ length: n }, () => [r(), r(), r(), r() - 0.5, r() - 0.5, r(), r()]) }); }
    for (let y = 0; y < size; y++) { for (let x = 0; x < size; x++) { const i = y * size + x, u = x / size + (f2[i] - 0.5) * 0.012, v0 = y / size + (f4[i] - 0.5) * 0.008, v = v0 - Math.floor(v0);
        let row = 0; while (row < rows - 1 && v >= cy[row + 1]) row++; const R = rowsB[row]; let cu = u + R.off; cu -= Math.floor(cu); let k = 0; while (k < R.n - 1 && cu >= R.xs[k + 1]) k++;
        const b = R.B[k], w = R.xs[k + 1] - R.xs[k], hh = cy[row + 1] - cy[row], fx = (cu - R.xs[k]) / w, fy = (v - cy[row]) / hh;
        // distance to the block edge in tile units, with a wavering outline and rounded (worn) corners
        const ex = Math.min(fx, 1 - fx) * w, ey = Math.min(fy, 1 - fy) * hh, wob = (f2[i] - 0.5) * 0.022 + (f4[i] - 0.5) * 0.008, rr = 0.004 + 0.014 * b[5] * b[5];
        const qx = Math.max(rr - ex, 0), qy = Math.max(rr - ey, 0), d = Math.min(ex, ey) > rr ? Math.min(ex, ey) + wob : rr - Math.hypot(qx, qy) + wob;
        const mw = mortar * (0.35 + 0.8 * f3[i]), bev = sstep(mw * 0.25, mw, d); mort[i] = bev;
        const chip = sstep(0.62, 0.74, f2[i] * 0.55 + f1[i] * 0.45) * sstep(0.09, 0.0, d), sp = b[6] < 0.16 ? sstep(0.42, 0.56, f1[i] * 0.6 + f2[i] * 0.4) : 0;     // chipped arrises, spalled faces
        const tool = b[0] > 0.72 && !flag ? 0.011 * Math.sin((fx * w * Math.cos(b[1] * 3) + fy * hh * Math.sin(b[1] * 3)) * 520) : 0;
        const crack = sstep(0.012, 0.002, Math.abs(f1[i] - 0.5 + (b[2] - 0.5) * 0.3)) * sstep(0.45, 0.7, f3[(i * 3 + 977) % N]) * bev;
        h[i] = bev * (0.6 + 0.1 * b[0] + (fx - 0.5) * b[3] * 0.1 + (fy - 0.5) * b[4] * 0.1) + bev * (f1[i] - 0.5) * 0.45 + (f2[i] - 0.5) * 0.14 + bev * tool - (1 - bev) * (0.02 + 0.2 * f3[i] * f3[i]) - chip * 0.3 - sp * 0.22 - crack * 0.3;
        const pit = sstep(0.68, 0.8, f2[i] * 0.6 + f4[i] * 0.4); h[i] -= pit * 0.2 * bev;
        tone[i] = 0.44 + 0.2 * b[1] + (f3[i] - 0.5) * 0.4 - 0.25 * crack - 0.12 * sp; hue[i] = b[2]; spall[i] = sp; } } }
  const alb = new Uint8Array(N * 4), nor = new Uint8Array(N * 4), rgh = new Uint8Array(N * 4);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const i = y * size + x, xl = y * size + (x + size - 1) % size, xr = y * size + (x + 1) % size, yu = ((y + size - 1) % size) * size + x, yd = ((y + 1) % size) * size + x;
    let nx = (h[xl] - h[xr]) * bump * size / 512, ny = (h[yu] - h[yd]) * bump * size / 512, nz = 1; const il = 1 / Math.hypot(nx, ny, nz);
    nor[i * 4] = (nx * il * 0.5 + 0.5) * 255; nor[i * 4 + 1] = (ny * il * 0.5 + 0.5) * 255; nor[i * 4 + 2] = (nz * il * 0.5 + 0.5) * 255; nor[i * 4 + 3] = 255;
    const k = (0.55 + 0.75 * tone[i]) * (0.72 + 0.5 * f1[i]) * lerp(0.7, 1, mort[i]), hu = hue[i] - 0.5;
    let cr = tint[0] * k * (1 + 0.13 * hu), cg = tint[1] * k * (1 + 0.03 * hu), cb = tint[2] * k * (1 - 0.15 * hu);
    const stain = sstep(0.5, 0.75, f3[i] * 0.7 + f2[i] * 0.3); cr *= 1 - stain * 0.35; cg *= 1 - stain * 0.33; cb *= 1 - stain * 0.28;
    // grime runs: dark vertical streaks; pale lichen blooms; moss gathering in the joints and on spalled faces
    const st = sstep(0.5, 0.78, f1[(Math.floor(y * 0.11) * size + (x * 3) % size) % N] * 0.6 + f3[(Math.floor(y * 0.3) * size + x) % N] * 0.4) * grime; cr *= 1 - 0.3 * st; cg *= 1 - 0.3 * st; cb *= 1 - 0.27 * st;
    const pale = sstep(0.7, 0.8, f4[(i * 5 + 311) % N] * 0.5 + f1[(i + 7777) % N] * 0.5) * mort[i] * 0.45; cr = lerp(cr, 0.55, pale); cg = lerp(cg, 0.56, pale); cb = lerp(cb, 0.5, pale);
    if (lichen > 0) { const L = clamp(sstep(0.5, 0.66, f1[(i * 7 + 131) % N] * 0.5 + f3[i] * 0.5) * lichen * (0.35 + 0.65 * (1 - mort[i]) + 0.5 * spall[i])); cr = lerp(cr, 0.2, L); cg = lerp(cg, 0.27, L); cb = lerp(cb, 0.1, L); }
    alb[i * 4] = clamp(cr) * 255; alb[i * 4 + 1] = clamp(cg) * 255; alb[i * 4 + 2] = clamp(cb) * 255; alb[i * 4 + 3] = 255;
    const ro = clamp(0.74 + 0.22 * f2[i] - 0.1 * (h[i] > 0.6 ? 1 : 0) + (1 - mort[i]) * 0.2);
    rgh[i * 4] = 255; rgh[i * 4 + 1] = ro * 255; rgh[i * 4 + 2] = 0; rgh[i * 4 + 3] = 255;
  }
  return { map: tex(alb, size, true), normalMap: tex(nor, size, false), roughnessMap: tex(rgh, size, false) };
}
const cache = {};
export function stoneMat(key, opts = {}, matOpts = {}) {
  if (cache[key]) return cache[key];
  const t = masonry(opts), W = opts.weather ?? {};
  const m = new THREE.MeshStandardMaterial({ ...t, roughness: 1, metalness: 0, normalScale: new THREE.Vector2(1.15, 1.15), ...matOpts });
  // world-space weathering: broad tonal drift, rain streaks down vertical faces, damp and moss toward the ground
  const u = { uWS: { value: W.scale ?? 1 }, uWStreak: { value: W.streak ?? 0.45 }, uWMoss: { value: W.moss ?? 0.35 }, uWBase: { value: W.base ?? 0 }, uWDrift: { value: W.drift ?? 0.4 } }; m.userData.u = u;
  m.customProgramCacheKey = () => 'stone-weather';
  m.onBeforeCompile = sh => { Object.assign(sh.uniforms, u);
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vWP; varying vec3 vWN;').replace('#include <begin_vertex>', '#include <begin_vertex>\nvWP=(modelMatrix*vec4(position,1.)).xyz; vWN=normalize(mat3(modelMatrix)*normal);');
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', `#include <common>\nvarying vec3 vWP; varying vec3 vWN; uniform float uWS,uWStreak,uWMoss,uWBase,uWDrift;
      float wh(vec3 p){ p=fract(p*0.3183099+.1); p*=17.; return fract(p.x*p.y*p.z*(p.x+p.y+p.z)); }
      float wn(vec3 x){ vec3 i=floor(x), f=fract(x); f=f*f*(3.-2.*f); return mix(mix(mix(wh(i),wh(i+vec3(1,0,0)),f.x),mix(wh(i+vec3(0,1,0)),wh(i+vec3(1,1,0)),f.x),f.y),mix(mix(wh(i+vec3(0,0,1)),wh(i+vec3(1,0,1)),f.x),mix(wh(i+vec3(0,1,1)),wh(i+vec3(1,1,1)),f.x),f.y),f.z); }
      float wf(vec3 p){ return wn(p)*.5+wn(p*2.07+3.)*.3+wn(p*4.3+9.)*.2; }`)
      .replace('#include <color_fragment>', `#include <color_fragment>
        { vec3 p=vWP*uWS; float drift=wf(p*.21); diffuseColor.rgb*=1.+uWDrift*(drift-.5)*1.4; diffuseColor.rgb*=mix(vec3(1.),vec3(1.06,.99,.93),wf(p*.09+7.)-.2);
          float wall=1.-abs(vWN.y); float sk=wf(vec3(p.x*2.6+p.z*2.6, p.y*.16, p.z*.9-p.x*.9)); float st=smoothstep(.5,.72,sk)*wall*uWStreak; diffuseColor.rgb*=1.-st*.55;
          float low=smoothstep(2.6,.0,vWP.y-uWBase); float ms=smoothstep(.42,.68,wf(p*.9+2.)*.6+low*.5)*uWMoss*(.35+.65*low); diffuseColor.rgb=mix(diffuseColor.rgb,diffuseColor.rgb*vec3(.5,.62,.34)+vec3(.004,.008,.0),ms);
          diffuseColor.rgb*=1.-.3*low*wall*uWMoss; }`); };
  return cache[key] = m;
}
// Diamond-mesh net (alpha) drawn with Canvas2D paths
export function netTexture(n = 8, lw = 5) {
  const c = document.createElement('canvas'); c.width = c.height = 256; const g = c.getContext('2d');
  g.clearRect(0, 0, 256, 256); g.strokeStyle = '#fff'; g.lineWidth = lw; const s = 256 / n;
  for (let i = -n; i < 2 * n; i++) { g.beginPath(); g.moveTo(i * s, 0); g.lineTo(i * s + 256, 256); g.stroke(); g.beginPath(); g.moveTo(i * s, 0); g.lineTo(i * s - 256, 256); g.stroke(); }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8; return t;
}
// Ragged tapestry: alpha holes + red/black heraldic smear
export function tapestryTexture(seed = 5) {
  const size = 256, f = fbmTile(size, seed, 4, 5), f2 = fbmTile(size, seed + 9, 8, 4), d = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const i = y * size + x, u = x / size - 0.5, v = y / size;
    const fig = sstep(0.32, 0.28, Math.hypot(u * 1.3, v - 0.55) + (f2[i] - 0.5) * 0.25);
    const red = fig * (0.6 + 0.4 * f[i]);
    d[i * 4] = 18 + red * 150; d[i * 4 + 1] = 8 + red * 12; d[i * 4 + 2] = 10 + red * 14;
    const hole = f[i] * 0.7 + f2[i] * 0.3 + (1 - v) * 0.22 - 0.1; d[i * 4 + 3] = hole > 0.56 ? 0 : 255;
  }
  const t = new THREE.DataTexture(d, size, size, THREE.RGBAFormat); t.colorSpace = THREE.SRGBColorSpace; t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearMipmapLinearFilter; t.generateMipmaps = true; t.needsUpdate = true; return t;
}
