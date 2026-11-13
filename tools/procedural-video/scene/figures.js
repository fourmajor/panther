// Articulated 3D figures: jointed body (FK + analytic 2-bone IK), sculpted head with face/hair (scene/face.js,
// scene/hair.js), real hands (scene/hands.js) and a wardrobe of generic outfit parts (collars, coats, straps, cuffs,
// boots, pauldrons, hats, capes, shields...). A figure is described by a plain recipe object; nothing here knows a story.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { mulberry32, clamp, fbm1, lerp, sstep } from './util.js';
import { makeHead } from './face.js';
import { makeHair } from './hair.js';
import { makeHand } from './hands.js';
import { fabric, softSkin, gold } from './materials.js';

const V = (x, y, z) => new THREE.Vector3(x, y, z);
export const MT = v => v == null ? null : v.isMaterial ? v : typeof v === 'number' ? fabric('cloth', v) : fabric(v.k || 'cloth', v.c, v.o || {});
function sh(m, cast = true) { m.castShadow = cast; m.receiveShadow = true; return m; }
const lathe = (pts, seg = 14) => new THREE.LatheGeometry(pts.map(p => new THREE.Vector2(Math.max(p[0], 0), p[1])), seg);
// tapered limb segment hanging from the joint (y: 0 -> -len) with a muscle bulge
function seg(r0, r1, len, bulge = 0.12, at = 0.35) { const pts = [[0, -len - r1 * 0.9]], n = 9; for (let i = n; i >= 0; i--) { const t = i / n; pts.push([lerp(r0, r1, t) * (1 + bulge * Math.exp(-Math.pow((t - at) / 0.28, 2))), -len * t]); } pts.push([r0 * 0.75, r0 * 0.6], [0, r0 * 0.95]); return lathe(pts, 12); }
function limb(parent, pos, L1, L2, r1, r2, mat1, mat2, o = {}) {
  const a = new THREE.Group(); a.position.copy(pos); parent.add(a); a.add(sh(new THREE.Mesh(seg(r1, r1 * 0.82, L1, o.b1 ?? 0.14), mat1)));
  const b = new THREE.Group(); b.position.y = -L1; a.add(b); b.add(sh(new THREE.Mesh(seg(r2, r2 * (o.t2 ?? 0.68), L2, o.b2 ?? 0.16, 0.28), mat2 || mat1)));
  const e = new THREE.Group(); e.position.y = -L2; b.add(e); return { a, b, e, L1, L2, parent };
}
const _m = new THREE.Matrix4(), _q = new THREE.Quaternion(), _q2 = new THREE.Quaternion();
// Analytic two-bone IK. targetW: world target for the limb end; poleW: world direction the elbow/knee should point.
export function ik(l, targetW, poleW) {
  const p = l.parent; p.updateWorldMatrix(true, false);
  const t = p.worldToLocal(targetW.clone()).sub(l.a.position);
  const pole = poleW.clone().applyQuaternion(p.getWorldQuaternion(_q).invert());
  let d = t.length(); const maxd = (l.L1 + l.L2) * 0.999; if (d > maxd) { t.multiplyScalar(maxd / d); d = maxd; } d = Math.max(d, Math.abs(l.L1 - l.L2) + 1e-3);
  const y = t.clone().multiplyScalar(-1 / d), z = pole.multiplyScalar(-1); z.addScaledVector(y, -z.dot(y)); if (z.lengthSq() < 1e-6) z.set(0, 0, 1); z.normalize();
  const x = new THREE.Vector3().crossVectors(y, z);
  l.a.quaternion.setFromRotationMatrix(_m.makeBasis(x, y, z));
  const al = Math.acos(clamp((l.L1 * l.L1 + d * d - l.L2 * l.L2) / (2 * l.L1 * d), -1, 1)), b = Math.PI - Math.acos(clamp((l.L1 * l.L1 + l.L2 * l.L2 - d * d) / (2 * l.L1 * l.L2), -1, 1));
  l.a.rotateX(al); l.b.rotation.set(-b, 0, 0);
}
// Orient a wrist so the hand's grip axis (thumb side, local +z) points along dirW, keeping the fingers near the forearm line.
export function aimWrist(l, dirW, twist = 0) {
  l.b.updateWorldMatrix(true, false); const pq = l.b.getWorldQuaternion(_q), Z = dirW.clone().normalize(), fore = V(0, -1, 0).applyQuaternion(pq);
  const yn = fore.addScaledVector(Z, -fore.dot(Z)); if (yn.lengthSq() < 1e-6) yn.set(0, -1, 0).addScaledVector(Z, Z.y); yn.normalize(); const Y = yn.multiplyScalar(-1), X = new THREE.Vector3().crossVectors(Y, Z);
  _q2.setFromRotationMatrix(_m.makeBasis(X, Y, Z)); l.e.quaternion.copy(pq.invert().multiply(_q2)); if (twist) l.e.rotateZ(twist);
}
// Merge the static meshes directly under every joint group (per material) to keep draw calls down.
export function bake(root) {
  const groups = []; root.traverse(o => { if (o.isGroup && !o.userData.noBake) groups.push(o); });
  for (const g of groups) { let skip = false; for (let p = g; p; p = p.parent) if (p.userData.noBake) skip = true; if (skip) continue;
    const by = new Map(); for (const c of [...g.children]) { if (!c.isMesh || c.userData.dyn || c.geometry.morphAttributes.position) continue; const k = c.material.uuid + (c.castShadow ? 'c' : 'n'); if (!by.has(k)) by.set(k, []); by.get(k).push(c); }
    for (const ms of by.values()) { if (ms.length < 2) continue; const gs = ms.map(m => { m.updateMatrix(); let x = m.geometry.clone(); if (x.index) x = x.toNonIndexed(); x.applyMatrix4(m.matrix); return x; }); const keepC = gs.every(x => x.attributes.color); for (const x of gs) for (const k of Object.keys(x.attributes)) if (k !== 'position' && k !== 'normal' && !(k === 'color' && keepC)) x.deleteAttribute(k);
      if (ms[0].matrix.determinant() < 0) continue;
      const mm = sh(new THREE.Mesh(mergeGeometries(gs, false), ms[0].material), ms[0].castShadow); for (const m of ms) g.remove(m); g.add(mm); } }
}
function hashA(a, seed) { const s = Math.sin(a * 91.7 + seed * 13.1) * 43758.5; return s - Math.floor(s); }

// ---------------------------------------------------------------- outfit parts
// Each part: (f, p, C) where f = figure, p = part recipe, C = shared context { R(y) torso radius, surf(y, ang, off), ... }.
const PARTS = {
  // ring around the torso following a tilted plane: belts (amp 0) and baldrics/cross straps (amp > 0)
  strap(f, p, C) { const n = 40, w = p.w ?? 0.045, pos = [], idx = [], amp = p.amp ?? 0, a0 = p.a0 ?? 0, yc = p.y ?? 0.05, off = p.off ?? 0.008, par = p.on === 'pelvis' ? f.pelvis : f.spine;
    for (let i = 0; i <= n; i++) { const a = i / n * Math.PI * 2, y = yc + amp * Math.cos(a - a0); for (const s of [-1, 1]) { const q = C.surf(clamp(y + s * w / 2, -0.11, f.torso + 0.02), a, off); pos.push(q.x, q.y, q.z); } if (i < n) idx.push(i * 2, i * 2 + 2, i * 2 + 1, i * 2 + 1, i * 2 + 2, i * 2 + 3); }
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals(); const m = sh(new THREE.Mesh(g, MT(p.mat ?? { k: 'leather', c: 0x4a2e1a, o: { side: THREE.DoubleSide } }))); par.add(m);
    if (p.buckle !== false) { const ba = p.buckleAt ?? (amp ? a0 + 1.2 : 0), by = yc + amp * Math.cos(ba - a0), q = C.surf(by, ba, off + 0.006), b = sh(new THREE.Mesh(new THREE.TorusGeometry(w * 0.52, w * 0.13, 5, 4), gold(p.buckleColor ?? 0x9a8a5a))); b.position.copy(q); b.rotation.set(0, ba, Math.PI / 4); b.scale.z = 0.5; par.add(b); }
    for (const pc of p.pouches || []) { const q = C.surf(yc - 0.055, pc.a, off + 0.03), g2 = new THREE.SphereGeometry(1, 10, 8); g2.scale(pc.w ?? 0.05, pc.h ?? 0.06, 0.03); const b = sh(new THREE.Mesh(g2, MT(pc.mat ?? { k: 'leather', c: 0x4a2e1a }))); b.position.copy(q); b.rotation.y = pc.a; par.add(b); const fl = sh(new THREE.Mesh(new THREE.BoxGeometry((pc.w ?? 0.05) * 1.7, 0.035, 0.012), b.material)); fl.position.copy(C.surf(yc - 0.02, pc.a, off + 0.05)); fl.rotation.y = pc.a; par.add(fl); } },
  // skirt / coat tails from the waist: open cylinder with folds, optional front gap, ragged hem, edge trim
  skirt(f, p, C) { const len = p.len, n = p.seg ?? 30, rows = 8, gap = p.gap ?? 0, th0 = p.from ?? gap / 2, thL = p.arc ?? (Math.PI * 2 - gap), r0 = (p.r0 ?? f.hw + 0.09), r1 = p.flare ?? 0.36, y0 = p.y ?? 0.03, seed = f.seed + (p.seed ?? 0);
    const mk = (dr, yTop, yBot, a0, aL, mat, nn, rr) => { const g = new THREE.CylinderGeometry(r0 + dr, r1 + dr, len, nn, rr, true, a0, aL), q = g.attributes.position;
      for (let i = 0; i < q.count; i++) { const y = q.getY(i), v = 0.5 - y / len, a = Math.atan2(q.getX(i), q.getZ(i)); if (v < yTop - 1e-3 || v > yBot + 1e-3) { } const k = 1 + v * (p.fold ?? 0.09) * Math.sin(a * (p.folds ?? 9) + seed) + v * 0.03 * Math.sin(a * 23 + seed * 2); let yy = y; if (p.ragged && v > 0.8) yy += (hashA(Math.round(a * 14), seed) - 0.25) * len * p.ragged * sstep(0.8, 1, v);
        q.setXYZ(i, q.getX(i) * k, yy, q.getZ(i) * k * (p.depth ?? 0.82)); }
      g.computeVertexNormals(); const m = sh(new THREE.Mesh(g, mat)); m.position.y = -len / 2 + y0; (p.on === 'spine' ? f.spine : f.pelvis).add(m); return m; };
    const mat = MT(p.mat ?? 0x2a2622); mat.side = THREE.DoubleSide; f.extras.skirt = mk(0, 0, 1, th0, thL, mat, n, rows);
    if (p.trim) { const tm = MT(p.trim), tw = (p.trimW ?? 0.02) / r1; if (thL < Math.PI * 2 - 0.01) for (const a of [th0, th0 + thL - tw]) mk(0.004, 0, 1, a, tw, tm, 1, rows);
      const hg = new THREE.CylinderGeometry(r1 * 0.985 + 0.006, r1 + 0.006, p.trimW ?? 0.02, n, 1, true, th0, thL), q = hg.attributes.position; for (let i = 0; i < q.count; i++) { const a = Math.atan2(q.getX(i), q.getZ(i)), k = 1 + (p.fold ?? 0.09) * Math.sin(a * (p.folds ?? 9) + seed) + 0.03 * Math.sin(a * 23 + seed * 2); q.setXYZ(i, q.getX(i) * k, q.getY(i), q.getZ(i) * k * (p.depth ?? 0.82)); }
      const hm = sh(new THREE.Mesh(hg, tm)); hm.position.y = -len + y0 + 0.012; if (!p.ragged) f.pelvis.add(hm); } },
  // neck wear
  collar(f, p, C) { const m = MT(p.mat ?? 0x2a2622), k = p.kind ?? 'stand', ch = f.chest;
    if (k === 'stand') { const gap = p.gap ?? 0.9, h = p.h ?? 0.075, g = new THREE.CylinderGeometry(p.rTop ?? 0.07, p.rBot ?? 0.062, h, 18, 2, true, gap / 2, Math.PI * 2 - gap); g.scale(1, 1, 0.92); m.side = THREE.DoubleSide; const c = sh(new THREE.Mesh(g, m)); c.position.set(0, 0.004 + h / 2 + (p.y ?? 0), -0.016); c.rotation.x = p.tilt ?? 0.2; ch.add(c);
      if (p.trim) { const tg = new THREE.CylinderGeometry((p.rTop ?? 0.07) + 0.003, (p.rTop ?? 0.07) + 0.002, 0.012, 18, 1, true, gap / 2, Math.PI * 2 - gap); tg.scale(1, 1, 0.92); const t = sh(new THREE.Mesh(tg, MT(p.trim))); t.material.side = THREE.DoubleSide; t.position.set(0, 0.004 + h + (p.y ?? 0) - 0.004, -0.016 - (p.tilt ?? 0.2) * h * 0.5); t.rotation.x = p.tilt ?? 0.2; ch.add(t); } }
    else if (k === 'shirt') { // open V of shirt (and optionally bare chest) on the torso front, plus two collar wings
      const yT = f.torso + 0.03, yB = f.torso - (p.depth ?? 0.2), w = p.w ?? 0.5; const strip = (wk, off, mat) => { const pos = [], idx = [], nR = 8; for (let i = 0; i <= nR; i++) { const t = i / nR, y = lerp(yB, yT, t), a = wk * t; for (const s of [-1, 1]) { const q = C.surf(y, s * a, off); pos.push(q.x, q.y, q.z); } if (i < nR) idx.push(i * 2, i * 2 + 1, i * 2 + 2, i * 2 + 1, i * 2 + 3, i * 2 + 2); }
        const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals(); mat.side = THREE.DoubleSide; f.spine.add(sh(new THREE.Mesh(g, mat))); };
      strip(w, 0.006, m); if (p.skin) strip(w * 0.5, 0.009, softSkin(p.skin));
      { const og = new THREE.CylinderGeometry(p.rTop ?? 0.088, 0.058, 0.05, 18, 2, true, 0.75, Math.PI * 2 - 1.5); og.scale(1, 1, 0.95); const oc = sh(new THREE.Mesh(og, m)); oc.position.set(0, 0.03, -0.014); oc.rotation.x = 0.28; ch.add(oc); } }
    else if (k === 'fur' || k === 'scarf') { const R = p.R ?? f.sw * 0.66, r = p.r ?? 0.055, g = new THREE.TorusGeometry(R, r, 12, 36), q = g.attributes.position, rnd = mulberry32(f.seed * 31 + 5);
      for (let i = 0; i < q.count; i++) { const x = q.getX(i), y = q.getY(i), z = q.getZ(i), a = Math.atan2(y, x), kk = 1 + (k === 'fur' ? 0.16 : 0.1) * Math.sin(a * 9 + z * 60) + 0.1 * Math.sin(a * 17 + 2) + (k === 'scarf' ? 0.25 * Math.sin(a * 3 + 1) * (z > 0 ? 1 : 0.3) : 0); q.setXYZ(i, x * (1 + (kk - 1) * 0.25), y * (1 + (kk - 1) * 0.25), z * kk); }
      g.rotateX(Math.PI / 2); g.scale(1, p.flat ?? 0.8, p.depth ?? 0.82); g.computeVertexNormals(); const c = sh(new THREE.Mesh(g, m)); c.position.set(0, p.y ?? 0.035, p.z ?? -0.01); c.rotation.x = p.tilt ?? 0.22; ch.add(c);
      if (k === 'fur') { const gs = []; for (let i = 0; i < 700; i++) { const a = rnd() * 6.283, b = rnd() * Math.PI * 1.3 - 0.9, cg = new THREE.ConeGeometry(0.0065, 0.026 + rnd() * 0.022, 3); cg.translate(0, 0.012, 0); cg.rotateZ((rnd() - 0.5) * 0.9); cg.rotateX((rnd() - 0.5) * 0.9); const M4 = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(0, -a, 0)).multiply(new THREE.Matrix4().makeTranslation(R, 0, 0)).multiply(new THREE.Matrix4().makeRotationZ(b - Math.PI / 2 + (rnd() - 0.5))).multiply(new THREE.Matrix4().makeTranslation(0, r * 0.85, 0)); cg.applyMatrix4(M4); gs.push(cg); }
        const tg = mergeGeometries(gs); tg.scale(1, p.flat ?? 0.8, p.depth ?? 0.82); const t = sh(new THREE.Mesh(tg, m)); t.position.copy(c.position); t.rotation.x = c.rotation.x; ch.add(t); }
      if (k === 'scarf') { const g2 = new THREE.TorusGeometry(R * 0.72, r * 0.8, 10, 28), q2 = g2.attributes.position; for (let i = 0; i < q2.count; i++) { const a = Math.atan2(q2.getY(i), q2.getX(i)); q2.setZ(i, q2.getZ(i) * (1 + 0.2 * Math.sin(a * 7))); } g2.rotateX(Math.PI / 2); g2.scale(1, 0.9, 0.86); g2.computeVertexNormals(); const c2 = sh(new THREE.Mesh(g2, m)); c2.position.set(0.008, (p.y ?? 0.035) + 0.05, 0.0); c2.rotation.set(0.1, 0, 0.12); ch.add(c2);
        const dg = new THREE.ConeGeometry(R * 0.9, 0.2, 14, 3, true, -1.1, 2.2), dq = dg.attributes.position; for (let i = 0; i < dq.count; i++) { const a = Math.atan2(dq.getX(i), dq.getZ(i)); dq.setY(i, dq.getY(i) + 0.02 * Math.sin(a * 6)); } dg.scale(1, -1, 0.75); dg.computeVertexNormals(); m.side = THREE.DoubleSide; const d = sh(new THREE.Mesh(dg, m)); d.position.set(0, (p.y ?? 0.035) - 0.07, 0.035); ch.add(d); } } },
  // rows of fastenings down the front
  fastening(f, p, C) { const n = p.n ?? 5, y0 = p.y0 ?? f.torso - 0.12, y1 = p.y1 ?? 0.08, kind = p.kind ?? 'button', gm = gold(p.color ?? 0xa8904a);
    for (let i = 0; i < n; i++) { const y = lerp(y0, y1, n === 1 ? 0 : i / (n - 1)), a = p.a ?? 0, q = C.surf(y, a, 0.012);
      if (kind === 'button') { const g = new THREE.SphereGeometry(p.r ?? 0.009, 8, 6); g.scale(1, 1, 0.5); const b = sh(new THREE.Mesh(g, gm), false); b.position.copy(q); f.spine.add(b); }
      else { const st = sh(new THREE.Mesh(new THREE.BoxGeometry(p.w ?? 0.085, 0.016, 0.006), MT(p.strap ?? { k: 'leather', c: 0x3a2416 })), false); st.position.copy(q); f.spine.add(st); const b = sh(new THREE.Mesh(new THREE.TorusGeometry(0.011, 0.003, 4, 4), gm), false); b.position.copy(q).add(V(0.012, 0, 0.004)); b.rotation.z = Math.PI / 4; f.spine.add(b); } } },
  // vertical trim strips on the torso front (coat edges, embroidery)
  trim(f, p, C) { const m = MT(p.mat ?? gold()), w = p.w ?? 0.014, y0 = p.y0 ?? f.torso - 0.01, y1 = p.y1 ?? -0.02, nR = 10;
    for (const s of p.sides ?? [-1, 1]) { const pos = [], idx = []; for (let i = 0; i <= nR; i++) { const t = i / nR, y = lerp(y0, y1, t), a = s * lerp(p.aTop ?? p.a ?? 0.3, p.a ?? 0.3, t), rr = C.R(y), da = w / rr / 2; for (const e of [-1, 1]) { const q = C.surf(y, a + e * da, p.off ?? 0.009); pos.push(q.x, q.y, q.z); } if (i < nR) idx.push(i * 2, i * 2 + 2, i * 2 + 1, i * 2 + 1, i * 2 + 2, i * 2 + 3); }
      const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals(); m.side = THREE.DoubleSide; f.spine.add(sh(new THREE.Mesh(g, m), false)); } },
  // a coloured panel on the torso front/back (waistcoat front, tabard, cuirass plate, embroidery field)
  panel(f, p, C) { const m = MT(p.mat), y0 = p.y0 ?? f.torso - 0.02, y1 = p.y1 ?? 0, a0 = p.a ?? 0.55, nR = 10, nA = 10, pos = [], idx = [];
    for (let i = 0; i <= nR; i++) { const y = lerp(y0, y1, i / nR), aa = lerp(p.aTop ?? a0, a0, i / nR); for (let j = 0; j <= nA; j++) { const q = C.surf(y, (p.center ?? 0) + lerp(-aa, aa, j / nA), p.off ?? 0.006); pos.push(q.x, q.y, q.z); } }
    for (let i = 0; i < nR; i++) for (let j = 0; j < nA; j++) { const a = i * (nA + 1) + j; idx.push(a, a + nA + 1, a + 1, a + 1, a + nA + 1, a + nA + 2); }
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals(); m.side = THREE.DoubleSide; f.spine.add(sh(new THREE.Mesh(g, m))); },
  pauldron(f, p, C) { const m = MT(p.mat ?? { k: 'leather', c: 0x15140f }), k = p.kind ?? 'feather';
    for (const s of p.sides ?? [-1, 1]) { const G = new THREE.Group(); G.position.set(s * (f.sw + 0.012), 0.012, 0); f.chest.add(G);
      if (k === 'feather') { const rnd = mulberry32(f.seed * 17 + (s > 0 ? 3 : 9)), tiers = p.tiers ?? 4; for (let t = 0; t < tiers; t++) { const nn = 5 + t; for (let i = 0; i < nn; i++) { const a = (i / (nn - 1) - 0.5) * 2.6, len = 0.11 + 0.035 * t + rnd() * 0.02, g = new THREE.ConeGeometry(0.034 + 0.004 * t, len, 5, 1); g.scale(1, 1, 0.22); g.rotateX(Math.PI); g.translate(0, -len / 2, 0);
            const lf = sh(new THREE.Mesh(g, m)); lf.position.set(s * (0.012 + t * 0.012) * Math.cos(a), 0.035 - t * 0.022, Math.sin(a) * (0.05 + t * 0.014)); lf.rotation.set(Math.sin(a) * (0.75 + 0.1 * t), s * (Math.PI / 2 - a * 0.8), s * (0.85 - t * 0.14) * Math.cos(a) + (rnd() - 0.5) * 0.12, 'YXZ'); G.add(lf); } }
        const cg = new THREE.SphereGeometry(0.085, 12, 8, 0, Math.PI * 2, 0, Math.PI * 0.55); cg.scale(1.1, 0.7, 1.15); const cp = sh(new THREE.Mesh(cg, m)); cp.position.y = 0.015; cp.rotation.z = -s * 0.4; G.add(cp); }
      else if (k === 'cap') { const cg = new THREE.SphereGeometry(p.r ?? 0.082, 14, 8, 0, Math.PI * 2, 0, Math.PI * 0.55); cg.scale(1.1, 0.8, 1.2); const cp = sh(new THREE.Mesh(cg, m)); cp.position.y = 0.0; cp.rotation.z = -s * 0.45; G.add(cp); if (p.trim) { const t = sh(new THREE.Mesh(new THREE.TorusGeometry((p.r ?? 0.082) * 1.02, 0.006, 5, 20), MT(p.trim))); t.rotation.set(Math.PI / 2, 0, 0); t.scale.set(1.1, 1.2, 1); t.position.y = -0.01; t.rotation.y = 0; G.add(t); t.rotation.z = 0; t.rotateY(0); t.rotation.x = Math.PI / 2 - s * 0; } }
      else if (k === 'epaulette') { const gm = gold(p.color ?? 0xa8904a), pl = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.034, 0.038, 0.008, 12), gm)); pl.position.set(-s * 0.012, 0.028, 0); pl.rotation.z = -s * 0.42; pl.scale.z = 1.3; G.add(pl); for (let i = 0; i < 9; i++) { const a = (i / 8 - 0.5) * 2.4, fr = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.003, 0.03, 4), gm), false); fr.position.set(s * 0.02 * Math.cos(a) + s * 0.008, 0.008, 0.046 * Math.sin(a)); fr.rotation.z = s * 0.55; G.add(fr); } } } },
  // forearm / wrist wear
  cuff(f, p, C) { const k = p.kind ?? 'ruffle', m = MT(p.mat ?? { k: 'linen', c: 0xe8e2d2 }), r = f.rArm * 0.85;
    for (const a of p.arms ?? [f.armL, f.armR]) { const L2 = a.L2;
      if (k === 'ruffle') { const g = lathe([[r * 0.75, 0.02], [r * 0.95, 0.0], [r * (p.size ?? 1.9), -0.035], [r * (p.size ?? 1.9) * 1.25, -0.085]], 28), q = g.attributes.position; for (let i = 0; i < q.count; i++) { const an = Math.atan2(q.getX(i), q.getZ(i)), v = clamp(-q.getY(i) / 0.085), kk = 1 + 0.2 * v * Math.sin(an * 11) + 0.08 * v * Math.sin(an * 5 + 1); q.setXYZ(i, q.getX(i) * kk, q.getY(i) + 0.012 * v * Math.sin(an * 11 + 1.5), q.getZ(i) * kk); } g.computeVertexNormals(); m.side = THREE.DoubleSide; const c = sh(new THREE.Mesh(g, m)); c.position.y = -L2 + 0.045; a.b.add(c);
        if (p.puff) { const pg = new THREE.SphereGeometry(1, 14, 10); pg.scale(r * 1.75, 0.075, r * 1.75); const pm = sh(new THREE.Mesh(pg, m)); pm.position.y = -L2 + 0.085; a.b.add(pm); } }
      else if (k === 'bracer') { const len = L2 * (p.len ?? 0.62), g = lathe([[r * 1.12, -L2 + len + 0.02], [r * 1.22, -L2 + len], [r * 0.98, -L2 + 0.03], [r * 0.92, -L2 + 0.02]], 12); m.side = THREE.DoubleSide; a.b.add(sh(new THREE.Mesh(g, m))); for (let i = 0; i < (p.straps ?? 2); i++) { const y = -L2 + 0.05 + (len - 0.07) * (i + 0.5) / (p.straps ?? 2), t = sh(new THREE.Mesh(new THREE.TorusGeometry(r * lerp(1.0, 1.22, (y + L2) / len) + 0.003, 0.006, 5, 14), MT(p.strap ?? { k: 'leather', c: 0x2e1c10 })), false); t.rotation.x = Math.PI / 2; t.position.y = y; a.b.add(t); } }
      else if (k === 'coat') { const h = p.h ?? 0.09, g = lathe([[r * 1.05, -L2 + 0.03 + h], [r * (p.size ?? 1.55), -L2 + 0.03 + h * 0.95], [r * (p.size ?? 1.55) * 1.04, -L2 + 0.03], [r * 0.9, -L2 + 0.03]], 16); m.side = THREE.DoubleSide; a.b.add(sh(new THREE.Mesh(g, m)));
        if (p.trim) { for (const yy of [-L2 + 0.03 + h * 0.95, -L2 + 0.034]) { const t = sh(new THREE.Mesh(new THREE.TorusGeometry(r * (p.size ?? 1.55) * 1.03, 0.004, 4, 18), MT(p.trim)), false); t.rotation.x = Math.PI / 2; t.position.y = yy; a.b.add(t); } for (let i = 0; i < 3; i++) { const bt = sh(new THREE.Mesh(new THREE.SphereGeometry(0.008, 6, 5), MT(p.trim)), false); const sgn = a === f.armL ? 1 : -1; bt.position.set(sgn * r * (p.size ?? 1.55) * 1.02, -L2 + 0.045 + i * 0.022, 0); a.b.add(bt); } } } } },
  sleeve(f, p, C) { const m = MT(p.mat ?? { k: 'linen', c: 0xd8cfb8 }); for (const a of p.arms ?? [f.armL, f.armR]) { const g = seg(f.rArm * (p.size ?? 1.35), f.rArm * (p.size ?? 1.35) * 0.9, a.L1 * (p.len ?? 0.9), 0.2, 0.5); const s = sh(new THREE.Mesh(g, m)); s.position.y = -a.L1 * (p.from ?? 0.05); a.a.add(s);
      if (p.band) { const t = sh(new THREE.Mesh(new THREE.TorusGeometry(f.rArm * 1.25, 0.008, 5, 14), MT(p.band)), false); t.rotation.x = Math.PI / 2; t.position.y = -a.L1 * 0.55; a.a.add(t); } } },
  boots(f, p, C) { const m = MT(p.mat ?? { k: 'leather', c: 0x3a2618 }), r = f.rLeg * 0.8, h = p.h ?? 0.8;
    for (const l of [f.legL, f.legR]) { const T2 = l.L2, top = -T2 * (1 - h), g = lathe([[r * 0.72, -T2 + 0.01], [r * 0.82, -T2 + 0.06], [r * 1.0, -T2 * 0.55], [r * 1.18, top - 0.03], [r * 1.22, top]], 14); m.side = THREE.DoubleSide; l.b.add(sh(new THREE.Mesh(g, m)));
      if (p.cuff) { const cg = lathe([[r * 1.2, top - p.cuff], [r * 1.42, top - p.cuff + 0.005], [r * 1.48, top + 0.012], [r * 1.24, top + 0.016]], 14); l.b.add(sh(new THREE.Mesh(cg, MT(p.cuffMat ?? p.mat ?? { k: 'leather', c: 0x3a2618 })))); l.b.children[l.b.children.length - 1].material.side = THREE.DoubleSide; }
      for (let i = 0; i < (p.straps ?? 1); i++) { const y = -T2 + 0.07 + i * (p.strapGap ?? 0.09), t = sh(new THREE.Mesh(new THREE.TorusGeometry(r * lerp(0.85, 1.05, i / 3) + 0.004, 0.007, 5, 14), MT(p.strap ?? { k: 'leather', c: 0x2a1a10 })), false); t.rotation.set(Math.PI / 2 + (p.wrap ? (i % 2 ? 0.3 : -0.3) : 0), 0, 0); t.position.y = y; l.b.add(t); if (!p.wrap) { const b = sh(new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.02, 0.006), gold(0x8a7a52)), false); b.position.set((l === f.legL ? 1 : -1) * (r + 0.008), y, 0.01); l.b.add(b); } } } },
  // thigh / knee wear
  legwear(f, p, C) { const m = MT(p.mat ?? { k: 'leather', c: 0x3a2618 }); for (const l of p.legs ?? [f.legL, f.legR]) { const y = -l.L1 * (p.at ?? 0.45), t = sh(new THREE.Mesh(new THREE.CylinderGeometry(f.rLeg * 1.08, f.rLeg * 1.0, p.h ?? 0.05, 12, 1, true), m)); m.side = THREE.DoubleSide; t.position.y = y; l.a.add(t);
      if (p.knee) { const kg = new THREE.SphereGeometry(f.rLeg * 0.95, 10, 8, 0, Math.PI); const k = sh(new THREE.Mesh(kg, m)); k.position.set(0, -l.L1 + 0.01, 0.02); k.scale.set(1, 1.3, 0.8); l.a.add(k); } } },
  hat(f, p, C) { const m = MT(p.mat ?? 0x2a1a30), G = new THREE.Group(), hr = 0.094; G.position.set(0, p.y ?? 0.088, p.z ?? -0.012); G.rotation.set(p.tilt ?? -0.1, p.yaw ?? 0, p.roll ?? 0.05); f.headG.add(G);
    const cg = new THREE.SphereGeometry(hr, 22, 10, 0, Math.PI * 2, 0, Math.PI * 0.5); cg.scale(1, 0.62, 1.1); G.add(sh(new THREE.Mesh(cg, m)));
    const nA = 60, nR = 7, bw = p.brim ?? 0.115, pos = [], idx = [], rim = [];
    for (let i = 0; i <= nA; i++) { const a = i / nA * Math.PI * 2, lift = Math.pow(0.5 + 0.5 * Math.cos(3 * a + Math.PI), 0.75), wdt = bw * (1 + 0.38 * (1 - lift)), cx = Math.sin(a), cz = Math.cos(a);
      for (let j = 0; j <= nR; j++) { const rho = j / nR, ph = lift * 1.22 * Math.pow(rho, 0.8), rr = hr * 1.0 + wdt * rho * Math.cos(ph * 0.9), y = wdt * rho * Math.sin(ph) - 0.03 * rho * rho * (1 - lift); pos.push(cx * rr, y, cz * rr * 1.1); if (j === nR && i < nA) rim.push(V(cx * rr, y, cz * rr * 1.1)); }
      if (i < nA) for (let j = 0; j < nR; j++) { const q = i * (nR + 1) + j; idx.push(q, q + 1, q + nR + 1, q + 1, q + nR + 2, q + nR + 1); } }
    const bg = new THREE.BufferGeometry(); bg.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); bg.setIndex(idx); bg.computeVertexNormals(); m.side = THREE.DoubleSide; G.add(sh(new THREE.Mesh(bg, m)));
    if (p.trim) { const tg = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(rim, true), 120, 0.0045, 5, true); G.add(sh(new THREE.Mesh(tg, MT(p.trim)), false)); const band = sh(new THREE.Mesh(new THREE.TorusGeometry(hr * 1.01, 0.006, 5, 24), MT(p.trim)), false); band.rotation.x = Math.PI / 2; band.scale.y = 1.1; band.position.y = 0.006; G.add(band); }
    if (p.feather) { const fp = p.feather, rnd = mulberry32(f.seed * 91 + 7), fpos = [], fnor = [], fidx = [], H = fp.len ?? 0.4, base = V(fp.x ?? 0.085, 0.03, fp.z ?? -0.03), N = 46;
      const spine = t => V(base.x + 0.035 * t + 0.03 * t * t, base.y + H * (t - 0.18 * t * t * t), base.z - 0.05 * t - 0.11 * t * t * t);
      const rg = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(Array.from({ length: 8 }, (_, i) => spine(i / 7))), 20, 0.0028, 4, false); G.add(sh(new THREE.Mesh(rg, MT(fp.mat ?? { k: 'linen', c: 0xf2efe6 })), false));
      for (let layer = 0; layer < 3; layer++) for (let i = 0; i < N; i++) for (const s of [-1, 1]) { const t = 0.12 + 0.88 * (i + rnd() * 0.8) / N, c0 = spine(t), tg = spine(Math.min(1, t + 0.02)).sub(c0).normalize(), sideV = V(Math.cos(layer * 1.05 + 0.3) * s, 0, Math.sin(layer * 1.05 + 0.3) * s), len = (fp.w ?? 0.075) * Math.sin(Math.PI * Math.min(1, t * 1.02 + 0.06)) ** 0.5 * (0.75 + 0.5 * rnd()), w = 0.007, nseg = 4, b0 = fpos.length / 3;
          for (let k = 0; k <= nseg; k++) { const u = k / nseg, q = c0.clone().addScaledVector(sideV, len * u).addScaledVector(tg, len * (0.35 * u + 0.25 * u * u)).add(V(0, -len * 0.55 * u * u, (rnd() - 0.5) * 0.004)); const ww = w * (1 - 0.6 * u); fpos.push(q.x - tg.x * ww, q.y - tg.y * ww, q.z - tg.z * ww, q.x + tg.x * ww, q.y + tg.y * ww, q.z + tg.z * ww); const nn = V(sideV.z, 0.5, -sideV.x).normalize(); fnor.push(nn.x, nn.y, nn.z, nn.x, nn.y, nn.z); if (k < nseg) fidx.push(b0 + k * 2, b0 + k * 2 + 1, b0 + k * 2 + 2, b0 + k * 2 + 1, b0 + k * 2 + 3, b0 + k * 2 + 2); } }
      const fg = new THREE.BufferGeometry(); fg.setAttribute('position', new THREE.Float32BufferAttribute(fpos, 3)); fg.setAttribute('normal', new THREE.Float32BufferAttribute(fnor, 3)); fg.setIndex(fidx);
      const fm = new THREE.MeshStandardMaterial({ color: fp.color ?? 0xf4f0e6, roughness: 0.85, side: THREE.DoubleSide, emissive: fp.color ?? 0xf4f0e6, emissiveIntensity: 0.04 }); const fe = sh(new THREE.Mesh(fg, fm)); fe.userData.dyn = true; G.add(fe);
      const br = sh(new THREE.Mesh(new THREE.SphereGeometry(0.014, 8, 6), gold(0xa08a50)), false); br.position.copy(base).add(V(0.012, -0.005, 0.01)); G.add(br); f.extras.feather = fe; }
    f.extras.hat = G; },
  // round shield strapped to a forearm
  shield(f, p, C) { const a = p.arm === 'R' ? f.armR : f.armL, s = a === f.armL ? 1 : -1, R = p.r ?? 0.36, G = new THREE.Group(); G.position.set(s * 0.065, -a.L2 * 0.55, 0.02); G.rotation.set(0, 0, s * -Math.PI / 2); a.b.add(G); G.userData.noBake = false;
    const dg = new THREE.CylinderGeometry(R, R, 0.028, 44); const disc = sh(new THREE.Mesh(dg, MT(p.wood ?? { k: 'wood', c: 0x6a4424 }))); disc.rotation.y = 0.5; G.add(disc);
    const iron = MT(p.iron ?? { k: 'metal', c: 0x3a3b3e, o: { rough: 0.55 } }), rim = sh(new THREE.Mesh(new THREE.TorusGeometry(R, 0.024, 8, 44), iron)); rim.rotation.x = Math.PI / 2; rim.scale.z = 0.9; G.add(rim);
    for (const ry of [0, Math.PI / 2]) { const st = sh(new THREE.Mesh(new THREE.BoxGeometry(R * 2, 0.008, 0.055), iron)); st.position.y = 0.017; st.rotation.y = ry; G.add(st); }
    const bg = new THREE.SphereGeometry(R * 0.25, 18, 10, 0, Math.PI * 2, 0, Math.PI * 0.5); bg.scale(1, 0.75, 1); const boss = sh(new THREE.Mesh(bg, iron)); boss.position.y = 0.016; G.add(boss);
    const gm = gold(0x9a7a3a); for (let i = 0; i < 16; i++) { const an = i / 16 * Math.PI * 2, rv = sh(new THREE.Mesh(new THREE.SphereGeometry(0.011, 6, 5), gm), false); rv.position.set(Math.cos(an) * R, 0.02, Math.sin(an) * R); G.add(rv); }
    for (let i = 0; i < 8; i++) { const an = i / 4 * Math.PI * 0.5 * 2, rr = R * (i < 4 ? 0.55 : 0.8), rv = sh(new THREE.Mesh(new THREE.SphereGeometry(0.009, 6, 5), gm), false); rv.position.set(Math.cos(an) * rr, 0.024, Math.sin(an) * rr); G.add(rv); }
    f.extras.shield = G; },
  // sheathed blade at the hip (or on the back)
  scabbard(f, p, C) { const G = new THREE.Group(), len = p.len ?? 0.85, m = MT(p.mat ?? { k: 'leather', c: 0x2e1c12 }), gm = gold(p.metal ?? 0x9a8a5a);
    if (p.back) { G.position.set(p.x ?? -0.05, p.y ?? 0.1, -(f.o.depth ?? 0.66) * f.sw - 0.03); G.rotation.set(0, 0, p.rz ?? -0.45); f.chest.add(G); } else { const s = p.side ?? 1; G.position.set(s * (f.hw + 0.085), p.y ?? 0.02, 0.01); G.rotation.set(p.rx ?? 0.5, 0, s * (p.rz ?? 0.12)); f.pelvis.add(G); }
    const g = lathe([[0.006, -len], [0.012, -len + 0.02], [p.w ?? 0.017, -0.02], [p.w ?? 0.017, 0]], 8); g.scale(1, 1, p.flat ?? 0.5); G.add(sh(new THREE.Mesh(g, m)));
    const ch = lathe([[0.004, -len - 0.012], [0.0135, -len + 0.03], [0.014, -len + 0.06]], 8); ch.scale(1, 1, p.flat ?? 0.5); G.add(sh(new THREE.Mesh(ch, gm), false)); const th = sh(new THREE.Mesh(new THREE.CylinderGeometry((p.w ?? 0.017) + 0.002, (p.w ?? 0.017) + 0.002, 0.04, 8), gm), false); th.scale.z = p.flat ?? 0.5; th.position.y = -0.02; G.add(th);
    if (p.hilt) { const h = p.hilt === 'rapier' ? rapierHilt() : swordHilt(p.hiltO); h.position.y = 0.012; G.add(h); } f.extras.scabbard = G; },
  pendant(f, p, C) { const q = C.surf(f.torso - (p.drop ?? 0.1), 0, 0.014), g = sh(new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.026, 0.006), gold(p.color ?? 0x9aa0b0, 0.25)), false); g.position.copy(q); f.spine.add(g);
    for (const s of [-1, 1]) { const c = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.0015, 0.0015, 0.1, 4), gold(0xa8904a)), false); c.position.copy(C.surf(f.torso - (p.drop ?? 0.1) + 0.05, s * 0.2, 0.012)); c.rotation.z = s * 0.45; f.spine.add(c); } },
  earrings(f, p, C) { const E = f.face.field, gm = gold(p.color ?? 0xc8a040, 0.25); for (const s of [-1, 1]) for (let i = 0; i < (p.n ?? 1); i++) { const r = sh(new THREE.Mesh(new THREE.TorusGeometry((p.r ?? 0.014) * (1 - 0.25 * i), 0.0022, 6, 16), gm), false); r.position.set(s * (0.078 * (f.face.spec.W) + 0.002), -0.03 - (p.r ?? 0.014) * (1 - 0.25 * i) + i * 0.012, -0.012 + i * 0.006); r.rotation.y = Math.PI / 2 + s * 0.3; f.headG.add(r); } },
  // small hanging charms (bones, fetishes) scattered over the torso and skirt
  fetishes(f, p, C) { const rnd = mulberry32(f.seed * 53 + 1), bm = MT(p.mat ?? { k: 'bone', c: 0xb9ae90 }), cm = MT({ k: 'leather', c: 0x1a120c });
    for (let i = 0; i < (p.n ?? 16); i++) { const a = (rnd() - 0.5) * 3.6, y = lerp(f.torso - 0.05, -0.05, rnd()), q = C.surf(y, a, 0.015), G = new THREE.Group(); G.position.copy(q); G.rotation.set(0, a, (rnd() - 0.5) * 0.5); f.spine.add(G);
      const st = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.0015, 0.0015, 0.05, 4), cm), false); st.position.y = -0.02; G.add(st); const kind = Math.floor(rnd() * 3);
      if (kind === 0) { const b = sh(new THREE.Mesh(lathe([[0, -0.03], [0.007, -0.027], [0.004, -0.018], [0.004, 0.018], [0.007, 0.027], [0, 0.03]], 6), bm)); b.position.y = -0.07; b.rotation.z = (rnd() - 0.5) * 1.2; G.add(b); }
      else if (kind === 1) { const sk = new THREE.SphereGeometry(0.016, 8, 6); sk.scale(0.8, 1, 1.15); const b = sh(new THREE.Mesh(sk, bm)); b.position.y = -0.06; G.add(b); }
      else { for (let k = 0; k < 3; k++) { const t = sh(new THREE.Mesh(new THREE.ConeGeometry(0.004, 0.035, 4), bm), false); t.position.set((k - 1) * 0.009, -0.06, 0); t.rotation.z = Math.PI + (k - 1) * 0.3; G.add(t); } } } },
};
export function swordHilt(o = {}) { const g = new THREE.Group(), gm = gold(o.metal ?? 0xb8943c);
  const guard = sh(new THREE.Mesh(new THREE.BoxGeometry(o.guardW ?? 0.22, 0.022, 0.03), gm)); guard.position.y = 0.012; g.add(guard); for (const s of [-1, 1]) { const e = sh(new THREE.Mesh(new THREE.SphereGeometry(0.017, 8, 6), gm), false); e.position.set(s * (o.guardW ?? 0.22) / 2, 0.012, 0); g.add(e); }
  const grip = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.0155, 0.0175, 0.17, 10), fabric('leather', o.grip ?? 0x2a1a12))); grip.position.y = -0.085; g.add(grip);
  for (let i = 0; i < 6; i++) { const w = sh(new THREE.Mesh(new THREE.TorusGeometry(0.0172, 0.0022, 4, 10), gm), false); w.rotation.x = Math.PI / 2 + 0.25; w.position.y = -0.02 - i * 0.026; g.add(w); }
  const pom = sh(new THREE.Mesh(new THREE.SphereGeometry(0.027, 10, 8), gm)); pom.scale.y = 0.8; pom.position.y = -0.19; g.add(pom); return g; }
export function rapierHilt() { const g = new THREE.Group(), gm = gold(0xa89058, 0.3);
  const grip = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.014, 0.12, 8), fabric('leather', 0x20140e))); grip.position.y = -0.06; g.add(grip); const pom = sh(new THREE.Mesh(new THREE.SphereGeometry(0.019, 8, 6), gm)); pom.position.y = -0.135; g.add(pom);
  const q = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.005, 0.005, 0.2, 6), gm), false); q.rotation.z = Math.PI / 2; q.position.y = 0.006; g.add(q);
  for (let i = 0; i < 3; i++) { const r = sh(new THREE.Mesh(new THREE.TorusGeometry(0.05 - i * 0.008, 0.0035, 5, 20), gm), false); r.position.set(0, 0.035 + i * 0.012, 0.008); r.rotation.set(Math.PI / 2 + 0.25 * (i - 1), 0.3 * i, 0); r.scale.set(1, 0.8, 1); g.add(r); }
  const kb = sh(new THREE.Mesh(new THREE.TorusGeometry(0.075, 0.004, 5, 16, Math.PI), gm), false); kb.position.set(0, -0.06, 0.0); kb.rotation.set(0, Math.PI / 2, -Math.PI / 2); kb.scale.set(1, 0.62, 1); g.add(kb); return g; }

/* Recipe: { seed, scale, sw, hw, hip, torso, L1, L2, T1, T2, rArm, rLeg, depth, headScale, neckLen,
     head: {...face spec}, hair: spec | [specs], hands: { glove:{mat, fingerless}, claw, size, thin },
     mats: { torso, upperArm, foreArm, leg, shin, foot }, outfit: [ {type, ...}, ... ],
     cloak: { mat|color, len, span, flare, center, ragged, y } , env } */
export function makeFigure(o = {}) {
  const seed = o.seed || 1, rnd = mulberry32(seed * 977);
  const sw = o.sw ?? 0.2, hw = o.hw ?? 0.1, torso = o.torso ?? 0.52, L1 = o.L1 ?? 0.3, L2 = o.L2 ?? 0.27, T1 = o.T1 ?? 0.46, T2 = o.T2 ?? 0.45, footH = 0.065, hip = o.hip ?? (T1 + T2 + 0.02 + footH);
  const rArm = o.rArm ?? 0.05, rLeg = o.rLeg ?? 0.072, depth = o.depth ?? 0.66, M = o.mats || {}, skinHex = (o.head && o.head.skin) ?? 0xc79a78;
  const mTorso = MT(M.torso ?? 0x2a2622), mUpper = MT(M.upperArm ?? M.torso ?? 0x2a2622), mFore = MT(M.foreArm ?? M.upperArm ?? M.torso ?? 0x2a2622), mLeg = MT(M.leg ?? 0x1c1a19), mShin = MT(M.shin ?? M.leg ?? 0x1c1a19), mFoot = MT(M.foot ?? M.shin ?? { k: 'leather', c: 0x2a1c12 }), mSkin = softSkin(skinHex);
  const root = new THREE.Group(), pelvis = new THREE.Group(); pelvis.position.y = hip; root.add(pelvis);
  const spine = new THREE.Group(); pelvis.add(spine);
  const f = { root, pelvis, spine, o, hip, torso, seed, sw, hw, rArm, rLeg, extras: {}, t: 0 };
  const ww = hw + 0.072 * (o.waist ?? 1), prof = [[0.01, -0.12], [hw * 1.25, -0.11], [hw + 0.078, -0.02], [ww, 0.06], [ww + 0.004, 0.17], [sw * 0.84, 0.34], [sw * 0.96, torso - 0.06], [sw * 0.8, torso - 0.005], [sw * 0.5, torso + 0.03], [0.04, torso + 0.046], [0.0, torso + 0.048]];
  const tg = lathe(prof, 22); tg.scale(1, 1, depth); spine.add(sh(new THREE.Mesh(tg, mTorso)));
  const R = y => { for (let i = 1; i < prof.length; i++) if (y <= prof[i][1]) { const a = prof[i - 1], b = prof[i]; return lerp(a[0], b[0], clamp((y - a[1]) / (b[1] - a[1] || 1))); } return prof[prof.length - 1][0]; };
  const C = { R, surf: (y, a, off = 0) => { const r = R(y) + off; return V(Math.sin(a) * r, y, Math.cos(a) * r * depth + (Math.cos(a) > 0 ? off * (1 - depth) * Math.cos(a) : 0)); } };
  const hipsG = new THREE.SphereGeometry(1, 14, 10); hipsG.scale(hw + 0.078, 0.12, (hw + 0.078) * depth); const hips = sh(new THREE.Mesh(hipsG, mLeg)); hips.position.y = -0.03; pelvis.add(hips);
  const chest = new THREE.Group(); chest.position.y = torso; spine.add(chest); f.chest = chest;
  const neck = new THREE.Group(); neck.position.y = 0.08 + (o.neckLen ?? 0); chest.add(neck); f.neck = neck;
  const head = new THREE.Group(); head.position.y = 0.106; neck.add(head); f.head = head;
  const headG = new THREE.Group(); headG.userData.noBake = true; headG.scale.setScalar(o.headScale ?? 1); head.add(headG); f.headG = headG;
  const H = makeHead({ seed, ...(o.head || {}) }, { env: o.env, eyeEnv: o.eyeEnv }); headG.add(H.group); f.face = H;
  for (const hs of [].concat(o.hair || [])) headG.add(makeHair(H, { seed, ...hs }));
  // arms + hands
  f.armL = limb(chest, V(sw, -0.035, 0), L1, L2, rArm, rArm * 0.85, mUpper, mFore); f.armR = limb(chest, V(-sw, -0.035, 0), L1, L2, rArm, rArm * 0.85, mUpper, mFore);
  const hs = o.hands || {}, glove = hs.glove ? { mat: MT(hs.glove.mat), fingerless: hs.glove.fingerless } : null, nail = new THREE.MeshStandardMaterial({ color: hs.nail ?? new THREE.Color(skinHex).lerp(new THREE.Color(0xf0d8d0), 0.35).getHex(), roughness: 0.3 });
  f.handL = makeHand({ side: -1, skin: mSkin, nail, glove, claw: hs.claw, size: hs.size ?? 1, thin: hs.thin, thinFinger: hs.thinFinger, longTip: hs.longTip }); f.armL.e.add(f.handL.group);
  f.handR = makeHand({ side: 1, skin: mSkin, nail, glove, claw: hs.claw, size: hs.size ?? 1, thin: hs.thin, thinFinger: hs.thinFinger, longTip: hs.longTip }); f.armR.e.add(f.handR.group);
  f.armL.hand = f.handL; f.armR.hand = f.handR;
  // legs + feet
  f.legL = limb(pelvis, V(hw, -0.02, 0), T1, T2, rLeg, rLeg * 0.8, mLeg, mShin, { b1: 0.1, b2: 0.22, t2: 0.62 }); f.legR = limb(pelvis, V(-hw, -0.02, 0), T1, T2, rLeg, rLeg * 0.8, mLeg, mShin, { b1: 0.1, b2: 0.22, t2: 0.62 });
  const fs = o.footSize ?? 1; for (const l of [f.legL, f.legR]) { const fg = new THREE.CapsuleGeometry(0.043 * fs, 0.15 * fs, 4, 10); fg.rotateX(Math.PI / 2); fg.scale(1, 0.78, 1); const ft = sh(new THREE.Mesh(fg, mFoot)); ft.position.set(0, -footH + 0.036 * fs, 0.065 * fs); l.e.add(ft);
    const hg = new THREE.SphereGeometry(0.046 * fs, 10, 8); const hl = sh(new THREE.Mesh(hg, mFoot)); hl.position.set(0, -footH + 0.04 * fs, -0.012); l.e.add(hl); const sole = sh(new THREE.Mesh(new THREE.BoxGeometry(0.082 * fs, 0.014, 0.25 * fs), fabric('leather', 0x120d0a))); sole.position.set(0, -footH + 0.007, 0.055 * fs); l.e.add(sole); }
  for (const p of o.outfit || []) { const fn = PARTS[p.type]; if (!fn) throw new Error('unknown outfit part: ' + p.type); fn(f, p, C); }
  // cloak / cape: grid hanging from the shoulders, re-posed every frame
  if (o.cloak) { const c = o.cloak, nu = c.nu ?? 30, nv = 12, g = new THREE.PlaneGeometry(1, 1, nu, nv), mat = MT(c.mat ?? c.color ?? 0x2a1f1c); mat.side = THREE.DoubleSide; const m = sh(new THREE.Mesh(g, mat)); m.frustumCulled = false; m.userData.dyn = true; chest.add(m);
    const hem = []; for (let i = 0; i <= nu; i++) hem.push(c.ragged ? 1 - c.ragged * (0.15 + 0.85 * hashA(i * 1.37, seed)) * (hashA(i * 3.1, seed + 2) < 0.55 ? 1 : 0.25) : 1);
    f.cloak = { m, nu, nv, len: c.len ?? 1.15, span: c.span ?? 2.5, flare: c.flare ?? 0.26, r0: (c.r0 ?? sw + 0.05), center: c.center ?? 0, y: c.y ?? 0.045, hem, depth: c.depth ?? 0.78, drape: c.drape ?? 0 }; }
  f.cloakUpdate = (t, wind = 0, trail = 0) => { const c = f.cloak; if (!c) return; const p = c.m.geometry.attributes.position; let i = 0;
    for (let jv = 0; jv <= c.nv; jv++) for (let iu = 0; iu <= c.nu; iu++, i++) { const v0 = jv / c.nv, v = v0 * (jv === c.nv ? c.hem[iu] : lerp(1, c.hem[iu], v0 * v0)), u = iu / c.nu * 2 - 1, phi = u * c.span + c.center;
      const fold = 1 + 0.085 * v * Math.sin(phi * 6 + seed * 3) + 0.03 * v * Math.sin(phi * 13 + seed);
      const r = (c.r0 + v * c.flare) * fold, sway = v * v * (0.05 * Math.sin(t * 1.1 + seed + u * 2) + wind * (0.6 + 0.4 * Math.sin(t * 3.1 + u * 3 + v * 4 + seed)));
      p.setXYZ(i, Math.sin(phi) * r + sway * 0.6, c.y - v * c.len - 0.03 * Math.cos(phi) * (1 - v) - c.drape * (1 - Math.cos(u * 1.5)) * 0.1 * (1 - v), -Math.cos(phi) * r * c.depth - sway - trail * v * v); }
    p.needsUpdate = true; c.m.geometry.computeVertexNormals(); };
  bake(root);
  // base pose: relaxed stand with breathing and micro-motion (all functions of t)
  f.pose = (t, k = {}) => { const s = seed * 1.7; f.t = t;
    pelvis.position.set(0, hip + (k.crouch ? -k.crouch : 0), 0); pelvis.rotation.set(0, 0, 0);
    spine.rotation.set((k.lean ?? 0.03) + 0.012 * Math.sin(t * 1.35 + s), 0, 0.012 * Math.sin(t * 0.55 + s));
    chest.rotation.set(0.018 * Math.sin(t * 1.35 + s + 0.6), k.turn ?? 0, 0); chest.position.y = torso + 0.005 * Math.sin(t * 1.35 + s);
    neck.rotation.set((k.nod ?? 0) + 0.03 * fbm1(t * 0.4, seed), (k.look ?? 0) + 0.07 * fbm1(t * 0.3, seed + 5), 0); head.rotation.set(0, 0, 0);
    for (const [a, sg] of [[f.armL, 1], [f.armR, -1]]) { a.a.quaternion.identity(); a.a.rotation.set(0.06 + 0.02 * Math.sin(t * 1.35 + s), 0, sg * (k.armOut ?? 0.12)); a.b.rotation.set(-0.22, 0, 0); a.e.quaternion.identity(); a.e.rotation.set(0, 0, 0); }
    for (const [l, sg] of [[f.legL, 1], [f.legR, -1]]) { l.a.quaternion.identity(); l.a.rotation.set(0, 0, sg * 0.035); l.b.rotation.set(0, 0, 0); l.e.rotation.set(0, 0, 0); }
    f.handL.pose(k.handL || 'relax'); f.handR.pose(k.handR || 'relax');
    H.animate(t, null, k.expr || {});
    f.cloakUpdate(t, k.wind ?? 0, k.trail ?? 0); };
  // speech + expression for this frame (call after pose): sp from the lip-sync driver, expr = face offsets
  f.talk = (sp, expr = {}) => { H.animate(f.t, sp, expr); if (sp && sp.active) { neck.rotation.x += 0.05 * sp.emph - 0.02 * sp.jaw; neck.rotation.y += 0.02 * Math.sin(f.t * 2.3 + seed); } };
  f.walk = (ph, amp = 1) => { const s = Math.sin(ph), c = Math.cos(ph);
    f.legL.a.rotation.x = -s * 0.5 * amp; f.legR.a.rotation.x = s * 0.5 * amp; f.legL.b.rotation.x = Math.max(0, c) * 0.75 * amp + 0.05; f.legR.b.rotation.x = Math.max(0, -c) * 0.75 * amp + 0.05;
    f.armL.a.rotation.x += s * 0.35 * amp; f.armR.a.rotation.x -= s * 0.35 * amp; pelvis.position.y = hip - 0.02 + Math.abs(c) * 0.03 * amp; spine.rotation.z += s * 0.03 * amp; chest.rotation.y += s * 0.08 * amp; };
  // put the hand's grip anchor at gripW with the grip axis along dirW (two IK refinements)
  f.grasp = (arm, gripW, dirW, poleW, twist = 0) => { const tgt = gripW.clone(), g = new THREE.Vector3();
    for (let i = 0; i < 3; i++) { ik(arm, tgt, poleW); aimWrist(arm, dirW, twist); arm.hand.grip.updateWorldMatrix(true, false); arm.hand.grip.getWorldPosition(g); tgt.add(gripW).sub(g); } };
  if (o.scale) root.scale.setScalar(o.scale);
  return f;
}

// ---- props ----
export function makeSword({ len = 1.05, holy = false, worn = true } = {}) {
  const g = new THREE.Group(), steel = new THREE.MeshStandardMaterial({ color: 0xc8ccd4, metalness: 0.92, roughness: 0.24, emissive: holy ? 0xffe2a0 : 0x000000, emissiveIntensity: 0 });
  const s = new THREE.Shape(); s.moveTo(0, 0.022); s.lineTo(0.031, 0.022); s.lineTo(0.026, len * 0.82); s.lineTo(0, len + 0.03); s.lineTo(-0.026, len * 0.82); s.lineTo(-0.031, 0.022); s.lineTo(0, 0.022);
  const bg = new THREE.ExtrudeGeometry(s, { depth: 0.004, bevelEnabled: true, bevelThickness: 0.0035, bevelSize: 0.012, bevelSegments: 1 }); bg.translate(0, 0, -0.002); g.add(sh(new THREE.Mesh(bg, steel)));
  const fu = sh(new THREE.Mesh(new THREE.BoxGeometry(0.012, len * 0.62, 0.0125), new THREE.MeshStandardMaterial({ color: 0x8a8f98, metalness: 0.9, roughness: 0.4 })), false); fu.position.y = 0.03 + len * 0.31; g.add(fu);
  g.add(swordHilt()); g.steel = steel; return g;
}
export function makeRapier() { const g = new THREE.Group(), steel = new THREE.MeshStandardMaterial({ color: 0xd0d4dc, metalness: 0.92, roughness: 0.2 }); const b = new THREE.CylinderGeometry(0.0028, 0.008, 1.0, 6); b.scale(1, 1, 0.6); b.translate(0, 0.51, 0); g.add(sh(new THREE.Mesh(b, steel))); g.add(rapierHilt()); g.steel = steel; return g; }
export function makeSabre({ len = 0.82 } = {}) { const g = new THREE.Group(), steel = new THREE.MeshStandardMaterial({ color: 0xaeb3ba, metalness: 0.9, roughness: 0.3 });
  const s = new THREE.Shape(), n = 14; for (let i = 0; i <= n; i++) { const t = i / n, x = 0.11 * t * t - 0.024 * (1 - t), y = 0.02 + len * t; if (i === 0) s.moveTo(x, y); else s.lineTo(x, y); } for (let i = n; i >= 0; i--) { const t = i / n; s.lineTo(0.11 * t * t + 0.03 * (1 - t * t * 0.9) + 0.012 * Math.sin(Math.PI * t), 0.02 + len * t * 0.985); }
  const bg = new THREE.ExtrudeGeometry(s, { depth: 0.003, bevelEnabled: true, bevelThickness: 0.003, bevelSize: 0.008, bevelSegments: 1 }); bg.translate(-0.003, 0, -0.0015); g.add(sh(new THREE.Mesh(bg, steel)));
  g.add(swordHilt({ guardW: 0.13, metal: 0x8a7a52, grip: 0x1c140e })); g.steel = steel; return g; }
export function makeDagger() { const g = new THREE.Group(); const b = new THREE.ConeGeometry(0.022, 0.3, 4); b.scale(1, 1, 0.25); b.translate(0, 0.19, 0); g.add(sh(new THREE.Mesh(b, new THREE.MeshStandardMaterial({ color: 0xc0c4cc, metalness: 0.9, roughness: 0.25 })))); const h = swordHilt({ guardW: 0.09 }); h.scale.setScalar(0.6); g.add(h); return g; }
export function makeAxe({ rusty = true } = {}) { const g = new THREE.Group(); const s = new THREE.CylinderGeometry(0.018, 0.021, 1.25, 8); s.translate(0, 0.4, 0); g.add(sh(new THREE.Mesh(s, fabric('wood', 0x3a2a1c))));
  const sp = new THREE.Shape(); sp.moveTo(0, -0.075); sp.lineTo(0.17, -0.2); sp.lineTo(0.2, -0.13); sp.lineTo(0.235, -0.1); sp.quadraticCurveTo(0.3, 0.01, 0.22, 0.13); sp.lineTo(0.2, 0.11); sp.lineTo(0.19, 0.21); sp.lineTo(0, 0.075); sp.lineTo(-0.05, 0.05); sp.lineTo(-0.075, 0); sp.lineTo(-0.05, -0.05); sp.lineTo(0, -0.075);
  const bg = new THREE.ExtrudeGeometry(sp, { depth: 0.012, bevelEnabled: true, bevelThickness: 0.004, bevelSize: 0.014, bevelSegments: 1 }); bg.translate(0.012, 0.9, -0.006); g.add(sh(new THREE.Mesh(bg, fabric(rusty ? 'rust' : 'metal', 0x6a6e74, { rough: 0.5, metal: 0.85 }))));
  for (const y of [0.83, 0.97]) { const b = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.026, 0.026, 0.03, 8), fabric('rust', 0x55585c, { metal: 0.8 })), false); b.position.y = y; g.add(b); } return g; }
