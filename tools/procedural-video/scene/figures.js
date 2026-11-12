// Stylised articulated 3D figures built from capsules / lathes, with FK poses and analytic 2-bone IK.
import * as THREE from 'three';
import { mulberry32, clamp, fbm1, lerp } from './util.js';
const V = (x, y, z) => new THREE.Vector3(x, y, z);
const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.9, metalness: 0, ...o });
function sh(m) { m.castShadow = true; m.receiveShadow = true; return m; }
function cap(r, len, mat) { const g = new THREE.CapsuleGeometry(r, Math.max(len - 2 * r, 0.01), 4, 10); g.translate(0, -len / 2, 0); return sh(new THREE.Mesh(g, mat)); }
function limb(parent, pos, L1, L2, r1, r2, mat1, mat2) {
  const a = new THREE.Group(); a.position.copy(pos); parent.add(a); a.add(cap(r1, L1 + r1 * 0.5, mat1));
  const b = new THREE.Group(); b.position.y = -L1; a.add(b); b.add(cap(r2, L2 + r2 * 0.5, mat2 || mat1));
  const e = new THREE.Group(); e.position.y = -L2; b.add(e); return { a, b, e, L1, L2, parent };
}
const _m = new THREE.Matrix4(), _q = new THREE.Quaternion();
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
function cloakGeom(nu, nv) { const g = new THREE.PlaneGeometry(1, 1, nu, nv); return g; }
/* options: scale, sw (shoulder half-width), hip, torso, L1,L2 (arm), T1,T2 (leg), rArm,rLeg, headR,
   body,cloth,skin colours, cloak:{color,len,span,flare}, hood, hat:'brim'|'point', armor, skirt:{len,flare,color,ragged}, kind:'human'|'gaunt'|'skeleton' */
export function makeFigure(o = {}) {
  const kind = o.kind || 'human', seed = o.seed || 1, rnd = mulberry32(seed * 977);
  const sw = o.sw ?? 0.2, hw = o.hw ?? 0.1, hip = o.hip ?? 0.95, torso = o.torso ?? 0.52, L1 = o.L1 ?? 0.3, L2 = o.L2 ?? 0.3, T1 = o.T1 ?? 0.47, T2 = o.T2 ?? 0.48;
  const rArm = o.rArm ?? 0.05, rLeg = o.rLeg ?? 0.072, headR = o.headR ?? 0.112;
  const bone = kind === 'skeleton';
  const mBody = o.bodyMat || std(o.body ?? 0x2a2622, bone ? { roughness: 0.6 } : {}), mLimb = o.limbMat || std(o.limb ?? o.body ?? 0x2a2622), mSkin = std(o.skin ?? 0x1c1613, { roughness: 0.8 });
  const mLeg = std(o.leg ?? 0x1c1a19), mMetal = std(0x767a84, { metalness: 0.8, roughness: 0.42 });
  const root = new THREE.Group(), pelvis = new THREE.Group(); pelvis.position.y = hip; root.add(pelvis);
  const spine = new THREE.Group(); pelvis.add(spine);
  const f = { root, pelvis, spine, o, hip, torso, seed, extras: {} };
  if (!bone) {
    const tm = o.armor ? mMetal : mBody;
    const prof = [[0.01, -0.12], [hw * 1.25, -0.11], [hw + 0.075, 0], [hw + 0.05, 0.17], [sw * 0.82, 0.34], [sw * 0.95, torso - 0.05], [sw * 0.6, torso + 0.03], [0.055, torso + 0.07], [0.05, torso + 0.13]];
    const tg = new THREE.LatheGeometry(prof.map(p => new THREE.Vector2(p[0], p[1])), 18); tg.scale(1, 1, o.depth ?? 0.66);
    spine.add(sh(new THREE.Mesh(tg, tm)));
    if (o.armor) { const belt = sh(new THREE.Mesh(new THREE.TorusGeometry(hw + 0.085, 0.03, 6, 18), std(0x3a2a1a))); belt.rotation.x = Math.PI / 2; belt.scale.z = 1; belt.scale.y = 0.7; spine.add(belt); }
  } else {
    spine.add(cap(0.022, torso + 0.1, mBody)).position.y = torso + 0.08;
    for (let i = 0; i < 5; i++) { const r = sh(new THREE.Mesh(new THREE.TorusGeometry(0.13 - Math.abs(i - 1.5) * 0.012, 0.014, 5, 14), mBody)); r.rotation.x = Math.PI / 2 + 0.25; r.scale.y = 0.7; r.position.y = torso - 0.06 - i * 0.075; spine.add(r); }
    const pv = sh(new THREE.Mesh(new THREE.TorusGeometry(0.1, 0.03, 5, 12), mBody)); pv.rotation.x = Math.PI / 2; pv.scale.y = 0.6; spine.add(pv);
    const sb = cap(0.02, sw * 2, mBody); sb.rotation.z = Math.PI / 2; sb.position.set(-sw, torso, 0); spine.add(sb);
  }
  const chest = new THREE.Group(); chest.position.y = torso; spine.add(chest); f.chest = chest;
  const neck = new THREE.Group(); neck.position.y = 0.08; chest.add(neck); f.neck = neck;
  const head = new THREE.Group(); head.position.y = headR * 0.95; neck.add(head); f.head = head;
  if (kind === 'gaunt') {
    const hm = sh(new THREE.Mesh(new THREE.SphereGeometry(headR, 16, 12), mSkin)); hm.scale.set(0.8, 1.2, 0.55); head.add(hm);
    const cres = sh(new THREE.Mesh(new THREE.TorusGeometry(headR * 1.25, headR * 0.42, 8, 24, Math.PI * 1.25), mSkin)); cres.rotation.set(0, -Math.PI / 2, 0); cres.rotation.z = Math.PI * 0.375; cres.position.z = headR * 0.75; cres.scale.set(1, 1, 0.55);
    const cg = new THREE.Group(); cg.rotation.y = -Math.PI / 2; const c2 = sh(new THREE.Mesh(new THREE.TorusGeometry(headR * 1.15, headR * 0.4, 8, 24, Math.PI * 1.2), mSkin)); c2.rotation.z = Math.PI - Math.PI * 0.6; c2.scale.z = 0.6; cg.add(c2); cg.position.z = headR * 1.05; head.add(cg);
    const mEye = new THREE.MeshStandardMaterial({ color: 0x221a00, emissive: 0xffc81e, emissiveIntensity: 2.2 }); f.extras.eyeMat = mEye;
    for (const s of [-1, 1]) { const e = new THREE.Mesh(new THREE.SphereGeometry(0.014, 8, 6), mEye); e.position.set(s * 0.04, 0.03, headR * 0.62); head.add(e); }
    const mHair = std(0x77746a, { roughness: 1 });
    for (let i = 0; i < 22; i++) { const a = (rnd() - 0.5) * Math.PI * 1.5 + Math.PI, len = 0.3 + rnd() * 0.5; const g = new THREE.ConeGeometry(0.018 + rnd() * 0.014, len, 5); g.translate(0, -len / 2, 0); const s = sh(new THREE.Mesh(g, mHair)); s.position.set(Math.sin(a) * headR * 0.75, headR * (0.7 + rnd() * 0.4), Math.cos(a) * headR * 0.5); s.rotation.set((rnd() - 0.3) * 0.5 * Math.cos(a), 0, Math.sin(a) * 0.35 + (rnd() - 0.5) * 0.2); head.add(s); }
    const mGold = std(0xd8b25a, { metalness: 0.9, roughness: 0.3 });
    for (const s of [-1, 1]) { const e = sh(new THREE.Mesh(new THREE.TorusGeometry(0.035, 0.007, 6, 14), mGold)); e.position.set(s * headR * 0.85, -0.06, 0); e.rotation.y = Math.PI / 2; head.add(e); }
    const mBone = std(0x8f8a7a, { roughness: 0.6 });
    for (let i = 0; i < 12; i++) { const b = cap(0.012, 0.07 + rnd() * 0.08, mBone); const a = (rnd() - 0.5) * 2.2; b.position.set(Math.sin(a) * (sw * 0.8), -0.08 - rnd() * 0.42, Math.cos(a) * 0.12 + 0.02); b.rotation.z = (rnd() - 0.5) * 0.8; chest.add(b); }
  } else if (bone) {
    const sk = sh(new THREE.Mesh(new THREE.SphereGeometry(headR, 14, 10), mBody)); sk.scale.set(0.86, 1, 1); head.add(sk);
    const jaw = sh(new THREE.Mesh(new THREE.BoxGeometry(headR * 1.1, headR * 0.5, headR * 0.9), mBody)); jaw.position.set(0, -headR * 0.85, headR * 0.25); head.add(jaw);
    const dk = new THREE.MeshBasicMaterial({ color: 0x020203 });
    for (const s of [-1, 1]) { const e = new THREE.Mesh(new THREE.SphereGeometry(headR * 0.3, 8, 6), dk); e.position.set(s * headR * 0.38, headR * 0.05, headR * 0.8); head.add(e); }
  } else {
    const hm = sh(new THREE.Mesh(new THREE.SphereGeometry(headR, 16, 12), o.helm ? mMetal : mSkin)); hm.scale.set(0.88, 1.08, 0.96); head.add(hm);
    if (o.helm) { const ng = sh(new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.11, 0.02), mMetal)); ng.position.set(0, -0.02, headR * 0.95); head.add(ng); const cr = sh(new THREE.Mesh(new THREE.TorusGeometry(headR * 0.98, 0.012, 5, 16, Math.PI), mMetal)); cr.rotation.y = Math.PI / 2; cr.position.y = 0.01; head.add(cr);
      const av = sh(new THREE.Mesh(new THREE.CylinderGeometry(headR * 0.95, headR * 1.3, 0.13, 14, 1, true, Math.PI * 0.75, Math.PI * 1.5), std(0x55585e, { metalness: 0.6, roughness: 0.5, side: THREE.DoubleSide }))); av.position.y = -headR * 0.95; head.add(av); }
  }
  const mCloth = std(o.cloth ?? 0x231d1b, { side: THREE.DoubleSide, roughness: 0.95 });
  if (o.hood) {
    const hg = new THREE.SphereGeometry(headR * 1.38, 18, 12, Math.PI / 2 + 0.75, Math.PI * 2 - 1.5); const hd = sh(new THREE.Mesh(hg, mCloth)); hd.scale.set(1.02, 1.14, 1.34); hd.position.set(0, 0.014, 0.012); head.add(hd);
    const pk = sh(new THREE.Mesh(new THREE.ConeGeometry(headR * 0.75, headR * 2.6, 10), mCloth)); pk.position.set(0, headR * 0.95, -headR * 1.15); pk.rotation.x = -2.0; head.add(pk);
    const cw = sh(new THREE.Mesh(new THREE.ConeGeometry(sw * 1.08, 0.22, 16, 1, true), mCloth)); cw.scale.z = 0.8; cw.position.y = 0.02; chest.add(cw);
  }
  if (o.hat === 'brim') { const hm = std(o.hatColor ?? 0x1d1a22); const c = sh(new THREE.Mesh(new THREE.CylinderGeometry(headR * 0.82, headR * 0.98, 0.11, 14), hm)); c.position.y = headR * 0.95; head.add(c); const b = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.27, 0.27, 0.014, 22), hm)); b.position.y = headR * 0.62; b.rotation.set(0.08, 0, -0.18); head.add(b); const fe = sh(new THREE.Mesh(new THREE.ConeGeometry(0.03, 0.34, 5), std(0x8a1c1c))); fe.position.set(-0.11, headR * 1.3, -0.08); fe.rotation.set(-0.9, 0, 0.5); head.add(fe); }
  if (o.hat === 'point') { const hm = std(o.hatColor ?? 0x1c2030); const c = sh(new THREE.Mesh(new THREE.ConeGeometry(headR * 1.05, 0.38, 14), hm)); c.position.set(0, headR * 0.7 + 0.19, -0.02); c.rotation.x = -0.25; head.add(c); const b = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.26, 0.014, 22), hm)); b.position.y = headR * 0.62; head.add(b); }
  const armMat = o.armor ? mMetal : mLimb, handMat = bone ? mBody : (o.gloves ? std(0x1a1614) : mSkin);
  f.armL = limb(chest, V(sw, -0.035, 0), L1, L2, rArm, rArm * 0.85, armMat); f.armR = limb(chest, V(-sw, -0.035, 0), L1, L2, rArm, rArm * 0.85, armMat);
  for (const a of [f.armL, f.armR]) { const h = sh(new THREE.Mesh(new THREE.SphereGeometry(rArm * (bone ? 0.8 : 1.05), 8, 6), handMat)); h.scale.set(0.8, 1.35, 1); h.position.y = -0.045; a.e.add(h); }
  if (kind === 'gaunt') for (const a of [f.armL, f.armR]) for (let i = 0; i < 4; i++) { const g = new THREE.ConeGeometry(0.009, 0.15, 4); g.translate(0, -0.075, 0); const fg = sh(new THREE.Mesh(g, mSkin)); fg.position.set((i - 1.5) * 0.016, -0.07, 0); fg.rotation.set(-0.25, 0, (i - 1.5) * 0.14); a.e.add(fg); }
  if (o.armor) for (const s of [-1, 1]) { const p = sh(new THREE.Mesh(new THREE.SphereGeometry(0.105, 12, 8, 0, Math.PI * 2, 0, Math.PI * 0.6), mMetal)); p.scale.set(1.15, 0.85, 1.15); p.position.set(s * (sw + 0.02), 0.0, 0); p.rotation.z = -s * 0.35; chest.add(p); }
  const legMat = bone ? mBody : (o.armor ? std(0x4a4d55, { metalness: 0.6, roughness: 0.5 }) : mLeg);
  f.legL = limb(pelvis, V(hw, -0.02, 0), T1, T2, rLeg, rLeg * 0.8, legMat); f.legR = limb(pelvis, V(-hw, -0.02, 0), T1, T2, rLeg, rLeg * 0.8, legMat);
  for (const l of [f.legL, f.legR]) { const ft = sh(new THREE.Mesh(new THREE.BoxGeometry(rLeg * 1.5, 0.07, 0.25), legMat)); ft.position.set(0, -0.02, 0.07); l.e.add(ft); }
  // skirt / robe (lathe from pelvis down)
  if (o.skirt) { const s = o.skirt, n = 22, rows = 6, g = new THREE.CylinderGeometry(hw + 0.085, s.flare ?? 0.36, s.len, n, rows, true); const p = g.attributes.position;
    for (let i = 0; i < p.count; i++) { const y = p.getY(i), v = 0.5 - y / s.len, a = Math.atan2(p.getZ(i), p.getX(i)); const k = 1 + v * 0.1 * Math.sin(a * 7 + seed); let yy = y; if (s.ragged && v > 0.95) yy += (hashA(a, seed) - 0.3) * s.len * 0.22; p.setXYZ(i, p.getX(i) * k, yy, p.getZ(i) * k * 0.85); }
    g.computeVertexNormals(); const m = sh(new THREE.Mesh(g, std(s.color ?? o.body ?? 0x2a2622, { side: THREE.DoubleSide, roughness: 0.95 }))); m.position.y = -s.len / 2 + 0.03; pelvis.add(m); f.extras.skirt = m; }
  // cloak / cape: grid hanging from the shoulders, re-posed every frame
  if (o.cloak) { const c = o.cloak, nu = 22, nv = 10, g = cloakGeom(nu, nv); const m = sh(new THREE.Mesh(g, std(c.color ?? 0x2a1f1c, { side: THREE.DoubleSide, roughness: 0.96 }))); m.frustumCulled = false; chest.add(m);
    f.cloak = { m, nu, nv, len: c.len ?? 1.15, span: c.span ?? 2.5, flare: c.flare ?? 0.26, r0: sw + 0.045 }; }
  f.cloakUpdate = (t, wind = 0, trail = 0) => { const c = f.cloak; if (!c) return; const p = c.m.geometry.attributes.position; let i = 0;
    for (let jv = 0; jv <= c.nv; jv++) for (let iu = 0; iu <= c.nu; iu++, i++) { const v = jv / c.nv, u = iu / c.nu * 2 - 1, phi = u * c.span;
      const fold = 1 + 0.085 * v * Math.sin(phi * 6 + seed * 3) + 0.03 * v * Math.sin(phi * 13 + seed);
      const r = (c.r0 + v * c.flare) * fold, sway = v * v * (0.05 * Math.sin(t * 1.1 + seed + u * 2) + wind * (0.6 + 0.4 * Math.sin(t * 3.1 + u * 3 + v * 4 + seed)));
      p.setXYZ(i, Math.sin(phi) * r + sway * 0.6, 0.045 - v * c.len - 0.03 * Math.cos(phi) * (1 - v), -Math.cos(phi) * r * 0.78 - sway - trail * v * v); }
    p.needsUpdate = true; c.m.geometry.computeVertexNormals(); };
  // base pose: relaxed stand with breathing and micro-motion (all functions of t)
  f.pose = (t, k = {}) => { const s = seed * 1.7;
    pelvis.position.set(0, hip + (k.crouch ? -k.crouch : 0), 0); pelvis.rotation.set(0, 0, 0);
    spine.rotation.set((k.lean ?? 0.03) + 0.012 * Math.sin(t * 1.35 + s), 0, 0.012 * Math.sin(t * 0.55 + s));
    chest.rotation.set(0.018 * Math.sin(t * 1.35 + s + 0.6), k.turn ?? 0, 0); chest.position.y = torso + 0.005 * Math.sin(t * 1.35 + s);
    neck.rotation.set((k.nod ?? 0) + 0.03 * fbm1(t * 0.4, seed), (k.look ?? 0) + 0.07 * fbm1(t * 0.3, seed + 5), 0);
    for (const [a, sg] of [[f.armL, 1], [f.armR, -1]]) { a.a.quaternion.identity(); a.a.rotation.set(0.06 + 0.02 * Math.sin(t * 1.35 + s), 0, sg * (k.armOut ?? 0.1)); a.b.rotation.set(-0.22, 0, 0); a.e.rotation.set(0, 0, 0); }
    for (const [l, sg] of [[f.legL, 1], [f.legR, -1]]) { l.a.quaternion.identity(); l.a.rotation.set(0, 0, sg * 0.035); l.b.rotation.set(0, 0, 0); l.e.rotation.set(0, 0, 0); }
    f.cloakUpdate(t, k.wind ?? 0, k.trail ?? 0); };
  f.walk = (ph, amp = 1) => { const s = Math.sin(ph), c = Math.cos(ph);
    f.legL.a.rotation.x = -s * 0.5 * amp; f.legR.a.rotation.x = s * 0.5 * amp; f.legL.b.rotation.x = Math.max(0, c) * 0.75 * amp + 0.05; f.legR.b.rotation.x = Math.max(0, -c) * 0.75 * amp + 0.05;
    f.armL.a.rotation.x += s * 0.35 * amp; f.armR.a.rotation.x -= s * 0.35 * amp; pelvis.position.y = hip - 0.02 + Math.abs(c) * 0.03 * amp; spine.rotation.z += s * 0.03 * amp; chest.rotation.y += s * 0.08 * amp; };
  if (o.scale) root.scale.setScalar(o.scale);
  return f;
}
function hashA(a, seed) { const s = Math.sin(a * 91.7 + seed * 13.1) * 43758.5; return s - Math.floor(s); }

// ---- props ----
export function makeSword({ len = 1.05, holy = false } = {}) {
  const g = new THREE.Group(), steel = std(0xc8ccd4, { metalness: 0.9, roughness: 0.22, emissive: holy ? 0xffe2a0 : 0x000000, emissiveIntensity: 0 });
  const bg = new THREE.CylinderGeometry(0.036, 0.036, len, 4, 1); bg.scale(1, 1, 0.18); bg.translate(0, len / 2 + 0.03, 0); g.add(sh(new THREE.Mesh(bg, steel)));
  const tip = new THREE.ConeGeometry(0.036, 0.1, 4); tip.scale(1, 1, 0.18); tip.translate(0, len + 0.08, 0); g.add(sh(new THREE.Mesh(tip, steel)));
  const gold = std(0xb8943c, { metalness: 0.9, roughness: 0.35 });
  const guard = sh(new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.028, 0.035), gold)); guard.position.y = 0.02; g.add(guard);
  const grip = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.017, 0.017, 0.2, 8), std(0x2a1a12))); grip.position.y = -0.09; g.add(grip);
  const pom = sh(new THREE.Mesh(new THREE.SphereGeometry(0.03, 8, 6), gold)); pom.position.y = -0.2; g.add(pom);
  g.steel = steel; return g;
}
export function makeRapier() { const g = new THREE.Group(), steel = std(0xd0d4dc, { metalness: 0.9, roughness: 0.2 }); const b = new THREE.CylinderGeometry(0.004, 0.011, 1.0, 6); b.translate(0, 0.53, 0); g.add(sh(new THREE.Mesh(b, steel)));
  const cup = sh(new THREE.Mesh(new THREE.SphereGeometry(0.055, 10, 6, 0, Math.PI * 2, 0, Math.PI / 2), std(0xb8943c, { metalness: 0.9, roughness: 0.35, side: THREE.DoubleSide }))); cup.rotation.x = Math.PI; cup.position.y = 0.05; g.add(cup);
  const grip = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.15, 6), std(0x20140e))); grip.position.y = -0.05; g.add(grip); return g; }
export function makeDagger() { const g = new THREE.Group(); const b = new THREE.ConeGeometry(0.022, 0.3, 4); b.scale(1, 1, 0.25); b.translate(0, 0.19, 0); g.add(sh(new THREE.Mesh(b, std(0xc0c4cc, { metalness: 0.9, roughness: 0.25 })))); const gr = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.013, 0.013, 0.1, 6), std(0x20140e))); gr.position.y = -0.02; g.add(gr); return g; }
export function makeStaff() { const g = new THREE.Group(); const s = new THREE.CylinderGeometry(0.016, 0.02, 1.85, 6); s.translate(0, 0.35, 0); g.add(sh(new THREE.Mesh(s, std(0x3a2a1c)))); const k = sh(new THREE.Mesh(new THREE.IcosahedronGeometry(0.05, 0), std(0x7090c0, { emissive: 0x4a78ff, emissiveIntensity: 0.6, roughness: 0.3 }))); k.position.y = 1.3; g.add(k); return g; }
export function makeAxe() { const g = new THREE.Group(); const s = new THREE.CylinderGeometry(0.018, 0.02, 1.25, 6); s.translate(0, 0.4, 0); g.add(sh(new THREE.Mesh(s, std(0x3a2a1c))));
  const sp = new THREE.Shape(); sp.moveTo(0, -0.07); sp.lineTo(0.2, -0.2); sp.quadraticCurveTo(0.3, 0, 0.2, 0.2); sp.lineTo(0, 0.07); sp.lineTo(0, -0.07);
  const bg = new THREE.ExtrudeGeometry(sp, { depth: 0.016, bevelEnabled: false }); bg.translate(0.012, 0.9, -0.008); g.add(sh(new THREE.Mesh(bg, std(0x8a8f96, { metalness: 0.85, roughness: 0.4 })))); return g; }

export const makeSkeleton = seed => makeFigure({ seed, kind: 'skeleton', body: 0x9a937f, sw: 0.19, rArm: 0.022, rLeg: 0.026, headR: 0.1 });
