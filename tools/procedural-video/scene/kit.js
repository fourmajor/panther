// Set-building kit: batched static geometry, world-space UVs, arches, columns, vault ribs, battlements, particles.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { mulberry32 } from './util.js';

export const V = (x, y, z) => new THREE.Vector3(x, y, z);
export function worldUV(g, scale = 2) {
  const p = g.attributes.position, n = g.attributes.normal, uv = new Float32Array(p.count * 2);
  for (let i = 0; i < p.count; i++) {
    const ax = Math.abs(n.getX(i)), ay = Math.abs(n.getY(i)), az = Math.abs(n.getZ(i));
    let u, v; if (ay >= ax && ay >= az) { u = p.getX(i); v = p.getZ(i); } else if (ax >= az) { u = p.getZ(i); v = p.getY(i); } else { u = p.getX(i); v = p.getY(i); }
    uv[i * 2] = u / scale; uv[i * 2 + 1] = v / scale;
  }
  g.setAttribute('uv', new THREE.BufferAttribute(uv, 2)); return g;
}
export function scaleUV(g, su, sv) { const uv = g.attributes.uv; for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * su, uv.getY(i) * sv); return g; }
// Collects transformed geometry per material and emits one merged mesh per material.
export class Batch {
  constructor() { this.m = new Map(); }
  add(g, mat, { pos, rot, scale, wuv = 0, matrix } = {}) {
    g = g.index ? g.toNonIndexed() : g;
    const M = matrix || new THREE.Matrix4().compose(pos || V(0, 0, 0), new THREE.Quaternion().setFromEuler(rot || new THREE.Euler()), scale || V(1, 1, 1));
    g.applyMatrix4(M); if (wuv) worldUV(g, wuv);
    for (const k of Object.keys(g.attributes)) if (!['position', 'normal', 'uv'].includes(k)) g.deleteAttribute(k);
    if (!this.m.has(mat)) this.m.set(mat, []); this.m.get(mat).push(g); return this;
  }
  box(mat, w, h, d, x, y, z, ry = 0, wuv = 2) { return this.add(new THREE.BoxGeometry(w, h, d), mat, { pos: V(x, y, z), rot: new THREE.Euler(0, ry, 0), wuv }); }
  build(parent, { cast = true, receive = true } = {}) {
    for (const [mat, gs] of this.m) { const mesh = new THREE.Mesh(mergeGeometries(gs, false), mat); mesh.castShadow = cast; mesh.receiveShadow = receive; parent.add(mesh); }
    this.m.clear();
  }
}
// Wall slab (in XY, extruded +Z by thick) with a round-arched opening. Base at y=0, centred on x.
export function archWallGeom(w, h, thick, openW, spring, cx = 0, sill = 0) {
  const s = new THREE.Shape(); s.moveTo(-w / 2, 0); s.lineTo(w / 2, 0); s.lineTo(w / 2, h); s.lineTo(-w / 2, h); s.lineTo(-w / 2, 0);
  const r = openW / 2, hole = new THREE.Path(); hole.moveTo(cx - r, sill); hole.lineTo(cx - r, spring); hole.absarc(cx, spring, r, Math.PI, 0, true); hole.lineTo(cx + r, sill); hole.lineTo(cx - r, sill);
  s.holes.push(hole);
  return new THREE.ExtrudeGeometry(s, { depth: thick, bevelEnabled: false, curveSegments: 20 });
}
// Ring of voussoir blocks around an arch (in XY plane at z), with slight irregularity.
export function voussoirs(batch, mat, { cx = 0, spring, r, depth = 0.5, n = 13, z = 0, ry = 0, origin = V(0, 0, 0), seed = 1, thick = 0.34 }) {
  const rnd = mulberry32(seed), base = new THREE.Matrix4().makeRotationY(ry).setPosition(origin);
  for (let i = 0; i < n; i++) {
    const a = Math.PI * (i + 0.5) / n, key = i === (n - 1) / 2, t = thick * (key ? 1.35 : 1) * (0.92 + rnd() * 0.16), rr = r + t / 2;
    const g = new THREE.BoxGeometry(Math.PI * (r + t) / n * 0.93, t, depth * (key ? 1.15 : 1) * (0.94 + rnd() * 0.1));
    const M = new THREE.Matrix4().makeRotationZ(a - Math.PI / 2).setPosition(cx + Math.cos(a) * rr, spring + Math.sin(a) * rr, z);
    batch.add(g, mat, { matrix: base.clone().multiply(M), wuv: 1.3 });
  }
  // imposts
  for (const sx of [-1, 1]) batch.add(new THREE.BoxGeometry(thick * 1.25, 0.16, depth * 1.12), mat, { matrix: base.clone().multiply(new THREE.Matrix4().setPosition(cx + sx * (r + thick * 0.45), spring - 0.08, z)), wuv: 1.3 });
}
export function columnGeom(h, r) {
  const p = [[r * 1.55, 0], [r * 1.55, 0.14], [r * 1.3, 0.16], [r * 1.38, 0.24], [r * 1.12, 0.32], [r, 0.38], [r * 1.02, h * 0.45], [r * 0.93, h - 0.42], [r * 1.08, h - 0.38], [r * 0.98, h - 0.32], [r * 1.5, h - 0.1], [r * 1.6, h - 0.08], [r * 1.6, h], [0, h]];
  const g = new THREE.LatheGeometry(p.map(q => new THREE.Vector2(q[0], q[1])), 20); scaleUV(g, 3, h / 2); return g;
}
export function ribGeom(fn, r = 0.2, seg = 40) {
  class C extends THREE.Curve { getPoint(t, o = new THREE.Vector3()) { return fn(t, o); } }
  const g = new THREE.TubeGeometry(new C(), seg, r, 6, false); scaleUV(g, 8, 1); return g;
}
// Crenellations along a segment
export function battlements(batch, mat, x0, z0, x1, z1, y, { mw = 0.9, mh = 1.0, gap = 0.75, thick = 0.5, seed = 3 } = {}) {
  const len = Math.hypot(x1 - x0, z1 - z0), n = Math.max(1, Math.floor((len + gap) / (mw + gap))), ry = -Math.atan2(z1 - z0, x1 - x0), rnd = mulberry32(seed);
  const step = len / n;
  for (let i = 0; i < n; i++) {
    const f = (i + 0.5) * step / len, broken = rnd() < 0.08, hh = broken ? mh * 0.45 : mh * (0.95 + rnd() * 0.1);
    batch.box(mat, step - gap, hh, thick, x0 + (x1 - x0) * f, y + hh / 2, z0 + (z1 - z0) * f, ry);
  }
  batch.box(mat, len, 0.35, thick, (x0 + x1) / 2, y - 0.17, (z0 + z1) / 2, ry);
}
export function mesh(g, mat, cast = true, receive = true) { const m = new THREE.Mesh(g, mat); m.castShadow = cast; m.receiveShadow = receive; return m; }

// Stateless GPU particles: every particle's position is a pure function of (seed, uTime).
const PVERT = `
attribute vec4 aSeed; uniform float uTime,uT0,uLife,uSize,uGrow,uGravity,uSpeed,uSwirl,uConverge,uBurst,uPx; uniform vec3 uOrigin,uSpread,uVel;
varying float vA; varying float vPh;
void main(){
  float life=uLife*(0.55+0.9*aSeed.w);
  float age=uBurst>0.5?(uTime-uT0):mod(uTime+aSeed.z*life*7.31+aSeed.x*3.7,life);
  float ph=age/life; vPh=ph;
  vec3 dir=normalize(aSeed.xyz*2.-1.+1e-4);
  vec3 p=uOrigin+(aSeed.xyz*2.-1.)*uSpread+(uVel+dir*uSpeed*(0.4+aSeed.w))*age+vec3(0.,-.5*uGravity*age*age,0.);
  p.xz+=uSwirl*vec2(sin(age*1.7+aSeed.x*40.),cos(age*1.3+aSeed.y*40.))*min(ph*2.,1.);
  if(uConverge>0.) p=uOrigin+dir*mix(uConverge,0.25,ph*ph)+vec3(0.,sin(ph*6.+aSeed.x*9.)*.2,0.);
  vA=(ph<0.||ph>1.)?0.:(uBurst>0.5?(1.-ph)*(1.-ph):sin(ph*3.14159));
  vec4 mv=modelViewMatrix*vec4(p,1.); gl_Position=projectionMatrix*mv;
  gl_PointSize=min(uSize*(0.5+aSeed.y)*(1.+uGrow*ph)*uPx/max(-mv.z,0.05),300.);
}`;
const PFRAG = `
uniform vec3 uColA,uColB; uniform float uOpacity,uSoft; varying float vA; varying float vPh;
void main(){ float r=length(gl_PointCoord-.5)*2.; float a=pow(clamp(1.-r,0.,1.),uSoft)*vA*uOpacity; if(a<0.001) discard;
  gl_FragColor=vec4(mix(uColA,uColB,clamp(vPh,0.,1.))*a,a); }`;
export function particles(n, seed, o = {}) {
  const r = mulberry32(seed), s = new Float32Array(n * 4); for (let i = 0; i < s.length; i++) s[i] = r();
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(n * 3), 3)); g.setAttribute('aSeed', new THREE.BufferAttribute(s, 4));
  const u = { uTime: { value: 0 }, uT0: { value: -99 }, uLife: { value: o.life ?? 3 }, uSize: { value: o.size ?? 0.05 }, uGrow: { value: o.grow ?? 0 }, uGravity: { value: o.gravity ?? 0 }, uSpeed: { value: o.speed ?? 0 }, uSwirl: { value: o.swirl ?? 0 }, uConverge: { value: o.converge ?? 0 }, uBurst: { value: o.burst ? 1 : 0 }, uPx: { value: 1080 * 1.2 },
    uOrigin: { value: o.origin || V(0, 0, 0) }, uSpread: { value: o.spread || V(0, 0, 0) }, uVel: { value: o.vel || V(0, 0, 0) }, uColA: { value: new THREE.Color().fromArray(o.colA || [1, 0.5, 0.1]) }, uColB: { value: new THREE.Color().fromArray(o.colB || o.colA || [1, 0.2, 0]) }, uOpacity: { value: o.opacity ?? 1 }, uSoft: { value: o.soft ?? 1.5 } };
  const m = new THREE.ShaderMaterial({ vertexShader: PVERT, fragmentShader: PFRAG, uniforms: u, transparent: true, depthWrite: false, blending: o.additive === false ? THREE.CustomBlending : THREE.AdditiveBlending });
  if (o.additive === false) { m.blendSrc = THREE.OneFactor; m.blendDst = THREE.OneMinusSrcAlphaFactor; m.blendEquation = THREE.AddEquation; }
  const pts = new THREE.Points(g, m); pts.frustumCulled = false; pts.u = u; return pts;
}
