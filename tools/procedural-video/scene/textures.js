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
// kind: 'brick' (coursed ashlar), 'flag' (floor slabs), 'rough' (plain weathered stone)
export function masonry({ size = 512, rows = 8, cols = 4, seed = 1, kind = 'brick', tint = [0.42, 0.40, 0.38], lichen = 0, bump = 3.0, mortar = 0.035 }) {
  const N = size * size, h = new Float32Array(N), tone = new Float32Array(N), mort = new Float32Array(N);
  const f1 = fbmTile(size, seed + 1, 4, 6), f2 = fbmTile(size, seed + 2, 16, 4), f3 = fbmTile(size, seed + 3, 3, 4);
  const r = mulberry32(seed * 91 + 7), rowOff = [], bt = [];
  for (let i = 0; i < rows; i++) rowOff.push(kind === 'flag' ? r() : (i % 2) * 0.5 + (r() - 0.5) * 0.25);
  for (let i = 0; i < rows * cols; i++) bt.push([r(), r(), r()]);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const i = y * size + x, u = x / size, v = y / size;
    if (kind === 'rough') { h[i] = f1[i] * 0.8 + f2[i] * 0.35; tone[i] = 0.5 + (f3[i] - 0.5) * 0.9; mort[i] = 1; continue; }
    const row = Math.floor(v * rows), cx = u * cols + rowOff[row], col = ((Math.floor(cx) % cols) + cols) % cols;
    const fx = cx - Math.floor(cx), fy = v * rows - row, b = bt[row * cols + col];
    const warp = (f2[i] - 0.5) * 0.02;
    const d = Math.min(Math.min(fx, 1 - fx) / cols, Math.min(fy, 1 - fy) / rows) + warp;
    const bev = sstep(mortar * 0.25, mortar, d);
    mort[i] = bev;
    h[i] = bev * (0.62 + 0.3 * b[0]) + bev * (f1[i] - 0.5) * 0.5 + (f2[i] - 0.5) * 0.12 - (1 - bev) * 0.05;
    // chipped corners / pits
    const pit = sstep(0.68, 0.8, f2[i] * 0.6 + f1[i] * 0.4); h[i] -= pit * 0.22 * bev;
    tone[i] = 0.34 + 0.5 * b[1] + (f3[i] - 0.5) * 0.5;
  }
  const alb = new Uint8Array(N * 4), nor = new Uint8Array(N * 4), rgh = new Uint8Array(N * 4);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const i = y * size + x, xl = y * size + (x + size - 1) % size, xr = y * size + (x + 1) % size, yu = ((y + size - 1) % size) * size + x, yd = ((y + 1) % size) * size + x;
    let nx = (h[xl] - h[xr]) * bump, ny = (h[yu] - h[yd]) * bump, nz = 1; const il = 1 / Math.hypot(nx, ny, nz);
    nor[i * 4] = (nx * il * 0.5 + 0.5) * 255; nor[i * 4 + 1] = (ny * il * 0.5 + 0.5) * 255; nor[i * 4 + 2] = (nz * il * 0.5 + 0.5) * 255; nor[i * 4 + 3] = 255;
    const k = (0.55 + 0.75 * tone[i]) * (0.72 + 0.5 * f1[i]) * lerp(0.42, 1, mort[i]);
    let cr = tint[0] * k, cg = tint[1] * k, cb = tint[2] * k;
    const stain = sstep(0.5, 0.75, f3[i] * 0.7 + f2[i] * 0.3); cr *= 1 - stain * 0.35; cg *= 1 - stain * 0.33; cb *= 1 - stain * 0.28;
    if (lichen > 0) { const L = sstep(0.56, 0.7, f1[(i * 7 + 131) % N] * 0.5 + f3[i] * 0.5) * lichen * mort[i]; cr = lerp(cr, 0.42, L); cg = lerp(cg, 0.52, L); cb = lerp(cb, 0.30, L); }
    alb[i * 4] = clamp(cr) * 255; alb[i * 4 + 1] = clamp(cg) * 255; alb[i * 4 + 2] = clamp(cb) * 255; alb[i * 4 + 3] = 255;
    const ro = clamp(0.72 + 0.25 * f2[i] - 0.12 * (h[i] > 0.6 ? 1 : 0) + (1 - mort[i]) * 0.2);
    rgh[i * 4] = 255; rgh[i * 4 + 1] = ro * 255; rgh[i * 4 + 2] = 0; rgh[i * 4 + 3] = 255;
  }
  return { map: tex(alb, size, true), normalMap: tex(nor, size, false), roughnessMap: tex(rgh, size, false) };
}
const cache = {};
export function stoneMat(key, opts = {}, matOpts = {}) {
  if (cache[key]) return cache[key];
  const t = masonry(opts);
  const m = new THREE.MeshStandardMaterial({ ...t, roughness: 1, metalness: 0, normalScale: new THREE.Vector2(1.6, 1.6), ...matOpts });
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
