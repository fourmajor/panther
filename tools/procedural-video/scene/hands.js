// Articulated hands: sculpted palm (thenar/hypothenar pads, knuckles), four fingers of three phalanges, a three-joint
// thumb, nails or claws, optional (fingerless) gloves, and a bone variant for skeletons. Posed from a named pose table.
// Local frame (right hand; the left is mirrored in x): wrist at the origin, fingers along -y, thumb toward +z,
// palm facing +x. `grip` is an anchor whose +y axis runs through the closed fist (blade/handle axis).
import * as THREE from 'three';
import { smin, smax, sph, ell, cone, surfaceNets, toGeometry } from './sdf.js';

const FING = [   // base z, base y, lengths, radius
  { z: 0.029, y: -0.094, L: [0.043, 0.026, 0.022], r: 0.0088 }, { z: 0.0095, y: -0.099, L: [0.047, 0.030, 0.023], r: 0.0092 },
  { z: -0.0105, y: -0.095, L: [0.043, 0.028, 0.022], r: 0.0086 }, { z: -0.029, y: -0.086, L: [0.034, 0.020, 0.019], r: 0.0076 }];
const TH = { p: [0.012, -0.026, 0.030], dir: [0.38, -0.55, 0.74], L: [0.040, 0.032, 0.027], r: 0.0108 };
const R4 = a => [a, a, a, a];
export const HAND_POSES = {
  relax: { f: [[0.18, 0.30, 0.2], [0.24, 0.36, 0.22], [0.30, 0.40, 0.25], [0.36, 0.44, 0.28]], sp: [0.06, 0, -0.05, -0.12], th: [0.3, 0.2, 0.2], out: 0 },
  fist: { f: R4([1.35, 1.6, 1.0]), sp: [0, 0, 0, 0], th: [1, 0.5, 0.7], out: -0.2 },
  grip: { f: [[1.15, 1.45, 0.85], [1.25, 1.5, 0.9], [1.3, 1.5, 0.9], [1.35, 1.5, 0.9]], sp: [0, 0, 0, 0], th: [0.95, 0.45, 0.6], out: -0.15 },
  rapier: { f: [[0.7, 1.2, 0.55], [1.2, 1.5, 0.9], [1.3, 1.5, 0.9], [1.35, 1.5, 0.9]], sp: [0.05, 0, 0, 0], th: [0.8, 0.3, 0.3], out: -0.05 },
  point: { f: [[0.02, 0.04, 0.02], [1.35, 1.6, 1.0], [1.4, 1.6, 1.0], [1.45, 1.6, 1.0]], sp: [0, 0, 0, 0], th: [1, 0.5, 0.7], out: -0.2 },
  open: { f: [[-0.08, 0.08, 0.05], [-0.1, 0.06, 0.04], [-0.08, 0.08, 0.05], [-0.04, 0.12, 0.08]], sp: [0.2, 0.04, -0.12, -0.3], th: [-0.2, 0, 0], out: 0.5 },
  plead: { f: [[0.12, 0.25, 0.15], [0.16, 0.3, 0.2], [0.2, 0.34, 0.2], [0.26, 0.4, 0.25]], sp: [0.14, 0.03, -0.08, -0.2], th: [0, 0.1, 0.1], out: 0.35 },
  claw: { f: [[0.22, 1.0, 0.75], [0.28, 1.05, 0.8], [0.28, 1.0, 0.8], [0.32, 0.95, 0.75]], sp: [0.28, 0.06, -0.16, -0.36], th: [0.1, 0.5, 0.7], out: 0.45 },
  rope: { f: R4([1.2, 1.35, 0.8]), sp: [0, 0, 0, 0], th: [0.95, 0.45, 0.6], out: -0.1 },
  hold: { f: R4([0.95, 1.2, 0.7]), sp: [0.03, 0, 0, -0.04], th: [0.8, 0.35, 0.5], out: 0.0 },
};
let palmGeo = null;
function palmGeometry() { if (palmGeo) return palmGeo;
  const f = (x, y, z) => { let d = ell(x, y + 0.050, z, 0.0128, 0.050, 0.0395);
    for (const F of FING) d = smin(d, sph(x + 0.002, y - F.y - 0.004, z - F.z, 0.0098), 0.008);
    d = smin(d, ell(x - 0.007, y + 0.036, z - 0.027, 0.013, 0.028, 0.0155), 0.012); d = smin(d, ell(x - 0.005, y + 0.046, z + 0.028, 0.0105, 0.03, 0.0115), 0.01);
    d = smin(d, ell(x, y - 0.004, z, 0.0195, 0.03, 0.0285), 0.018); d = smax(d, -ell(x - 0.021, y + 0.052, z - 0.002, 0.010, 0.028, 0.02), 0.012); return d; };
  const m = surfaceNets(f, [-0.03, -0.115, -0.05], [0.035, 0.03, 0.055], 0.0024); return palmGeo = toGeometry(m); }
function segGeom(len, r, tip, bone) {
  const pts = bone ? [[0, 0.001], [r * 0.95, 0], [r * 1.0, -len * 0.08], [r * 0.5, -len * 0.3], [r * 0.46, -len * 0.7], [r * 0.82, -len * 0.92], [r * 0.7, -len * 0.99], [0, -len]]
    : tip ? [[0, 0.002], [r * 0.98, 0], [r * 0.93, -len * 0.45], [r * 0.9, -len * 0.75], [r * 0.7, -len * 0.93], [r * 0.35, -len * 1.02], [0, -len * 1.04]] : [[0, 0.002], [r, 0], [r * 0.9, -len * 0.5], [r * 0.95, -len], [0, -len - 0.001]];
  const g = new THREE.LatheGeometry(pts.map(p => new THREE.Vector2(p[0], p[1])).reverse(), 10); g.scale(0.9, 1, 1); return g;
}
// o: { side: 1 (right) | -1 (left), skin, nail (materials), size, claw (m), glove: {mat, fingerless}, bone: material }
export function makeHand(o = {}) {
  const side = o.side ?? 1, sz = o.size ?? 1, bone = o.bone || null, skin = bone || o.skin, group = new THREE.Group(), inner = new THREE.Group(); group.add(inner); inner.scale.set(side * sz, sz, sz * (o.thin ?? 1));
  const gl = o.glove, palmMat = bone || (gl ? gl.mat : skin), M = (g, m, cast = false) => { const x = new THREE.Mesh(g, m); x.castShadow = cast; x.receiveShadow = true; return x; };
  const nailM = o.nail || new THREE.MeshStandardMaterial({ color: 0xd9b8a8, roughness: 0.3 });
  if (bone) { for (const F of FING) { const mc = M(segGeom(0.062, 0.0062, false, true), bone, true); mc.position.set(0, F.y + 0.062, F.z * 0.75); mc.rotation.x = -F.z * 2.2; inner.add(mc); }
    for (let i = 0; i < 7; i++) { const c = M(new THREE.IcosahedronGeometry(0.0085, 1), bone); c.position.set((i % 2) * 0.004 - 0.002, -0.006 - Math.floor(i / 4) * 0.014, ((i % 4) - 1.5) * 0.012); c.scale.set(0.8, 0.9, 1); inner.add(c); } }
  else { const pm = M(palmGeometry(), palmMat, true); inner.add(pm); }
  const fingers = FING.map((F, i) => { const j = [], rr = bone ? F.r * 0.62 : F.r * (o.thinFinger ?? 1); let parent = inner;
    for (let k = 0; k < 3; k++) { const gI = new THREE.Group(); gI.position.set(0, k === 0 ? F.y : -F.L[k - 1], k === 0 ? F.z : 0); parent.add(gI); const r = rr * (1 - 0.1 * k);
      const mat = bone || (gl && !(gl.fingerless && k > 0) ? gl.mat : skin); gI.add(M(segGeom(F.L[k] * (k === 2 ? 1 + (o.longTip || 0) : 1), r, k === 2, !!bone), mat));
      if (!bone) { const kn = M(new THREE.SphereGeometry(r * 1.06, 8, 6), mat); kn.scale.set(0.95, 0.9, 1); gI.add(kn); }
      if (k === 2 && !bone && !(gl && !gl.fingerless)) { if (o.claw) { const c = new THREE.ConeGeometry(r * 0.62, o.claw, 6); c.translate(0, -o.claw / 2, 0); const cm = M(c, nailM); cm.position.set(-r * 0.25, -F.L[2] * 0.72, 0); cm.rotation.z = 0.28; gI.add(cm); }
        else { const ng = new THREE.SphereGeometry(1, 8, 6); ng.scale(r * 0.22, F.L[2] * 0.3, r * 0.78); const nm = M(ng, nailM); nm.position.set(-r * 0.72, -F.L[2] * 0.66, 0); gI.add(nm); } }
      j.push(gI); parent = gI; }
    return j; });
  const tb = new THREE.Group(); tb.position.set(...TH.p); inner.add(tb);
  const thumb = []; { let parent = tb; for (let k = 0; k < 3; k++) { const gI = new THREE.Group(); gI.position.y = k === 0 ? 0 : -TH.L[k - 1]; parent.add(gI); const r = (bone ? TH.r * 0.62 : TH.r) * (1 - 0.08 * k), mat = bone || (gl && !(gl.fingerless && k > 0) ? gl.mat : skin);
      gI.add(M(segGeom(TH.L[k], r * (k === 0 && !bone ? 1.15 : 1), k === 2, !!bone), mat)); if (!bone) gI.add(M(new THREE.SphereGeometry(r * 1.05, 8, 6), mat));
      if (k === 2 && !bone && !(gl && !gl.fingerless)) { if (o.claw) { const c = new THREE.ConeGeometry(r * 0.6, o.claw, 6); c.translate(0, -o.claw / 2, 0); const cm = M(c, nailM); cm.position.set(-r * 0.2, -TH.L[2] * 0.72, 0); cm.rotation.z = 0.25; gI.add(cm); }
        else { const ng = new THREE.SphereGeometry(1, 8, 6); ng.scale(r * 0.22, TH.L[2] * 0.3, r * 0.8); const nm = M(ng, nailM); nm.position.set(-r * 0.72, -TH.L[2] * 0.62, 0); gI.add(nm); } }
      thumb.push(gI); parent = gI; } }
  const grip = new THREE.Group(); grip.position.set(side * 0.029 * sz, -0.095 * sz, 0.0); grip.rotation.x = Math.PI / 2; group.add(grip);
  const H = { group, grip, fingers, thumb, side };
  const P = n => typeof n === 'string' ? HAND_POSES[n] : n;
  H.pose = (a, b = null, t = 0) => { const A = P(a), B = b ? P(b) : A, mx = (x, y) => x + (y - x) * t;
    fingers.forEach((j, i) => { j[0].rotation.set(mx(A.sp[i], B.sp[i]), 0, mx(A.f[i][0], B.f[i][0])); j[1].rotation.z = mx(A.f[i][1], B.f[i][1]); j[2].rotation.z = mx(A.f[i][2], B.f[i][2]); });
    // thumb: base swings from splayed (0) to opposed across the palm (1); the two outer joints flex toward the fingers
    const op = mx(A.th[0], B.th[0]), D = new THREE.Vector3(0.1 + 0.62 * op, -0.5 - 0.02 * op, 0.9 - 0.55 * op).normalize(), F = new THREE.Vector3(0.62, -0.25, -0.74), X = F.addScaledVector(D, -F.dot(D)).normalize(), Y = D.clone().multiplyScalar(-1), Z = new THREE.Vector3().crossVectors(X, Y);
    tb.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(X, Y, Z)); thumb[0].rotation.set(0, 0, 0); thumb[1].rotation.set(0, 0, mx(A.th[1], B.th[1])); thumb[2].rotation.set(0, 0, mx(A.th[2], B.th[2])); return H; };
  H.pose('relax'); return H;
}
