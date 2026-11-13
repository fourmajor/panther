// Anatomical skeleton: sculpted skull (cranium, orbits, nasal cavity, zygomatic arches, maxilla) with individual
// teeth and a separately hinged mandible; cervical / thoracic / lumbar vertebrae; ribcage of individual curved ribs
// with costal cartilage and sternum; clavicles, scapulae; sculpted pelvis with sacrum; humerus, radius + ulna, femur,
// patella, tibia + fibula; hand and foot bones. Aged bone material, rusted armour scraps, glowing eye points.
// Returns the same articulated interface as scene/figures.js figures (root, pelvis, spine, chest, neck, head, arms, legs, pose).
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { smin, smax, sph, ell, cone, surfaceNets, toGeometry } from './sdf.js';
import { mulberry32, clamp, lerp, sstep, fbm1, noise1 } from './util.js';
import { fabric } from './materials.js';
import { makeHand } from './hands.js';
import { bake } from './figures.js';

const V = (x, y, z) => new THREE.Vector3(x, y, z);
const sh = (m, cast = true) => { m.castShadow = cast; m.receiveShadow = true; return m; };
const lathe = (pts, seg = 10) => new THREE.LatheGeometry(pts.map(p => new THREE.Vector2(Math.max(p[0], 0), p[1])), seg);
const cache = {};
// bake ambient occlusion from the field into vertex colours (dirt gathers in crevices)
function aoColors(m, f, r = 0.012) { const P = m.position, N = m.normal, n = P.length / 3, c = new Float32Array(n * 3); for (let i = 0; i < n; i++) { const x = P[i * 3], y = P[i * 3 + 1], z = P[i * 3 + 2], a = clamp(f(x + N[i * 3] * r, y + N[i * 3 + 1] * r, z + N[i * 3 + 2] * r) / r), b = clamp(f(x + N[i * 3] * r * 0.3, y + N[i * 3 + 1] * r * 0.3, z + N[i * 3 + 2] * r * 0.3) / (r * 0.3)), k = 0.16 + 0.84 * a * (0.5 + 0.5 * b); c[i * 3] = k; c[i * 3 + 1] = k * (0.9 + 0.1 * a); c[i * 3 + 2] = k * (0.8 + 0.2 * a); } m.color = c; return m; }
const white = g => { const n = g.attributes.position.count, c = new Float32Array(n * 3); const p = g.attributes.position; g.computeBoundingBox(); const b = g.boundingBox, hgt = b.max.y - b.min.y || 1; for (let i = 0; i < n; i++) { const t = (p.getY(i) - b.min.y) / hgt, k = 0.78 + 0.22 * Math.sin(Math.PI * t); c[i * 3] = k; c[i * 3 + 1] = k * 0.97; c[i * 3 + 2] = k * 0.92; } g.setAttribute('color', new THREE.BufferAttribute(c, 3)); return g; };
const clean = g => { g = g.index ? g.toNonIndexed() : g; for (const k of Object.keys(g.attributes)) if (!['position', 'normal', 'color'].includes(k)) g.deleteAttribute(k); return g; };
const merge = gs => mergeGeometries(gs.map(g => clean(g.attributes.color ? g : white(g))), false);
const xf = (g, pos, rot, scl) => { const M = new THREE.Matrix4().compose(pos || V(0, 0, 0), new THREE.Quaternion().setFromEuler(rot || new THREE.Euler()), scl || V(1, 1, 1)); g.applyMatrix4(M); return g; };

function skullGeo() { if (cache.skull) return cache.skull;
  const f = (x, y, z) => { const ax = Math.abs(x);
    let d = ell(x, y - 0.040, z + 0.016, 0.0715, 0.073, 0.092); if (d > 0.07) return d;
    d = smin(d, ell(x, y + 0.014, z - 0.046, 0.058, 0.05, 0.048), 0.022);
    d = smin(d, cone(ax, y, z, 0.006, 0.029, 0.083, 0.047, 0.031, 0.062, 0.0085, 0.0075), 0.012);
    d = smin(d, ell(ax - 0.056, y + 0.015, z - 0.050, 0.014, 0.0115, 0.017), 0.012);
    d = smin(d, cone(ax, y, z, 0.059, -0.014, 0.040, 0.0685, -0.008, -0.012, 0.0048, 0.0052), 0.006);
    d = smin(d, ell(x, y + 0.046, z - 0.060, 0.031, 0.021, 0.027), 0.012);
    d = smin(d, sph(ax - 0.066, y + 0.03, z + 0.012, 0.012), 0.012);                                   // mastoid
    d = smax(d, -ell(ax - 0.0335, y - 0.007, z - 0.082, 0.0205, 0.0185, 0.032), 0.005);                 // orbits
    d = smax(d, -ell(x, y + 0.020, z - 0.092, 0.0105, 0.0165, 0.03), 0.004); d = smax(d, -ell(ax - 0.0065, y + 0.0315, z - 0.092, 0.0078, 0.0085, 0.03), 0.003);   // piriform aperture
    d = smax(d, -ell(ax - 0.079, y + 0.002, z - 0.022, 0.016, 0.03, 0.034), 0.02);                      // temporal fossa
    d = smax(d, -ell(ax - 0.045, y + 0.038, z - 0.072, 0.012, 0.012, 0.016), 0.012);                    // canine fossa
    d = smax(d, -Math.max(y + 0.043, z - 0.032), 0.012);                                                // skull base
    d = smax(d, -Math.max(y + 0.066, -100), 0.004);
    d = smax(d, -ell(x, y + 0.064, z - 0.052, 0.022, 0.012, 0.024), 0.004);                             // palate vault
    return d; };
  const m = surfaceNets(f, [-0.085, -0.075, -0.115], [0.085, 0.13, 0.105], 0.0024); aoColors(m, f); return cache.skull = toGeometry(m); }
function jawGeo() { if (cache.jaw) return cache.jaw;
  const f = (x, y, z) => { const ax = Math.abs(x);
    let d = cone(ax, y, z, 0, -0.100, 0.066, 0.045, -0.090, 0.004, 0.0105, 0.0085); d = smin(d, cone(ax, y, z, 0, -0.084, 0.064, 0.044, -0.078, 0.006, 0.0072, 0.006), 0.012);
    d = smin(d, cone(ax, y, z, 0.046, -0.092, 0.002, 0.053, -0.026, -0.010, 0.0092, 0.0065), 0.01); d = smin(d, sph(ax - 0.053, y + 0.02, z + 0.011, 0.0082), 0.006);
    d = smin(d, cone(ax, y, z, 0.049, -0.062, 0.010, 0.051, -0.034, 0.02, 0.006, 0.0035), 0.008); d = smin(d, ell(x, y + 0.107, z - 0.070, 0.014, 0.009, 0.01), 0.012);
    return d; };
  const m = surfaceNets(f, [-0.07, -0.125, -0.03], [0.07, -0.005, 0.09], 0.0024); aoColors(m, f, 0.008); return cache.jaw = toGeometry(m); }
function pelvisGeo() { if (cache.pelvis) return cache.pelvis;
  const c1 = Math.cos(0.6), s1 = Math.sin(0.6);
  const f = (x, y, z) => { const ax = Math.abs(x), px = ax - 0.082, pz = z + 0.012, rx = px * c1 + pz * s1, rz = -px * s1 + pz * c1;
    let d = ell(rx, y - 0.045, rz, 0.012, 0.072, 0.062); d = smax(d, -sph(rx - 0.045, y - 0.05, rz - 0.01, 0.05), 0.02);
    d = smin(d, cone(x, y, z, 0, 0.065, -0.062, 0, -0.045, -0.078, 0.034, 0.011), 0.02);
    d = smin(d, cone(ax, y, z, 0.012, -0.072, 0.048, 0.082, -0.028, 0.018, 0.011, 0.013), 0.012);
    d = smin(d, cone(ax, y, z, 0.078, -0.03, 0.006, 0.058, -0.104, -0.012, 0.014, 0.012), 0.012); d = smin(d, cone(ax, y, z, 0.058, -0.104, -0.012, 0.016, -0.084, 0.04, 0.0095, 0.009), 0.008);
    d = smax(d, -sph(ax - 0.103, y + 0.036, z - 0.004, 0.021), 0.006);
    for (let i = 0; i < 4; i++) d = smax(d, -sph(ax - 0.014, y - 0.045 + i * 0.024, z + 0.036, 0.0045), 0.003);
    return d; };
  const m = surfaceNets(f, [-0.16, -0.125, -0.12], [0.16, 0.125, 0.075], 0.0034); aoColors(m, f, 0.016); return cache.pelvis = toGeometry(m); }
function vertebra(r, h, sp, tr) { const gs = [];
  const body = new THREE.CylinderGeometry(r, r * 1.04, h, 10); body.scale(1, 1, 0.82); gs.push(body);
  for (const y of [-h / 2, h / 2]) { const lip = new THREE.TorusGeometry(r * 0.98, r * 0.14, 4, 10); lip.rotateX(Math.PI / 2); lip.scale(1, 1, 0.82); lip.translate(0, y * 0.9, 0); gs.push(lip); }
  const arch = new THREE.TorusGeometry(r * 0.72, r * 0.22, 5, 10, Math.PI); arch.rotateX(Math.PI / 2); arch.rotateY(Math.PI); arch.translate(0, 0, -r * 0.8); gs.push(arch);
  const spn = new THREE.ConeGeometry(r * 0.3, sp, 5); spn.rotateX(-Math.PI / 2 - 0.5); spn.translate(0, -sp * 0.24, -r * 1.45 - sp * 0.42); gs.push(spn);
  for (const s of [-1, 1]) { const t = new THREE.ConeGeometry(r * 0.26, tr, 5); t.rotateZ(-s * Math.PI / 2); t.translate(s * (r * 0.9 + tr / 2), 0, -r * 0.75); gs.push(t); }
  return merge(gs); }
function tube(pts, r, seg = 18, rad = 6) { return new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), seg, r, rad, false); }
function longBone(L, r, e0, e1) { return lathe([[0, e0 * 0.9], [e0 * 0.8, e0 * 0.55], [e0, 0], [e0 * 0.8, -L * 0.06], [r * 1.12, -L * 0.16], [r, -L * 0.4], [r * 1.02, -L * 0.74], [e1 * 0.75, -L * 0.9], [e1, -L * 0.965], [e1 * 0.9, -L], [0, -L - e1 * 0.45]], 9); }

/* o: { seed, scale, eye: [r,g,b] glow colour, armor: ['plate','pauldronL','helm','tassets','mail'], boneColor } */
export function makeSkeleton(o = {}) {
  if (typeof o === 'number') o = { seed: o };
  const seed = o.seed || 1, rnd = mulberry32(seed * 613 + 11), torso = 0.47, sw = 0.17, hw = 0.085, L1 = 0.3, L2 = 0.25, T1 = 0.43, T2 = 0.4, hip = T1 + T2 + 0.06;
  const boneM = fabric('bone', o.boneColor ?? 0xb7a985, { vertexColors: true }), rust = fabric('rust', 0x5c5f63, { rough: 0.55, metal: 0.8, side: THREE.DoubleSide }), rag = fabric('cloth', 0x1c1612, { side: THREE.DoubleSide });
  const root = new THREE.Group(), pelvis = new THREE.Group(); pelvis.position.y = hip; root.add(pelvis); const spine = new THREE.Group(); pelvis.add(spine);
  const f = { root, pelvis, spine, hip, torso, seed, sw, o, extras: {}, t: 0 };
  const B = (g, parent, pos, rot) => { const m = sh(new THREE.Mesh(g.attributes.color ? g : white(g), boneM)); if (pos) m.position.copy(pos); if (rot) m.rotation.copy(rot); parent.add(m); return m; };
  // pelvis + sacrum, lumbar spine
  B(pelvisGeo(), pelvis, V(0, 0.0, 0));
  const lum = []; for (let i = 0; i < 5; i++) { const t = i / 5, g = vertebra(0.021 - 0.002 * t, 0.027, 0.03, 0.03); xf(g, V(0, 0.085 + i * 0.036, -0.035 + 0.022 * Math.sin(Math.PI * t * 0.9)), new THREE.Euler(-0.12 + 0.3 * t, 0, 0)); lum.push(g); } B(merge(lum), spine);
  const chest = new THREE.Group(); chest.position.y = torso; spine.add(chest); f.chest = chest;
  // thoracic spine, ribs, sternum (chest space: y = 0 at the shoulder line)
  const thor = [], ty = i => -0.012 - (11 - i) * 0.0258 + 0.0, tz = i => -0.058 - 0.022 * Math.sin(Math.PI * (i + 0.5) / 12); // i = 0 (T12, lowest) .. 11 (T1)
  for (let i = 0; i < 12; i++) { const g = vertebra(0.0185 - 0.0005 * i, 0.02, 0.034, 0.022); xf(g, V(0, ty(i), tz(i)), new THREE.Euler(0.25 * Math.cos(Math.PI * (i + 0.5) / 12), 0, 0)); thor.push(g); }
  B(merge(thor), chest);
  const ribs = [], cart = [];
  for (let k = 0; k < 12; k++) { const i = 11 - k, y0 = ty(i), u = k / 11, rx = lerp(0.062, 0.128, Math.sin(Math.PI * Math.min(1, u * 1.25) * 0.5)) * (k > 9 ? 0.92 : 1), rz = lerp(0.062, 0.098, Math.sin(Math.PI * Math.min(1, u * 1.3) * 0.5)), drop = lerp(0.03, 0.085, u), cz = 0.0, endA = k < 7 ? 0.30 : k < 10 ? 0.55 + (k - 7) * 0.22 : 1.55 + (k - 10) * 0.35, rr = k === 0 ? 0.0052 : 0.0058;
    for (const s of [-1, 1]) { const pts = []; const n = 11; for (let j = 0; j <= n; j++) { const a = lerp(Math.PI - 0.22, endA, j / n), w = (Math.PI - a) / Math.PI; pts.push(V(s * rx * Math.sin(a) * (1 + 0.06 * Math.sin(a * 2)), y0 - drop * Math.pow(w, 1.25), cz - 0.01 + rz * Math.cos(a) * (a > Math.PI / 2 ? 0.86 : 1))); }
      const g = tube(pts, rr, 22, 6), q = g.attributes.position; g.scale(1, 1.0, 1); ribs.push(g);
      if (k < 10) { const e = pts[n], sy = -0.045 - Math.min(k, 6) * 0.021 - (k > 6 ? 0.0 : 0), tgt = V(s * 0.016, sy + (k > 6 ? -0.012 * (k - 6) : 0), cz - 0.012 + lerp(0.064, 0.096, Math.min(1, u * 1.6))), mid = e.clone().lerp(tgt, 0.5).add(V(0, k > 6 ? -0.012 : -0.008, 0.008)); cart.push(tube([e, mid, tgt], 0.0042, 8, 5)); } } }
  B(merge(ribs), chest); const cartM = sh(new THREE.Mesh(white(merge(cart)), fabric('bone', 0x7a6c52, { vertexColors: true }))); chest.add(cartM);
  const st = [xf(new THREE.BoxGeometry(0.05, 0.048, 0.011), V(0, -0.058, 0.064), new THREE.Euler(-0.25, 0, 0)), xf(new THREE.BoxGeometry(0.033, 0.1, 0.01), V(0, -0.132, 0.084), new THREE.Euler(-0.22, 0, 0)), xf(new THREE.ConeGeometry(0.011, 0.035, 4), V(0, -0.198, 0.094), new THREE.Euler(Math.PI - 0.2, 0, 0))]; B(merge(st), chest);
  // shoulder girdle
  for (const s of [-1, 1]) { B(tube([V(s * 0.02, -0.036, 0.06), V(s * 0.07, -0.028, 0.055), V(s * 0.12, -0.02, 0.012), V(s * (sw - 0.005), -0.012, -0.012)], 0.0068, 14, 6), chest);
    const sp = new THREE.Shape(); sp.moveTo(0, 0); sp.lineTo(0.085, -0.012); sp.lineTo(0.02, -0.15); sp.lineTo(-0.012, -0.06); sp.lineTo(0, 0);
    const sg = new THREE.ExtrudeGeometry(sp, { depth: 0.005, bevelEnabled: true, bevelSize: 0.004, bevelThickness: 0.003, bevelSegments: 1 }); if (s < 0) sg.scale(-1, 1, 1);
    const sc = B(sg, chest, V(s * 0.062, -0.022, -0.092), new THREE.Euler(0.12, s * 0.35, 0)); if (s < 0) sc.material = boneM;
    B(xf(new THREE.CapsuleGeometry(0.006, 0.07, 3, 6), V(0, 0, 0), new THREE.Euler(0, 0, Math.PI / 2)), chest, V(s * 0.108, -0.045, -0.094), new THREE.Euler(0.1, s * 0.3, s * 0.22));
    B(new THREE.SphereGeometry(0.016, 8, 6), chest, V(s * (sw - 0.012), -0.022, -0.03)); }
  // neck, skull, jaw
  const neck = new THREE.Group(); neck.position.y = 0.012; chest.add(neck); f.neck = neck;
  const cerv = []; for (let i = 0; i < 7; i++) { const g = vertebra(0.0125 - 0.0004 * i, 0.0125, 0.02, 0.014); xf(g, V(0, 0.006 + i * 0.0172, -0.05 + 0.02 * Math.sin(Math.PI * i / 7)), new THREE.Euler(-0.2 + 0.05 * i, 0, 0)); cerv.push(g); } B(merge(cerv), neck);
  const head = new THREE.Group(); head.position.y = 0.168; neck.add(head); f.head = head;
  B(skullGeo(), head);
  const toothM = fabric('bone', 0xc9b98c, { vertexColors: true }), teeth = up => { const gs = []; for (let i = 0; i < 14; i++) { if (rnd() < (o.missing ?? 0.14)) continue; const a = (i + 0.5 - 7) / 7 * 1.32, front = Math.abs(i + 0.5 - 7) < 3, w = front ? 0.0068 : 0.0082, ht = (front ? 0.0115 : 0.0085) * (0.85 + 0.3 * rnd()), g = new THREE.CylinderGeometry(w * 0.5, w * 0.36, ht, 5); g.scale(1, 1, front ? 0.6 : 0.95);
      xf(g, V(Math.sin(a) * 0.0275 * (up ? 1 : 0.94), up ? -0.066 - ht / 2 + 0.002 : -0.079 + ht / 2, 0.052 + Math.cos(a) * 0.032 * (up ? 1 : 0.95)), new THREE.Euler((rnd() - 0.5) * 0.25, a, up ? 0 : Math.PI)); gs.push(g); } return merge(gs); };
  head.add(sh(new THREE.Mesh(teeth(true), toothM)));
  const jaw = new THREE.Group(); jaw.position.set(0, -0.02, -0.011); head.add(jaw); f.jaw = jaw;
  const jm = B(jawGeo(), jaw, V(0, 0.02, 0.011)); const lt = sh(new THREE.Mesh(teeth(false), toothM)); lt.position.set(0, 0.02, 0.011); jaw.add(lt);
  const ec = o.eye ?? [0.55, 1.0, 0.85], eyeMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(ec[0] * 5, ec[1] * 5, ec[2] * 5) }), haloM = new THREE.MeshBasicMaterial({ color: new THREE.Color(ec[0] * 0.5, ec[1] * 0.5, ec[2] * 0.5), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false });
  f.extras.eyeMat = eyeMat; f.extras.haloMat = haloM; f.eyeColor = ec;
  for (const s of [-1, 1]) { const e = new THREE.Mesh(new THREE.SphereGeometry(0.0034, 10, 8), eyeMat); e.position.set(s * 0.033, -0.007, 0.06); head.add(e); const hl = new THREE.Mesh(new THREE.SphereGeometry(0.0085, 10, 8), haloM); hl.position.copy(e.position); head.add(hl); }
  // arms
  const arm = s => { const a = new THREE.Group(); a.position.set(s * sw, -0.03, -0.02); chest.add(a);
    const hum = longBone(L1, 0.0105, 0.019, 0.02); B(hum, a); B(new THREE.SphereGeometry(0.02, 10, 8), a, V(-s * 0.012, 0.004, 0));
    const b = new THREE.Group(); b.position.y = -L1; a.add(b);
    B(xf(longBone(L2 - 0.01, 0.0062, 0.0105, 0.012), V(s * 0.012, 0, 0.004), new THREE.Euler(0, 0, -s * 0.045)), b); B(xf(longBone(L2 + 0.012, 0.0058, 0.013, 0.008), V(-s * 0.012, 0.022, -0.006), new THREE.Euler(0, 0, s * 0.04)), b);
    const e = new THREE.Group(); e.position.y = -L2; b.add(e); const hand = makeHand({ side: -s, bone: boneM, size: 1.04 }); hand.group.traverse(x => { if (x.isMesh && !x.geometry.attributes.color) white(x.geometry); }); e.add(hand.group);
    return { a, b, e, L1, L2, parent: chest, hand }; };
  f.armL = arm(1); f.armR = arm(-1); f.handL = f.armL.hand; f.handR = f.armR.hand;
  // legs
  const leg = s => { const a = new THREE.Group(); a.position.set(s * 0.1, -0.038, -0.002); pelvis.add(a);
    B(new THREE.SphereGeometry(0.021, 10, 8), a, V(0, 0, 0)); B(xf(lathe([[0.012, 0], [0.011, -0.05], [0.014, -0.058]], 7), V(0, 0, 0), new THREE.Euler(0, 0, s * 1.05)), a); B(new THREE.SphereGeometry(0.017, 8, 6), a, V(s * 0.05, -0.03, -0.004));
    B(xf(longBone(T1 - 0.03, 0.0135, 0.017, 0.0255), V(s * 0.045, -0.028, 0), new THREE.Euler(0, 0, s * 0.1)), a); for (const c of [-1, 1]) B(new THREE.SphereGeometry(0.019, 8, 6), a, V(c * 0.017 + s * 0.004, -T1 + 0.004, -0.004));
    const b = new THREE.Group(); b.position.y = -T1; a.add(b); B(xf(new THREE.SphereGeometry(0.019, 8, 6), V(0, 0, 0), null, V(1, 1.15, 0.55)), b, V(s * 0.003, 0.012, 0.03));
    B(xf(longBone(T2 - 0.012, 0.0115, 0.026, 0.017), V(0, -0.012, 0), null, V(1, 1, 0.85)), b); B(xf(longBone(T2 - 0.03, 0.0048, 0.0085, 0.0095), V(s * 0.026, -0.03, -0.012)), b);
    const e = new THREE.Group(); e.position.y = -T2; b.add(e);
    const ft = []; ft.push(xf(new THREE.SphereGeometry(0.024, 8, 6), V(0, -0.028, -0.03), null, V(0.85, 0.8, 1.5)), xf(new THREE.SphereGeometry(0.02, 8, 6), V(0, -0.012, 0.004), null, V(1, 0.75, 1.2)));
    for (let i = 0; i < 4; i++) ft.push(xf(new THREE.IcosahedronGeometry(0.0115, 1), V((i - 1.5) * 0.015 * s, -0.026, 0.036), null, V(1, 0.8, 1.1)));
    for (let i = 0; i < 5; i++) { const x = (i - 2) * 0.0155 * s + s * 0.003, big = (s > 0 ? i === 0 : i === 4), mlen = 0.062 - Math.abs(i - 1.5) * 0.004; ft.push(xf(longBone(mlen, 0.004, 0.0068, 0.0068), V(x, -0.03, 0.048), new THREE.Euler(-Math.PI / 2 - 0.22, 0, 0)));
      let z = 0.048 + mlen * 0.975, y = -0.03 - mlen * 0.215; for (let k = 0; k < (big ? 2 : 3); k++) { const pl = (big ? 0.026 : 0.017) * (1 - 0.25 * k); ft.push(xf(longBone(pl, 0.0032, 0.0056, 0.005), V(x * (1 + 0.012 * (k + 1)), y, z), new THREE.Euler(-Math.PI / 2 - 0.05, 0, 0))); z += pl + 0.003; y -= 0.002; } }
    B(merge(ft), e); return { a, b, e, L1: T1, L2: T2, parent: pelvis }; };
  f.legL = leg(1); f.legR = leg(-1);
  // rusted scraps of armour and rotted cloth
  const armor = o.armor ?? ['plate', 'pauldronL', 'rags'];
  const dent = (g, amp, sd) => { const p = g.attributes.position; for (let i = 0; i < p.count; i++) { const x = p.getX(i), y = p.getY(i), z = p.getZ(i), k = 1 + amp * (fbm1(x * 31 + y * 17 + sd, sd) + 0.6 * noise1(z * 53 + x * 29, sd + 3)); p.setXYZ(i, x * k, y * k, z * k); } g.computeVertexNormals(); return g; };
  if (armor.includes('plate')) { const g = dent(new THREE.SphereGeometry(0.15, 22, 14, -1.25 + Math.PI / 2 - 0.2, 2.3, 0.75, 1.25), 0.06, seed); g.scale(1, 1.22, 0.86); const p = sh(new THREE.Mesh(g, rust)); p.position.set(0.012, -0.15, -0.002); p.rotation.set(0.05, -Math.PI / 2 + 0.25, 0.05); chest.add(p);
    const st2 = sh(new THREE.Mesh(new THREE.TorusGeometry(0.135, 0.008, 4, 20, 2.6), rag)); st2.position.set(-0.01, -0.09, -0.01); st2.rotation.set(Math.PI / 2 - 0.5, 0.2, 2.2); chest.add(st2); }
  for (const [nm, s] of [['pauldronL', 1], ['pauldronR', -1]]) if (armor.includes(nm)) { const g = dent(new THREE.SphereGeometry(0.075, 14, 9, 0, Math.PI * 2, 0, Math.PI * 0.52), 0.07, seed + s); g.scale(1.15, 0.8, 1.2); const p = sh(new THREE.Mesh(g, rust)); p.position.set(s * (sw + 0.01), 0.012, -0.02); p.rotation.z = -s * 0.5; chest.add(p);
      const g2 = dent(new THREE.CylinderGeometry(0.07, 0.078, 0.07, 12, 1, true, s > 0 ? 0.2 : Math.PI + 0.2, Math.PI - 0.4), 0.05, seed + 5); const p2 = sh(new THREE.Mesh(g2, rust)); p2.position.set(s * (sw + 0.012), -0.06, -0.02); chest.add(p2); }
  if (armor.includes('helm')) { const g = dent(new THREE.SphereGeometry(0.086, 20, 12, 0, Math.PI * 2, 0, Math.PI * 0.55), 0.035, seed + 9); g.scale(0.95, 1.0, 1.15); const h = sh(new THREE.Mesh(g, rust)); h.position.set(0, 0.052, -0.014); h.rotation.set(-0.12, 0, 0.1); head.add(h);
    const ng = sh(new THREE.Mesh(new THREE.BoxGeometry(0.017, 0.075, 0.008), rust)); ng.position.set(0.002, 0.012, 0.089); ng.rotation.x = 0.1; head.add(ng); const br = sh(new THREE.Mesh(dent(new THREE.TorusGeometry(0.086, 0.007, 4, 22), 0.05, seed), rust)); br.rotation.x = Math.PI / 2 - 0.12; br.rotation.y = 0.1; br.scale.set(0.95, 1.15, 1); br.position.set(0, 0.042, -0.014); head.add(br); }
  if (armor.includes('mail')) { const g = new THREE.CylinderGeometry(0.12, 0.15, 0.2, 18, 3, true, 0.5, 3.4), p = g.attributes.position; for (let i = 0; i < p.count; i++) if (p.getY(i) < -0.05) p.setY(i, p.getY(i) + 0.08 * rnd() * rnd()); g.scale(1, 1, 0.85); g.computeVertexNormals(); const ml = sh(new THREE.Mesh(g, fabric('chain', 0x54463a, { side: THREE.DoubleSide, rough: 0.7, metal: 0.6 }))); ml.position.y = -0.25; chest.add(ml); }
  if (armor.includes('rags') || armor.includes('tassets')) { for (let i = 0; i < 6; i++) { const a = (i / 6) * Math.PI * 2 + rnd(), len = 0.2 + rnd() * 0.3, g = new THREE.PlaneGeometry(0.09 + rnd() * 0.06, len, 3, 5), p = g.attributes.position; for (let k = 0; k < p.count; k++) { const v = 0.5 - p.getY(k) / len; p.setZ(k, 0.02 * Math.sin(v * 7 + i) * v); if (v > 0.9) p.setY(k, p.getY(k) + rnd() * len * 0.3); p.setX(k, p.getX(k) * (1 - 0.3 * v * rnd())); } g.translate(0, -len / 2, 0); g.computeVertexNormals();
      const m = sh(new THREE.Mesh(g, armor.includes('tassets') && i % 3 === 0 ? rust : rag)); m.position.set(Math.sin(a) * 0.125, 0.02, Math.cos(a) * 0.1); m.rotation.y = a; m.rotation.x = 0.12; pelvis.add(m); }
    const belt = sh(new THREE.Mesh(new THREE.TorusGeometry(0.128, 0.012, 5, 22), rag)); belt.rotation.x = Math.PI / 2; belt.scale.y = 0.82; belt.position.y = 0.03; pelvis.add(belt); }
  bake(root);
  f.pose = (t, k = {}) => { const s = seed * 1.7; f.t = t;
    pelvis.position.set(0, hip + (k.crouch ? -k.crouch : 0), 0); pelvis.rotation.set(0, 0, 0);
    spine.rotation.set((k.lean ?? 0.1) + 0.02 * Math.sin(t * 1.1 + s), 0, 0.03 * Math.sin(t * 0.7 + s));
    chest.rotation.set(0, k.turn ?? 0, 0); neck.rotation.set((k.nod ?? 0) + 0.05 * fbm1(t * 0.9, seed), (k.look ?? 0) + 0.12 * fbm1(t * 0.7, seed + 5), 0.06 * fbm1(t * 0.5, seed + 9)); head.rotation.set(0, 0, 0);
    for (const [a, sg] of [[f.armL, 1], [f.armR, -1]]) { a.a.quaternion.identity(); a.a.rotation.set(0.06, 0, sg * (k.armOut ?? 0.14)); a.b.rotation.set(-0.3, 0, 0); a.e.quaternion.identity(); a.e.rotation.set(0, 0, 0); }
    for (const [l, sg] of [[f.legL, 1], [f.legR, -1]]) { l.a.quaternion.identity(); l.a.rotation.set(0, 0, sg * 0.03); l.b.rotation.set(0, 0, 0); l.e.rotation.set(0, 0, 0); }
    f.handL.pose(k.handL || 'claw'); f.handR.pose(k.handR || 'grip');
    // jaw chatter: bursts of fast clacking
    const burst = sstep(0.1, 0.5, fbm1(t * 0.8, seed + 21)) * (k.chatter ?? 1); jaw.rotation.x = 0.04 + burst * 0.22 * Math.abs(Math.sin(t * 31 + seed)) + (k.gape ?? 0);
    const fl = 0.75 + 0.25 * fbm1(t * 9, seed + 2) + (k.flare ?? 0); eyeMat.color.setRGB(ec[0] * 4.5 * fl, ec[1] * 4.5 * fl, ec[2] * 4.5 * fl); haloM.color.setRGB(ec[0] * 0.22 * fl, ec[1] * 0.22 * fl, ec[2] * 0.22 * fl); };
  if (o.scale) root.scale.setScalar(o.scale);
  return f;
}
