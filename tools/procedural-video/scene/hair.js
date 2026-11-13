// Hair as strand ribbons grown over a head's distance field: roots sampled inside a hairline, strands flow from a
// parting, fall under gravity, wave or curl, clump into locks and collide with the head and shoulders. A scalp cap
// under the strands hides the skin. Everything is driven by a spec; nothing here knows any particular hairstyle.
import * as THREE from 'three';
import { mulberry32, clamp, lerp, sstep } from './util.js';
import { project, ell } from './sdf.js';

export const HAIR_DEFAULTS = { color: 0x2a1c12, tip: null, vary: 0.3, clumps: 110, per: 9, spread: 0.07, len: [0.10, 0.16], segs: 10, width: 0.0026, taper: 0.35,
  hairline: { front: 31, temple: 7, side: -6, sideburn: 0, nape: -44 }, part: 0.0, flow: [0.9, -0.3, -0.45], fringe: 0, fringeFlow: [0.5, -0.9, 0.45], lift: 0.25, gravity: 1, stiff: 0,
  wave: 0.004, waveFreq: 38, curl: 0, curlTurns: 0, frizz: 0.0015, lenTop: 1, lenSide: 1, lenBack: 1, topClip: 90, rough: 0.46, cap: true, shoulders: true, margin: 0.0035, converge: 0.5, sweepBack: 0, hug: 0, edge: 0.18, seed: 1 };
const C0 = [0, 0.03, -0.012];
export function hairline(hl, azDeg) { const a = Math.abs(azDeg), F = hl.front, K = [[0, F], [38, F + hl.temple], [60, F - 8], [74, hl.side - 2 - hl.sideburn], [84, hl.side - hl.sideburn * 0.4], [100, hl.side - 6], [125, lerp(hl.side, hl.nape, 0.7)], [180, hl.nape]];
  for (let i = 1; i < K.length; i++) if (a <= K[i][0]) return lerp(K[i - 1][1], K[i][1], (a - K[i - 1][0]) / (K[i][0] - K[i - 1][0])); return hl.nape; }
// head: result of makeHead (uses head.field.f). Returns a Group (cap + strand mesh).
export function makeHair(head, spec = {}) {
  const s = { ...HAIR_DEFAULTS, ...spec, hairline: { ...HAIR_DEFAULTS.hairline, ...(spec.hairline || {}) } }, f = head.field.f, rnd = mulberry32(s.seed * 7717 + 3), group = new THREE.Group();
  const col = new THREE.Color(s.color), tip = new THREE.Color(s.tip ?? s.color), DEG = 180 / Math.PI;
  const grad = (x, y, z, o) => { const e = 0.002, gx = f(x + e, y, z) - f(x - e, y, z), gy = f(x, y + e, z) - f(x, y - e, z), gz = f(x, y, z + e) - f(x, y, z - e), l = Math.hypot(gx, gy, gz) || 1; o[0] = gx / l; o[1] = gy / l; o[2] = gz / l; return o; };
  const inside = d => { const el = Math.asin(d[1]) * DEG, az = Math.atan2(d[0], d[2]) * DEG; return el > hairline(s.hairline, az) && el < s.topClip; };
  const edgeDir = () => { const az = (rnd() * 2 - 1) * 150, el = (hairline(s.hairline, az) + 0.5 + rnd() * 5) / DEG, a = az / DEG; return [Math.sin(a) * Math.cos(el), Math.sin(el), Math.cos(a) * Math.cos(el)]; };
  const randDir = () => { if (rnd() < s.edge) { const d = edgeDir(); if (inside(d)) return d; } for (let k = 0; k < 200; k++) { const y = rnd() * 1.75 - 0.75, a = rnd() * Math.PI * 2, r = Math.sqrt(1 - y * y), d = [Math.sin(a) * r, y, Math.cos(a) * r]; if (inside(d)) return d; } return [0, 1, 0]; };
  const pos = [], nor = [], colr = [], idx = [], n3 = [0, 0, 0], c = new THREE.Color();
  const shoulder = (p) => { if (!s.shoulders) return; const d = ell(p[0], p[1] + 0.31, p[2] + 0.02, 0.235, 0.115, 0.135); if (d < 0.004) { const e = 0.004, gx = ell(p[0] + e, p[1] + 0.31, p[2] + 0.02, 0.235, 0.115, 0.135) - d, gy = ell(p[0], p[1] + 0.31 + e, p[2] + 0.02, 0.235, 0.115, 0.135) - d, gz = ell(p[0], p[1] + 0.31, p[2] + 0.02 + e, 0.235, 0.115, 0.135) - d, l = Math.hypot(gx, gy, gz) || 1; const k = (0.004 - d); p[0] += gx / l * k; p[1] += gy / l * k; p[2] += gz / l * k; } };
  for (let ci = 0; ci < s.clumps; ci++) {
    const gd = randDir(), ph1 = rnd() * 6.28, ph2 = rnd() * 6.28, lenK = rnd(), tone = 1 + (rnd() - 0.5) * 2 * s.vary, curlDir = rnd() < 0.5 ? -1 : 1, guide = [];
    for (let si = 0; si <= s.per; si++) {
      let d = gd; if (si > 0) { for (let k = 0; k < 20; k++) { const q = [gd[0] + (rnd() - 0.5) * 2 * s.spread, gd[1] + (rnd() - 0.5) * 2 * s.spread, gd[2] + (rnd() - 0.5) * 2 * s.spread], l = Math.hypot(...q); d = [q[0] / l, q[1] / l, q[2] / l]; if (inside(d)) break; d = gd; } }
      const p = project(f, C0, d, 0.22, 0.0012); grad(p[0], p[1], p[2], n3);
      const az = Math.atan2(d[0], d[2]) * DEG, el = Math.asin(d[1]) * DEG, top = sstep(25, 55, el), back = sstep(100, 140, Math.abs(az)) * (1 - top), sideK = (1 - top) * (1 - back);
      const side = Math.abs(p[0] - s.part) < 0.004 ? (rnd() < 0.5 ? -1 : 1) : Math.sign(p[0] - s.part), fr = s.fringe * sstep(60, 25, Math.abs(az)) * sstep(-10, 20, el);
      let v = [side * s.flow[0] * (1 - fr) + side * s.fringeFlow[0] * fr, s.flow[1] * (1 - fr) + s.fringeFlow[1] * fr, s.flow[2] * (1 - fr) + s.fringeFlow[2] * fr];
      { const sb = s.sweepBack * (1 - fr) * sstep(80, 35, Math.abs(az)) * sstep(-5, 15, el); v = [lerp(v[0], side * 0.55, sb), lerp(v[1], 0.2, sb), lerp(v[2], -1, sb)]; }
      const vn = v[0] * n3[0] + v[1] * n3[1] + v[2] * n3[2]; v = [v[0] - n3[0] * vn, v[1] - n3[1] * vn, v[2] - n3[2] * vn]; const vl = Math.hypot(...v) || 1;
      let dir = [n3[0] * s.lift + v[0] / vl * (1 - s.lift), n3[1] * s.lift + v[1] / vl * (1 - s.lift), n3[2] * s.lift + v[2] / vl * (1 - s.lift)];
      const L = lerp(s.len[0], s.len[1], clamp(lenK + (rnd() - 0.5) * 0.25)) * (top * s.lenTop + sideK * s.lenSide + back * s.lenBack) * (1 - 0.45 * fr), ds = L / s.segs, tn = tone * (1 + (rnd() - 0.5) * 0.25);
      const base = pos.length / 3, w0 = s.width * (0.7 + 0.6 * rnd()), tilt = (rnd() - 0.5) * 0.9, pts = [];
      for (let k = 0; k <= s.segs; k++) { const u = k / s.segs, sl = u * L;
        if (k > 0) { const gk = s.gravity * ds * 9 * (1 - s.stiff); dir[1] -= gk; const dl = Math.hypot(...dir); dir = [dir[0] / dl, dir[1] / dl, dir[2] / dl];
          p[0] += dir[0] * ds; p[1] += dir[1] * ds; p[2] += dir[2] * ds;
          let dd = f(p[0], p[1], p[2]) - s.margin; if (dd > 0 && s.hug) { grad(p[0], p[1], p[2], n3); const hk = dd * s.hug * (1 - 0.6 * k / s.segs); p[0] -= n3[0] * hk; p[1] -= n3[1] * hk; p[2] -= n3[2] * hk; const dn = dir[0] * n3[0] + dir[1] * n3[1] + dir[2] * n3[2]; dir = [dir[0] - n3[0] * dn * s.hug, dir[1] - n3[1] * dn * s.hug, dir[2] - n3[2] * dn * s.hug]; dd = 1; }
          if (dd < 0) { grad(p[0], p[1], p[2], n3); p[0] -= n3[0] * dd; p[1] -= n3[1] * dd; p[2] -= n3[2] * dd; const dn = dir[0] * n3[0] + dir[1] * n3[1] + dir[2] * n3[2]; if (dn < 0) { dir = [dir[0] - n3[0] * dn, dir[1] - n3[1] * dn, dir[2] - n3[2] * dn]; } }
          shoulder(p); }
        // lateral offsets: wave, curl, frizz; strands converge on their lock's guide toward the tip
        const ox = [dir[1] * 0 - dir[2] * 1, 0, dir[0]], ol = Math.hypot(ox[0], ox[2]) || 1, e1 = [ox[0] / ol, 0, ox[2] / ol], e2 = [dir[1] * e1[2], dir[2] * e1[0] - dir[0] * e1[2], -dir[1] * e1[0]];
        const env = sstep(0, 0.25, u), wv = s.wave * env * Math.sin(sl * s.waveFreq + ph1), wv2 = s.wave * 0.6 * env * Math.sin(sl * s.waveFreq * 0.63 + ph2);
        const ca = curlDir * (sl / Math.max(L, 1e-4)) * s.curlTurns * 6.283 + ph1, cr = s.curl * env;
        let q = [p[0] + e1[0] * (wv + cr * Math.cos(ca)) + e2[0] * (wv2 + cr * Math.sin(ca)), p[1] + e2[1] * (wv2 + cr * Math.sin(ca)) + (rnd() - 0.5) * s.frizz, p[2] + e1[2] * (wv + cr * Math.cos(ca)) + e2[2] * (wv2 + cr * Math.sin(ca))];
        q[0] += (rnd() - 0.5) * s.frizz; q[2] += (rnd() - 0.5) * s.frizz;
        if (si === 0) guide.push(q.slice()); else { const g = guide[k], cv = s.converge * u; q = [lerp(q[0], g[0], cv), lerp(q[1], g[1], cv), lerp(q[2], g[2], cv)]; }
        pts.push(q); }
      for (let k = 0; k <= s.segs; k++) { const q = pts[k], a = pts[Math.max(0, k - 1)], b = pts[Math.min(s.segs, k + 1)], u = k / s.segs; let tx = b[0] - a[0], ty = b[1] - a[1], tz = b[2] - a[2]; const tl = Math.hypot(tx, ty, tz) || 1; tx /= tl; ty /= tl; tz /= tl;
        let ox = q[0], oy = q[1] - clamp(q[1], -0.06, 0.045), oz = q[2] + 0.012; const ol = Math.hypot(ox, oy, oz) || 1; ox /= ol; oy /= ol; oz /= ol;
        let wx = ty * oz - tz * oy, wy = tz * ox - tx * oz, wz = tx * oy - ty * ox; const wl = Math.hypot(wx, wy, wz) || 1; wx /= wl; wy /= wl; wz /= wl;
        const w = w0 * 0.5 * lerp(1, s.taper, u * u); pos.push(q[0] - wx * w, q[1] - wy * w, q[2] - wz * w, q[0] + wx * w, q[1] + wy * w, q[2] + wz * w);
        for (const sd of [-1, 1]) { let nx = ox + wx * (tilt + sd * 0.75), ny = oy + wy * (tilt + sd * 0.75) + 0.15, nz = oz + wz * (tilt + sd * 0.75); const nl = Math.hypot(nx, ny, nz); nor.push(nx / nl, ny / nl, nz / nl); }
        c.copy(col).lerp(tip, u * u).multiplyScalar(tn * (0.55 + 0.5 * sstep(0, 0.3, u))); colr.push(c.r, c.g, c.b, c.r, c.g, c.b);
        if (k < s.segs) { const i0 = base + k * 2; idx.push(i0, i0 + 1, i0 + 2, i0 + 1, i0 + 3, i0 + 2); } }
    }
  }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3)); g.setAttribute('color', new THREE.Float32BufferAttribute(colr, 3)); g.setIndex(idx);
  const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: s.rough, metalness: 0, side: THREE.DoubleSide });
  const m = new THREE.Mesh(g, mat); m.castShadow = true; m.receiveShadow = true; group.add(m);
  if (s.cap) { const sg = new THREE.SphereGeometry(1, 110, 80), p = sg.attributes.position, keep = new Uint8Array(p.count), P2 = new Float32Array(p.count * 3), N2 = new Float32Array(p.count * 3);
    for (let i = 0; i < p.count; i++) { const d = [p.getX(i), p.getY(i), p.getZ(i)]; const el = Math.asin(clamp(d[1], -1, 1)) * DEG, az = Math.atan2(d[0], d[2]) * DEG; keep[i] = el > hairline(s.hairline, az) + 4 ? 1 : 0; const q = project(f, C0, d, 0.22, 0.0016); P2.set(q, i * 3); grad(q[0], q[1], q[2], n3); N2.set(n3, i * 3); }
    const id = sg.index.array, out = []; for (let t = 0; t < id.length; t += 3) if (keep[id[t]] && keep[id[t + 1]] && keep[id[t + 2]]) out.push(id[t], id[t + 1], id[t + 2]);
    const cg = new THREE.BufferGeometry(); cg.setAttribute('position', new THREE.BufferAttribute(P2, 3)); cg.setAttribute('normal', new THREE.BufferAttribute(N2, 3)); cg.setIndex(out);
    const cm = new THREE.Mesh(cg, new THREE.MeshStandardMaterial({ color: col.clone().multiplyScalar(0.5), roughness: 0.8, side: THREE.DoubleSide })); cm.castShadow = true; group.add(cm); }
  if (s.bun) { const b = s.bun, bg = new THREE.SphereGeometry(b.r ?? 0.045, 20, 14), q = bg.attributes.position, cc = new Float32Array(q.count * 3); for (let i = 0; i < q.count; i++) { const a = Math.atan2(q.getY(i), q.getX(i)), k = 1 + 0.06 * Math.sin(a * 14 + q.getZ(i) * 90); q.setXYZ(i, q.getX(i) * k, q.getY(i) * k, q.getZ(i)); const tn = 0.7 + 0.5 * (0.5 + 0.5 * Math.sin(a * 23 + q.getZ(i) * 140)); cc[i * 3] = col.r * tn; cc[i * 3 + 1] = col.g * tn; cc[i * 3 + 2] = col.b * tn; }
    bg.setAttribute('color', new THREE.BufferAttribute(cc, 3)); bg.computeVertexNormals(); const bm = new THREE.Mesh(bg, mat); bm.position.set(...(b.pos ?? [0, 0.06, -0.1])); bm.scale.set(1, 0.9, 0.85); bm.castShadow = true; group.add(bm); }
  group.userData.strands = m; return group;
}
