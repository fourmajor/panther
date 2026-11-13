// Procedural heads. A head is sculpted as a signed-distance field (cranium, brow ridge, sockets, cheekbones, nose with
// bridge/tip/alae/nostrils, philtrum, lips, mouth slit + cavity, jaw, chin, ears, neck), meshed with surface nets, and
// given: vertex-colour skin with a wrap/SSS light model, pore/wrinkle/freckle/stubble detail, morph targets (jaw,
// lip shapes, brows), eyeballs with iris/pupil textures and a wet clear-coat, blinking lids with lashes, brows of
// individual hairs, teeth and tongue. All shape and colour is driven by a plain spec object.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { smin, smax, sph, ell, cone, surfaceNets, toGeometry, project } from './sdf.js';
import { mulberry32, clamp, lerp, sstep, fbm1, hash1 } from './util.js';

export const HEAD_DEFAULTS = { W: 1, H: 1, jawW: 1, jawL: 1, chin: 1, chinW: 1, cheek: 1, brow: 1, forehead: 0, noseL: 1, noseW: 1, noseB: 1, noseHook: 0, noseTip: 0, lips: 1, mouthW: 1, mouthCurve: 0.3,
  eye: 1, eyeGap: 1, eyeTilt: 0.07, ear: 1, earOut: 1, neck: 1, gaunt: 0, age: 0, crook: 0, voxel: 0.0021,
  skin: 0xc79a78, lip: 0x9a5548, iris: 0x5a3d24, sclera: 0xcdc7bd, browColor: 0x1a1410, browThick: 1, browArch: 0.3, browTilt: 0, browLen: 1, lash: 0x100c0a, teeth: 0xd8d0b8,
  stubble: 0, stubbleColor: 0x15120f, freckles: 0, blush: 0.25, pores: 1, wrinkles: 0, sss: 1, rough: 0.52, glowEyes: 0, extra: null, seed: 1 };

const EYE_R = 0.0122;
// Builds the distance function for a spec. Returns f plus the landmarks and part distances that masks need.
export function headField(s) {
  const W = s.W, H = s.H, JW = s.jawW, JL = s.jawL, NL = s.noseL, NW = s.noseW, NB = s.noseB, MW = s.mouthW, L = s.lips, EG = s.eyeGap, ES = s.eye, age = s.age, ck = s.crook;
  const E = [0.0318 * EG * W, 0.011, 0.0665], hw = 0.0238 * MW, my = -0.0628 - 0.004 * (JL - 1), ehw = 0.0147 * ES, tipY = -0.031 * NL, tipZ = 0.1165 + 0.007 * (NB - 1) + 0.004 * (NL - 1);
  const P = { lip: 1, cut: 1, pit: 1, nos: 1, ear: 1, base: 1 };
  const slitY = ax => my - s.mouthCurve * 0.0045 * (ax / hw) * (ax / hw), slitT = ax => 0.0004 + 0.0018 * Math.sqrt(Math.max(0, 1 - Math.pow(ax / hw, 4)));
  const f = (x0, y, z) => {
    const x = x0 + ck * 0.9 * y * y * Math.sign(y) * 6 + ck * 0.012 * Math.sin(y * 30), ax = Math.abs(x);   // "crook": lateral bend of the whole head
    let d = ell(x, y - 0.040, z + 0.014, 0.0765 * W, 0.090 * H + 0.006 * s.forehead, 0.098);
    const nk = cone(x, y, z, 0, -0.07, -0.022, 0, -0.24, -0.042, 0.049 * s.neck, 0.057 * s.neck);
    if (d > 0.15 && nk > 0.06) { P.base = d; return Math.min(d, nk); }
    d = smin(d, ell(x, y + 0.024, z - 0.020, 0.0595 * W, 0.082, 0.078), 0.03);
    d = smin(d, ell(x, y + 0.078 * JL, z - 0.020, 0.0425 * JW * W, 0.040, 0.064), 0.028);
    d = smin(d, sph(ax - 0.0425 * JW * W, y + 0.070 * JL, z + 0.004, 0.0135), 0.025);
    if (s.gaunt < 0.3) d = smin(d, ell(ax - 0.038 * W, y + 0.047, z - 0.046, 0.019, 0.03, 0.024), 0.03);
    d = smin(d, ell(x, y + 0.103 * JL, z - 0.058 - 0.004 * (s.chin - 1), 0.021 * s.chinW, 0.0165, 0.018 * s.chin), 0.022);
    d = smin(d, ell(ax - 0.050 * W, y + 0.016, z - 0.050, 0.020 * (0.75 + 0.25 * s.cheek), 0.013, 0.020 * (0.75 + 0.25 * s.cheek)), 0.022);
    if (s.forehead) d = smin(d, ell(x, y - 0.065, z - 0.06, 0.05, 0.03, 0.03 * s.forehead), 0.03);
    d = smin(d, cone(ax, y, z, 0.008, 0.0305, 0.0885, 0.045 * W, 0.0345, 0.0700, 0.0072 * s.brow), 0.016);
    if (s.gaunt >= 0.3) d = smax(d, -ell(ax - 0.047 * W, y + 0.050, z - 0.058, 0.016 * s.gaunt, 0.026, 0.016 * s.gaunt), 0.03);
    d = smin(d, nk, 0.03); P.base = d;
    if (d > 0.05) return d; if (d < -0.045) return d;
    // orbit: hollow, then the lid bulge over the eyeball
    d = smax(d, -ell(ax - 0.0335 * EG * W, y - 0.0125, z - 0.090, 0.021, 0.0135 + 0.002 * age, 0.017), 0.012);
    d = smin(d, sph(ax - E[0], y - E[1], z - E[2], EYE_R + 0.0034), 0.0055);
    if (age) d = smin(d, ell(ax - E[0] - 0.001, y - E[1] + 0.0125, z - E[2] - 0.0125, 0.012, 0.0045, 0.005), 0.006 * age + 1e-4);     // bags under the eyes
    // nose: bridge, tip, alae, columella, nostrils
    d = smin(d, cone(x, y, z, 0, 0.022, 0.0905 + 0.003 * (NB - 1), 0, tipY + 0.004, tipZ - 0.0035, 0.0056 * NW, 0.0076 * NW), 0.011);
    if (s.noseHook) d = smin(d, sph(x, y - 0.002, z - 0.103 - 0.004 * s.noseHook, 0.0085), 0.012);
    d = smin(d, sph(x, y - tipY + 0.004 * s.noseHook - 0.003 * s.noseTip, z - tipZ, 0.0086 * NW), 0.006);
    d = smin(d, sph(ax - 0.0118 * NW, y - tipY + 0.0048, z - 0.1035, 0.0072 * NW), 0.006);
    d = smin(d, cone(x, y, z, 0, tipY - 0.006, tipZ - 0.004, 0, tipY - 0.011, 0.099, 0.0042, 0.005), 0.004);
    const nos = ell(ax - 0.0056 * NW, y - tipY + 0.0108, z - 0.1055, 0.0034 * NW, 0.003, 0.0062); P.nos = nos; d = smax(d, -nos, 0.0025);
    // muzzle, lips, philtrum, chin crease, nasolabial fold
    d = smin(d, ell(x, y - my - 0.002, z - 0.0855, 0.030 * MW, 0.021, 0.020), 0.018);
    const sy = slitY(ax), bow = 0.0016 * Math.max(0, 1 - Math.abs(ax - 0.0045) / 0.0045);
    const up = cone(ax, y, z, 0, my + 0.0074 + bow, 0.1068, hw * 0.92, sy + 0.0028, 0.0935, 0.0056 * L, 0.0026 * L);
    const lo = cone(ax, y, z, 0, my - 0.0074 * L, 0.1052, hw * 0.80, sy - 0.0030, 0.0940, 0.0070 * L, 0.0028 * L);
    P.lip = Math.min(up, lo); d = smin(d, up, 0.0045); d = smin(d, lo, 0.0045);
    d = smax(d, -cone(x, y, z, 0, tipY - 0.014, 0.1105, 0, my + 0.0105, 0.1125, 0.0026, 0.0032), 0.004);
    d = smax(d, -ell(x, y - my + 0.0175 * L, z - 0.1045, 0.015, 0.0045, 0.0075), 0.007);
    if (age) d = smax(d, -cone(ax, y, z, 0.0165 * NW, tipY + 0.002, 0.103, hw + 0.007, my - 0.004, 0.092, 0.0016, 0.0022), 0.008 * age + 1e-4);
    // ears: flattened shell with a hollowed concha, tragus and lobe
    { const ex = ax - 0.0745 * W - 0.002 * s.earOut, ey = y - 0.002, ez = z + 0.010, c1 = 0.92, s1 = 0.38 * s.earOut, rx = ex * c1 + ez * s1, rz = -ex * s1 + ez * c1, cy = 0.985, sY = 0.17, ry = ey * cy + rz * sY, rz2 = -ey * sY + rz * cy, q = s.ear;
      let e = ell(rx, ry, rz2, 0.0058, 0.0305 * q, 0.0165 * q); e = smax(e, -ell(rx - 0.0055, ry - 0.003 * q, rz2 - 0.0015, 0.0052, 0.0195 * q, 0.0092 * q), 0.004);
      e = smin(e, sph(rx - 0.001, ry + 0.004, rz2 - 0.0125 * q, 0.0042), 0.004); e = smin(e, sph(rx, ry + 0.026 * q, rz2 - 0.002, 0.0065), 0.006); P.ear = e; d = smin(d, e, 0.006); }
    // neck, throat
    d = smin(d, sph(x, y + 0.148, z - 0.012 * s.neck, 0.011), 0.02);
    if (s.extra) d = s.extra(d, x, y, z, ax, { smin, smax, sph, ell, cone });
    // mouth slit + oral cavity, eye aperture
    const slit = Math.max(Math.abs(y - sy) - slitT(ax), ax - hw, Math.abs(z - 0.088) - 0.032), cav = ell(x, y - my + 0.0035, z - 0.071, 0.0215, 0.0115, 0.0235);
    P.cut = Math.min(slit, cav); d = Math.max(d, -slit); d = smax(d, -cav, 0.002);
    { const u = (ax - E[0]) / ehw, v = y - E[1] - s.eyeTilt * (ax - E[0]), k = Math.max(0, 1 - u * u), top = 0.0052 * ES * Math.pow(k, 0.72) * (1 - 0.22 * u), bot = -0.0039 * ES * Math.pow(k, 0.85);
      const pit = Math.abs(u) >= 1 ? 0.01 : Math.max(v - top, bot - v, E[2] - 0.002 - z); P.pit = pit; d = Math.max(d, -pit); }
    return d;
  };
  return { f, P, E, hw, my, slitY, slitT, ehw, tipY, tipZ };
}

const SKIN_PARS = `
varying vec3 vRest; varying vec4 vMask; varying vec4 vMask2; uniform float uPore,uWrinkle,uFreckle,uStubble,uSSS; uniform vec3 uStubbleCol;
float h3(vec3 p){ p=fract(p*0.3183099+.1); p*=17.; return fract(p.x*p.y*p.z*(p.x+p.y+p.z)); }
float n3(vec3 x){ vec3 i=floor(x), f=fract(x); f=f*f*(3.-2.*f); return mix(mix(mix(h3(i),h3(i+vec3(1,0,0)),f.x),mix(h3(i+vec3(0,1,0)),h3(i+vec3(1,1,0)),f.x),f.y),mix(mix(h3(i+vec3(0,0,1)),h3(i+vec3(1,0,1)),f.x),mix(h3(i+vec3(0,1,1)),h3(i+vec3(1,1,1)),f.x),f.y),f.z); }
float cell(vec3 p){ vec3 i=floor(p), f=fract(p); float d=1.; for(int a=-1;a<=1;a++)for(int b=-1;b<=1;b++)for(int c=-1;c<=1;c++){ vec3 g=vec3(float(a),float(b),float(c)); vec3 o=vec3(h3(i+g),h3(i+g+7.3),h3(i+g+13.7)); d=min(d,length(g+o-f)); } return d; }
float skinH(vec3 p, float fade){
  float pore=smoothstep(.42,.05,cell(p*1150.))*.55*uPore*(1.-vMask2.x)*(1.-vMask2.y);
  float fine=(n3(p*1700.)-.5)*.5*uPore;
  float lipl=vMask2.x*smoothstep(.35,.0,abs(sin(p.x*900.+4.*n3(p*120.))))*.9;
  float w=0.;
  if(uWrinkle>0.){ float fl=smoothstep(.3,.0,abs(sin(p.y*430.+5.*n3(p*38.)))); float cf=smoothstep(.3,.0,abs(sin(atan(p.y-.011,abs(p.x)-.046)*11.+2.*n3(p*60.))));
    float nk=smoothstep(.3,.0,abs(sin(p.y*300.+6.*n3(p*25.)))); w=(fl*vMask.z+cf*vMask.y*0.+cf*vMask2.z+nk*vMask2.w)*uWrinkle; }
  float st=smoothstep(.34,.08,cell(p*1250.))*vMask.x*uStubble;
  return (-pore*.00022+fine*.00006-lipl*.00012-w*.00045+st*.00014)*fade;
}`;
// Skin: vertex-colour albedo, wrap-diffuse with red-shifted terminator (SSS look), back-scatter in thin parts, pores etc.
export function skinMaterial(s) {
  const m = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: s.rough, metalness: 0 });
  const u = { uPore: { value: s.pores }, uWrinkle: { value: s.wrinkles }, uFreckle: { value: s.freckles }, uStubble: { value: s.stubble }, uSSS: { value: s.sss }, uStubbleCol: { value: new THREE.Color(s.stubbleColor) } };
  m.userData.u = u;
  m.onBeforeCompile = sh => { Object.assign(sh.uniforms, u);
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nattribute vec3 aRest; attribute vec4 aMask; attribute vec4 aMask2; varying vec3 vRest; varying vec4 vMask; varying vec4 vMask2;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvRest=aRest; vMask=aMask; vMask2=aMask2;');
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\n' + SKIN_PARS)
      .replace('#include <lights_physical_pars_fragment>', THREE.ShaderChunk.lights_physical_pars_fragment.replace('vec3 irradiance = dotNL * directLight.color;',
        `vec3 irradiance = dotNL * directLight.color; float nlr = dot( geometryNormal, directLight.direction );
         vec3 sssW = mix( vec3( smoothstep(-0.34,1.0,nlr), smoothstep(-0.13,1.0,nlr), smoothstep(-0.07,1.0,nlr) ), vec3(dotNL), 0.35 );
         vec3 irrD = ( mix( vec3(dotNL), sssW, uSSS ) + uSSS * vMask.w * saturate(-nlr-0.1) * vec3(0.55,0.11,0.05) ) * directLight.color;`)
        .replace('reflectedLight.directDiffuse += irradiance * diffuseBRDF', 'reflectedLight.directDiffuse += irrD * diffuseBRDF'))
      .replace('#include <color_fragment>', `#include <color_fragment>
        { float fw=length(fwidth(vRest)); float fadeD=smoothstep(.0035,.0009,fw);
          float blot=n3(vRest*95.)-.5; diffuseColor.rgb*=1.+blot*.10*(1.-vMask2.y); diffuseColor.r*=1.+.04*(n3(vRest*310.)-.5);
          float fr=smoothstep(.60,.70,n3(vRest*640.+3.))*smoothstep(.25,.6,n3(vRest*170.))*vMask.y*uFreckle; diffuseColor.rgb=mix(diffuseColor.rgb,diffuseColor.rgb*vec3(.62,.40,.28),fr*mix(.45,1.,fadeD));
          float st=mix(.8,smoothstep(.38,.10,cell(vRest*1250.))*1.3+.6,fadeD)*vMask.x*uStubble; diffuseColor.rgb=mix(diffuseColor.rgb,uStubbleCol*vec3(.9,1.,1.15),clamp(st*1.25,0.,1.)*.8);
          diffuseColor.rgb*=1.-vMask2.x*.25*smoothstep(.4,.0,abs(sin(vRest.x*900.+4.*n3(vRest*120.))))*fadeD; }`)
      .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>
        roughnessFactor=mix(roughnessFactor,.30,vMask2.x); roughnessFactor=mix(roughnessFactor,.5,vMask2.y); roughnessFactor+=.10*(n3(vRest*260.)-.5);`)
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
        { float fw=length(fwidth(vRest)); float fadeD=smoothstep(.0028,.0007,fw); if(fadeD>0.){ float hh=skinH(vRest,fadeD);
          vec3 dpx=dFdx(-vViewPosition), dpy=dFdy(-vViewPosition); float hx=dFdx(hh), hy=dFdy(hh);
          vec3 r1=cross(dpy,normal), r2=cross(normal,dpx); float det=dot(dpx,r1);
          if(abs(det)>1e-12) normal=normalize(abs(det)*normal-sign(det)*(hx*r1+hy*r2)); } }`); };
  return m;
}

// Eye texture: u = angle around the optical axis, v = polar angle from the pupil (canvas top row = pupil centre).
const eyeTexCache = new Map();
export function eyeTexture(irisHex, scleraHex, seed = 1, glow = 0) {
  const key = irisHex + ':' + scleraHex + ':' + seed + ':' + glow; if (eyeTexCache.has(key)) return eyeTexCache.get(key);
  const Wd = 1024, Hd = 512, d = new Uint8Array(Wd * Hd * 4), ic = new THREE.Color(irisHex).convertLinearToSRGB(), sc = new THREE.Color(scleraHex).convertLinearToSRGB(), r = mulberry32(seed * 7919 + 13);
  const fib = new Float32Array(Wd), fib2 = new Float32Array(Wd); for (let i = 0; i < Wd; i++) { fib[i] = r(); fib2[i] = r(); }
  for (let p = 0; p < 3; p++) for (let i = 0; i < Wd; i++) fib2[i] = (fib2[(i + Wd - 1) % Wd] + fib2[i] * 2 + fib2[(i + 1) % Wd]) / 4;
  const veins = []; for (let i = 0; i < 26; i++) veins.push([r() * Wd, 0.3 + r() * 0.5, r() * 6, 2 + r() * 5]);
  const irisA = Math.asin(0.0059 / EYE_R) / Math.PI, pupA = irisA * 0.36;
  for (let y = 0; y < Hd; y++) for (let x = 0; x < Wd; x++) { const v = (y + 0.5) / Hd, i = (y * Wd + x) * 4; let cr, cg, cb;
    if (v < irisA * 1.06) { const q = v / irisA, f = 0.55 + 0.75 * (fib[x] * 0.5 + fib2[x] * 0.5) * sstep(0.3, 0.6, q) + 0.25 * fib[(x * 3) % Wd] * (1 - q);
      const coll = Math.exp(-Math.pow((q - 0.46 - 0.05 * fib2[x]) / 0.09, 2)), limb = sstep(0.8, 1.0, q), k = f * (0.75 + 0.6 * coll) * (1 - 0.82 * limb) * (0.7 + 0.5 * q);
      cr = ic.r * k + 0.10 * coll; cg = ic.g * k + 0.07 * coll; cb = ic.b * k + 0.02 * coll;
      const pu = sstep(pupA * 1.12, pupA * 0.92, v); cr = lerp(cr, glow ? 0.02 : 0.012, pu); cg = lerp(cg, 0.012, pu); cb = lerp(cb, 0.012, pu);
      const e = sstep(1.0, 1.06, q); cr = lerp(cr, sc.r * 0.8, e); cg = lerp(cg, sc.g * 0.8, e); cb = lerp(cb, sc.b * 0.8, e); }
    else { const back = sstep(irisA * 1.5, 0.5, v); let vein = 0; for (const [vx, v0, ph, fq] of veins) { if (v < v0) continue; const dx = Math.abs(((x - vx - 14 * Math.sin(v * fq * 9 + ph) + Wd * 1.5) % Wd) - Wd / 2); vein = Math.max(vein, sstep(2.2, 0.4, dx) * sstep(v0, v0 + 0.08, v) * 0.5); }
      cr = sc.r * (1 - 0.05 * back); cg = sc.g * (1 - 0.16 * back - 0.3 * vein); cb = sc.b * (1 - 0.2 * back - 0.33 * vein); }
    { const shd = 1 - 0.42 * Math.pow(Math.max(0, Math.cos(2 * Math.PI * ((x + 0.5) / Wd - 0.75))), 1.5) * sstep(0.02, 0.09, v); cr *= shd; cg *= shd; cb *= shd; }
    d[i] = clamp(cr) * 255; d[i + 1] = clamp(cg) * 255; d[i + 2] = clamp(cb) * 255; d[i + 3] = 255; }
  const t = new THREE.DataTexture(d, Wd, Hd, THREE.RGBAFormat); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = THREE.RepeatWrapping; t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearMipmapLinearFilter; t.generateMipmaps = true; t.anisotropy = 8; t.flipY = true; t.needsUpdate = true;
  eyeTexCache.set(key, t); return t;
}

const geomCache = new Map();
function buildHeadGeometry(s) {
  const key = JSON.stringify(s, (k, v) => typeof v === 'function' ? v.toString() : v); if (geomCache.has(key)) return geomCache.get(key);
  const F = headField(s), { f, P, E, hw, my, slitY, slitT } = F, h = s.voxel;
  const m = surfaceNets(f, [-0.105 * Math.max(1, s.W) - 0.01, -0.192, -0.125], [0.105 * Math.max(1, s.W) + 0.01, 0.145 + 0.02 * Math.max(0, s.H - 1) + (s.top || 0), 0.135 + (s.front || 0)], h);
  const pos = m.position, nor = m.normal, n = pos.length / 3, col = new Float32Array(n * 3), mask = new Float32Array(n * 4), mask2 = new Float32Array(n * 4), wj = new Float32Array(n);
  const skin = new THREE.Color(s.skin), lip = new THREE.Color(s.lip), c = new THREE.Color(), inner = new THREE.Color(0x2a0806), rim = new THREE.Color(s.skin).multiply(new THREE.Color(0.62, 0.38, 0.36)), red = new THREE.Color(s.skin).multiply(new THREE.Color(1.0, 0.72, 0.66));
  const g = (x, y, z, cx, cy, cz, r) => Math.exp(-((x - cx) * (x - cx) + (y - cy) * (y - cy) + (z - cz) * (z - cz)) / (r * r));
  for (let i = 0; i < n; i++) { const x = pos[i * 3], y = pos[i * 3 + 1], z = pos[i * 3 + 2], ax = Math.abs(x), nx = nor[i * 3], ny = nor[i * 3 + 1], nz = nor[i * 3 + 2];
    f(x, y, z); const lipD = P.lip, cut = P.cut, pit = P.pit, nos = P.nos, ear = P.ear;
    const ao = clamp(f(x + nx * 0.007, y + ny * 0.007, z + nz * 0.007) / 0.007, 0, 1), ao2 = clamp(f(x + nx * 0.02, y + ny * 0.02, z + nz * 0.02) / 0.02, 0, 1);
    const sy = slitY(ax), interior = sstep(0.0012, 0.0004, Math.abs(cut)) * sstep(0.101, 0.097, z) * (ax < hw + 0.004 ? 1 : 0), lipM = sstep(0.0028, 0.0004, lipD) * sstep(0.085, 0.089, z) * (1 - interior);
    const pitM = sstep(0.0011, 0.0003, Math.abs(pit)), nosM = sstep(0.0012, 0.0002, Math.abs(nos));
    c.copy(skin);
    const blush = g(ax, y, z, 0.046, -0.028, 0.062, 0.024) * s.blush + g(x, y, z, 0, F.tipY, F.tipZ, 0.014) * s.blush * 0.7 + sstep(0.004, -0.002, ear) * 0.5 * s.blush;
    c.lerp(red, clamp(blush)); const und = g(ax, y, z, E[0], E[1] - 0.011, E[2] + 0.012, 0.011); c.multiplyScalar(1 - 0.09 * und * (0.5 + s.age)); c.r *= 1 + 0.04 * und;
    const lidD = g(ax, y, z, E[0], E[1] + 0.007, E[2] + 0.012, 0.009); c.multiplyScalar(1 - 0.10 * lidD);
    c.lerp(lip, lipM * 0.92); c.lerp(rim, pitM * 0.85); c.lerp(inner, Math.max(interior, nosM * 0.8));
    // lash line along the upper edge of the eye opening
    const lashM = pitM * sstep(E[1] + 0.001, E[1] + 0.004, y) * sstep(E[2] + 0.004, E[2] + 0.009, z); c.lerp(new THREE.Color(s.lash), lashM * 0.9);
    c.multiplyScalar((0.68 + 0.32 * ao) * (0.88 + 0.12 * ao2));
    col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
    const beard = sstep(-0.045, -0.065, y) * sstep(-0.005, 0.03, z) * sstep(-0.150, -0.125, y) * (0.55 + 0.45 * sstep(-0.05, -0.085, y)) + g(x, y, z, 0, my + 0.011, 0.105, 0.017);
    mask[i * 4] = clamp(beard * (1 - lipM) * (1 - interior) + sstep(0.06, 0.068, ax) * sstep(0.01, -0.01, y) * sstep(-0.02, 0.012, z) * sstep(-0.075, -0.05, y) * (s.sideburn || 0));
    mask[i * 4 + 1] = clamp(g(ax, y, z, 0.036, -0.022, 0.075, 0.03) + g(x, y, z, 0, -0.012, 0.105, 0.022) + 0.45 * g(x, y, z, 0, 0.05, 0.08, 0.05));
    mask[i * 4 + 2] = sstep(0.036, 0.046, y) * sstep(0.045, 0.07, z) * sstep(0.062, 0.045, ax);
    mask[i * 4 + 3] = clamp(sstep(0.003, -0.001, ear) + g(ax, y, z, 0.0116, F.tipY + 0.0048, 0.1035, 0.006) * 0.6);
    mask2[i * 4] = lipM; mask2[i * 4 + 1] = Math.max(interior, pitM, nosM); mask2[i * 4 + 2] = g(ax, y, z, 0.05, 0.011, 0.06, 0.012); mask2[i * 4 + 3] = sstep(-0.125, -0.145, y) * sstep(-0.02, 0.02, z);
    // jaw weight: below the mouth line, front of the head, fading into the neck
    const b = 0.0012 + 0.5 * Math.max(0, ax - hw * 0.9); wj[i] = sstep(-b, b, sy - y) * sstep(-0.012, 0.03, z) * Math.max(sstep(-0.137, -0.116, y), sstep(0.03, 0.06, z)) * sstep(-0.165, -0.14, y) * lerp(Math.max(0, 1 - Math.pow(Math.min(1, ax / (hw * 1.05)), 2.2)), 1, sstep(0.003, 0.022, sy - y));
  }
  // bake the lips shut (the field is sculpted with the mouth ajar so that the slit has real topology)
  for (let i = 0; i < n; i++) { const x = pos[i * 3], y = pos[i * 3 + 1], z = pos[i * 3 + 2], ax = Math.abs(x); if (ax > hw + 0.006 || z < 0.08) continue; const sy = slitY(ax), dy = y - sy;
    pos[i * 3 + 1] -= Math.sign(dy) * (slitT(ax) - 0.00012) * Math.exp(-Math.pow(dy / 0.008, 2)) * sstep(0.086, 0.096, z) * sstep(hw + 0.004, hw - 0.004, ax); }
  const rest = Float32Array.from(pos), geo = toGeometry(m);
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3)); geo.setAttribute('aRest', new THREE.BufferAttribute(rest, 3)); geo.setAttribute('aMask', new THREE.BufferAttribute(mask, 4)); geo.setAttribute('aMask2', new THREE.BufferAttribute(mask2, 4));
  // morph targets
  const T = {}, mk = name => (T[name] = new Float32Array(n * 3)), A = JAW_ANGLE, ca = Math.cos(A), sa = Math.sin(A), cz = 0.0935;
  const jaw = mk('jaw'), wide = mk('wide'), round = mk('round'), smile = mk('smile'), frown = mk('frown'), snarl = mk('snarl'), bUp = mk('browUp'), bDn = mk('browDown'), squint = mk('squint'), ff = mk('lowerIn');
  for (let i = 0; i < n; i++) { const x = rest[i * 3], y = rest[i * 3 + 1], z = rest[i * 3 + 2], ax = Math.abs(x), sg = Math.sign(x), o = i * 3, w = wj[i];
    if (w > 0) { const ry = y - JAW_HINGE[0], rz = z - JAW_HINGE[1]; jaw[o + 1] = w * (ry * ca - rz * sa - ry); jaw[o + 2] = w * (ry * sa + rz * ca - rz); }
    const sy = slitY(hw), gc = g(ax, y, z, hw, sy, cz, 0.017), gl = g(x * 0.6, y, z, 0, my, 0.105, 0.02), upper = sstep(-0.001, 0.002, y - slitY(ax)), fr = sstep(0.07, 0.09, z);
    wide[o] = sg * 0.0045 * gc; wide[o + 1] = 0.0008 * gc; wide[o + 2] = -0.0035 * gc - 0.001 * gl;
    round[o] = -sg * 0.0075 * gc - x * 0.12 * gl; round[o + 2] = 0.0035 * gc + 0.0045 * gl * fr; round[o + 1] = (upper ? 0.0012 : -0.0014) * gl;
    smile[o] = sg * 0.005 * gc; smile[o + 1] = 0.0058 * gc + 0.0022 * g(ax, y, z, 0.045, -0.03, 0.065, 0.025); smile[o + 2] = -0.0035 * gc + 0.0015 * g(ax, y, z, 0.045, -0.03, 0.065, 0.025);
    frown[o + 1] = -0.0045 * gc; frown[o] = sg * 0.001 * gc; frown[o + 2] = -0.001 * gc;
    snarl[o + 1] = 0.0042 * upper * g(ax * 0.7, y, z, 0.006, my + 0.006, 0.105, 0.016) * fr + 0.0025 * g(ax, y, z, 0.016, F.tipY, 0.1, 0.012);
    ff[o + 1] = (1 - upper) * 0.003 * gl * fr; ff[o + 2] = -(1 - upper) * 0.004 * gl * fr;
    const gb = g(ax, y, z, 0.03, 0.036, 0.085, 0.024), gi = g(ax, y, z, 0.014, 0.031, 0.092, 0.016), fh = g(x * 0.5, y, z, 0, 0.055, 0.085, 0.03);
    bUp[o + 1] = 0.0052 * gb + 0.002 * fh; bUp[o + 2] = 0.0008 * gb;
    bDn[o + 1] = -0.0042 * gi - 0.0018 * gb; bDn[o] = -sg * 0.0030 * gi; bDn[o + 2] = 0.0016 * gi;
    const gs = g(ax, y, z, E[0], E[1] - 0.012, E[2] + 0.012, 0.013); squint[o + 1] = 0.0024 * gs;
  }
  geo.morphAttributes.position = Object.values(T).map(a => new THREE.BufferAttribute(a, 3)); geo.morphTargetsRelative = true; geo.userData.morphNames = Object.keys(T);
  geo.computeBoundingSphere(); geo.boundingSphere.radius *= 1.3;
  const out = { geo, F }; geomCache.set(key, out); return out;
}
export const JAW_ANGLE = 0.34, JAW_HINGE = [-0.012, -0.008];

function lidGeometry(skinC, lashC, R) {
  const gA = new THREE.SphereGeometry(R, 22, 10, 0, Math.PI, 0.2, 1.52), p = gA.attributes.position, col = new Float32Array(p.count * 3), c = new THREE.Color();
  for (let i = 0; i < p.count; i++) { const th = Math.acos(clamp(p.getY(i) / R, -1, 1)), k = sstep(1.58, 1.72, th); c.copy(skinC).multiplyScalar(0.86 - 0.1 * sstep(1.2, 1.6, th)).lerp(lashC, k); col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b; }
  gA.setAttribute('color', new THREE.BufferAttribute(col, 3)); return gA;
}
function lashGeometry(R, n = 26) { const pos = [], th = 1.72;
  for (let i = 0; i < n; i++) { const ph = Math.PI * (0.1 + 0.8 * (i + 0.5) / n), bx = -R * Math.cos(ph) * Math.sin(th), bz = R * Math.sin(ph) * Math.sin(th), by = R * Math.cos(th), len = 0.0034 * (0.6 + 0.6 * Math.sin(ph)), w = 0.00028;
    const ox = -Math.cos(ph), oz = Math.sin(ph); pos.push(bx - oz * w, by, bz - ox * w, bx + oz * w, by, bz + ox * w, bx + ox * len * 0.75, by + len * 0.25 - 0.0006, bz + oz * len); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.computeVertexNormals(); return g; }

// makeHead(spec, {env}) -> { group, spec, field, set(state), animate(t, speech, o), mesh, eyes }
export function makeHead(spec = {}, opts = {}) {
  const s = { ...HEAD_DEFAULTS, ...spec }, { geo, F } = buildHeadGeometry(s), { E, hw, my } = F, rnd = mulberry32(s.seed * 131 + 7);
  const group = new THREE.Group(), mat = skinMaterial(s), mesh = new THREE.Mesh(geo, mat); mesh.castShadow = true; mesh.receiveShadow = true; group.add(mesh);
  const names = geo.userData.morphNames, MI = Object.fromEntries(names.map((nm, i) => [nm, i])); mesh.morphTargetInfluences = names.map(() => 0);
  // eyes
  const eyeG = new THREE.SphereGeometry(EYE_R, 40, 28); eyeG.rotateX(Math.PI / 2);
  const eyeM = new THREE.MeshPhysicalMaterial({ map: eyeTexture(s.iris, s.sclera, s.seed, s.glowEyes), roughness: 0.32, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.04, envMap: opts.env || null, envMapIntensity: opts.env ? (opts.eyeEnv ?? 0.35) : 0 });
  if (s.glowEyes) { eyeM.emissiveMap = eyeM.map; eyeM.emissive = new THREE.Color(1, 0.85, 0.5); eyeM.emissiveIntensity = s.glowEyes; }
  const skinC = new THREE.Color(s.skin), lashC = new THREE.Color(s.lash), lidG = lidGeometry(skinC, lashC, EYE_R + 0.0013), lidM = skinMaterial({ ...s, pores: 0, freckles: 0, stubble: 0, wrinkles: 0 });
  const lashM = new THREE.MeshStandardMaterial({ color: s.lash, roughness: 0.6, side: THREE.DoubleSide }), lashG = lashGeometry(EYE_R + 0.0014);
  const zero3 = n => new THREE.BufferAttribute(new Float32Array(n * 3), 3), zero4 = n => new THREE.BufferAttribute(new Float32Array(n * 4), 4);
  lidG.setAttribute('aRest', lidG.attributes.position.clone()); lidG.setAttribute('aMask', zero4(lidG.attributes.position.count)); lidG.setAttribute('aMask2', zero4(lidG.attributes.position.count));
  const eyes = [1, -1].map(sg => { const pivot = new THREE.Group(); pivot.position.set(sg * E[0], E[1], E[2]); group.add(pivot);
    const ball = new THREE.Mesh(eyeG, eyeM); ball.rotation.y = sg * 0.03; ball.receiveShadow = true; pivot.add(ball);
    const lid = new THREE.Group(); const lm = new THREE.Mesh(lidG, lidM); lm.receiveShadow = true; lid.add(lm); lid.add(new THREE.Mesh(lashG, lashM)); lid.rotation.z = sg * (s.eyeTilt * 0.9); pivot.add(lid);
    const low = new THREE.Mesh(lidG, lidM); low.receiveShadow = true; low.scale.set(1, -1, 1); low.rotation.x = 0.57; pivot.add(low);   // lower lid: mirrored visor tucked below
    return { pivot, ball, lid, low, sg }; });
  // teeth, tongue (lower set rides the jaw)
  const toothM = new THREE.MeshStandardMaterial({ color: s.teeth, roughness: 0.28 }), gumM = new THREE.MeshStandardMaterial({ color: 0x5a2420, roughness: 0.35 });
  const arch = (up) => { const gs = [], gg = []; const nT = 12; for (let i = 0; i < nT; i++) { const a = (i + 0.5 - nT / 2) / (nT / 2) * 1.25, wdt = (Math.abs(i + 0.5 - nT / 2) < 2 ? 0.0078 : 0.0066) * (up ? 1 : 0.86), ht = up ? (Math.abs(i + 0.5 - nT / 2) < 1 ? 0.0095 : 0.0082) : 0.0072;
      const x = Math.sin(a) * 0.0185 * (up ? 1 : 0.94), z = 0.0735 + Math.cos(a) * 0.0195 * (up ? 1 : 0.93) - (s.snaggle ? 0.002 * rnd() : 0), t = new THREE.CapsuleGeometry(wdt * 0.42, ht - wdt * 0.6, 3, 8); t.scale(1, 1, 0.62);
      if (s.snaggle && rnd() < s.snaggle) continue;
      t.rotateY(a); t.translate(x, (up ? my - 0.0012 : my - 0.0056) + (s.snaggle ? (rnd() - 0.5) * 0.003 : 0), z); gs.push(t); }
    const gum = new THREE.TorusGeometry(0.0188, 0.0042, 6, 20, Math.PI * 0.9); gum.rotateX(Math.PI / 2); gum.rotateY(-Math.PI * 0.05 - Math.PI / 2 + Math.PI * 0.5); gum.rotateY(Math.PI * 0.05); gum.scale(1, 1, 1.04);
    return [mergeGeometries(gs), gum]; };
  const [upG] = arch(true), [loG] = arch(false);
  const upT = new THREE.Mesh(upG, toothM); group.add(upT);
  const jawG = new THREE.Group(); jawG.position.set(0, JAW_HINGE[0], JAW_HINGE[1]); group.add(jawG);
  const loT = new THREE.Mesh(loG, toothM); loT.position.set(0, -JAW_HINGE[0], -JAW_HINGE[1]); jawG.add(loT);
  const tg = new THREE.SphereGeometry(1, 14, 10); tg.scale(0.0145, 0.0045, 0.02); const tongue = new THREE.Mesh(tg, new THREE.MeshStandardMaterial({ color: 0x6a2a2c, roughness: 0.45 })); tongue.position.set(0, my - 0.0085 - JAW_HINGE[0], 0.072 - JAW_HINGE[1]); jawG.add(tongue);
  // brows: individual hairs laid on the brow ridge
  const browM = new THREE.MeshStandardMaterial({ color: s.browColor, roughness: 0.65, side: THREE.DoubleSide }), brows = [1, -1].map(sg => { const pos = [], nH = Math.round(360 * s.browThick);
    for (let i = 0; i < nH; i++) { const t = Math.pow(rnd(), 0.9), across = (rnd() - 0.5), th = 0.0034 * s.browThick * (1 - 0.6 * t) + 0.0008;
      const bx = lerp(0.0085, 0.0085 + 0.043 * s.browLen, t) * s.eyeGap, by = E[1] + 0.0155 + s.browArch * 0.012 * Math.sin(Math.PI * Math.min(1, t * 1.25)) * (t < 0.8 ? 1 : 1 - (t - 0.8) * 1.6) - 0.003 * t * t + s.browTilt * (t - 0.4) * 0.012 + across * th * 2;
      const ang = lerp(1.15, 0.05, sstep(0.0, 0.35, t)) - 0.35 * sstep(0.6, 1, t) + (rnd() - 0.5) * 0.35, len = 0.0055 + rnd() * 0.0045, w = 0.00062;
      const p0 = project(F.f, [sg * bx, by, 0], [0, 0, 1], 0.2, 0.0004), ex = bx + Math.cos(ang) * len, ey = by + Math.sin(ang) * len, p1 = project(F.f, [sg * ex, ey, 0], [0, 0, 1], 0.2, 0.0011);
      const px = -Math.sin(ang) * w, py = Math.cos(ang) * w; pos.push(p0[0] - sg * px, p0[1] - py, p0[2], p0[0] + sg * px, p0[1] + py, p0[2], p1[0], p1[1], p1[2]); }
    const g2 = new THREE.BufferGeometry(); g2.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); const nn = new Float32Array(pos.length); for (let i = 0; i < nn.length; i += 3) { nn[i] = sg * 0.2; nn[i + 1] = 0.25; nn[i + 2] = 0.95; } g2.setAttribute('normal', new THREE.BufferAttribute(nn, 3));
    const bm = new THREE.Mesh(g2, browM); group.add(bm); return bm; });
  const st = { jaw: 0, wide: 0, round: 0, smile: 0, frown: 0, snarl: 0, browUp: 0, browDown: 0, squint: 0, lowerIn: 0, blink: 0, gazeX: 0, gazeY: 0 };
  const H = { group, mesh, spec: s, field: F, eyes, state: st, mat, eyeMat: eyeM, brows };
  const base = { ...st, ...(s.expr || {}) };
  H.set = o => { Object.assign(st, o); const inf = mesh.morphTargetInfluences;
    for (const k of names) inf[MI[k]] = st[k] || 0;
    jawG.rotation.x = JAW_ANGLE * st.jaw;
    for (const e of eyes) { e.ball.rotation.set(-st.gazeY, e.sg * 0.03 + st.gazeX, 0); e.lid.rotation.x = lerp(-0.54, 0.17, clamp(st.blink + 0.25 * st.squint + 0.12 * st.browDown - 0.1 * st.browUp + Math.max(0, -st.gazeY) * 0.5)); e.low.rotation.x = 0.57 - 0.10 * st.squint - 0.06 * st.blink; }
    for (const b of brows) { b.position.y = 0.0052 * st.browUp - 0.003 * st.browDown; b.position.z = 0.001 * st.browDown + 0.0008 * st.browUp; }
    brows[0].rotation.z = -0.10 * st.browDown; brows[1].rotation.z = 0.10 * st.browDown; return H; };
  // Idle life + speech. speech = { jaw, wide, round, lowerIn, emph } (see scene/lipsync.js); o = extra expression offsets.
  H.animate = (t, sp = null, o = {}) => { const sd = s.seed * 3.17;
    const bt = t / 3.4 + sd, bi = Math.floor(bt), bo = 0.25 + 0.5 * hash1(bi + sd * 7), bl = Math.max(sstep(0.055 / 3.4, 0, Math.abs(bt - bi - bo) - 0.012), o.blink || 0);
    const sac = Math.floor(t * 0.9 + sd), gx = (hash1(sac * 3.1 + sd) - 0.5) * 0.10 + (o.gazeX || 0), gy = (hash1(sac * 5.3 + sd) - 0.5) * 0.05 + (o.gazeY || 0);
    const e = sp ? sp.emph || 0 : 0, r = { ...base };
    for (const k in o) if (k in r && k !== 'blink' && k !== 'gazeX' && k !== 'gazeY') r[k] = (base[k] || 0) + o[k];
    if (sp && sp.active) { r.jaw = Math.max(r.jaw, sp.jaw * 0.6); r.wide += sp.wide; r.round += sp.round; r.lowerIn += sp.lowerIn || 0; r.browUp += 0.55 * e; r.snarl += 0.35 * sp.jaw + 0.2 * sp.wide; r.smile *= 1 - 0.5 * sp.jaw; r.frown *= 1 - 0.6 * sp.jaw; }
    r.blink = bl; r.gazeX = gx; r.gazeY = gy; return H.set(r); };
  H.set(base);
  return H;
}
