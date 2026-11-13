// Post pipeline: HDR scene (MSAA + depth) -> raymarched volumetric fog/light shafts -> bokeh DoF -> bloom
// -> final (dissolve mix, ACES, grade, chromatic fringe, vignette, grain, 2.39:1 letterbox, fades/flashes).
import * as THREE from 'three';
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';

const VS = `varying vec2 vUv; void main(){ vUv=uv; gl_Position=vec4(position.xy,0.,1.); }`;
const FOG = `
precision highp float; varying vec2 vUv;
uniform sampler2D tColor,tDepth; uniform mat4 uPI,uVI; uniform vec3 uCam;
uniform float uTime,uDensity,uNoiseAmt,uNoiseScale,uHeightFall,uHeightBase,uMaxDist,uFrame;
uniform vec3 uAmbient,uWind; uniform vec3 uLPos[4]; uniform vec3 uLCol[4];
uniform vec3 uBPos,uBCol; uniform vec4 uPortal; uniform vec3 uSunDir,uSunCol;
float ih(vec2 p,float f){ uvec3 v=uvec3(uint(p.x),uint(p.y),uint(f)); v=v*1664525u+1013904223u; v.x+=v.y*v.z; v.y+=v.z*v.x; v.z+=v.x*v.y; v^=v>>16u; v.x+=v.y*v.z; v.y+=v.z*v.x; v.z+=v.x*v.y; return float(v.x>>8u)/16777216.; }
float hash(vec3 p){p=fract(p*0.3183099+.1);p*=17.;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
float vn(vec3 x){vec3 i=floor(x),f=fract(x);f=f*f*(3.-2.*f);
 return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
            mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);}
float fbm(vec3 p){return vn(p)*.55+vn(p*2.03+7.)*.3+vn(p*4.1+13.)*.15;}
void main(){
  float d=texture2D(tDepth,vUv).x;
  vec4 v=uPI*vec4(vUv*2.-1.,d*2.-1.,1.); v/=v.w; vec3 wp=(uVI*vec4(v.xyz,1.)).xyz;
  vec3 rd=wp-uCam; float L=length(rd); rd/=L; L=min(L,uMaxDist);
  const int N=30; float dt=L/float(N);
  float j=ih(gl_FragCoord.xy,uFrame);
  float T=1.; vec3 S=vec3(0.);
  float sunPh=0.55+0.9*pow(max(dot(rd,uSunDir),0.),6.);
  for(int i=0;i<N;i++){
    vec3 p=uCam+rd*(float(i)+j)*dt;
    float n=fbm(p*uNoiseScale+uWind*uTime);
    float dens=uDensity*exp(-max(p.y-uHeightBase,0.)*uHeightFall)*mix(1.,n*n*3.2,uNoiseAmt);
    vec3 Li=uAmbient+uSunCol*sunPh;
    for(int k=0;k<4;k++){ vec3 dl=uLPos[k]-p; Li+=uLCol[k]/(0.6+dot(dl,dl)); }
    if(uPortal.w>0.5){
      vec3 dl=p-uBPos; float att=1./(1.+dot(dl,dl)*0.012);
      if(p.z<uPortal.x){ float s=(uPortal.x-uBPos.z)/min(dl.z,-1e-3); vec3 q=uBPos+dl*s;
        float top=uPortal.z+sqrt(max(uPortal.y*uPortal.y-q.x*q.x,0.));
        float m=smoothstep(uPortal.y,uPortal.y-.18,abs(q.x))*smoothstep(top,top-.18,q.y)*step(0.,q.y);
        Li+=uBCol*m*att; }
      else Li+=uBCol*att*0.8;
    }
    float a=1.-exp(-dens*dt); S+=T*a*Li; T*=1.-a;
  }
  gl_FragColor=vec4(texture2D(tColor,vUv).rgb*T+S,1.);
}`;
const DOF = `
precision highp float; varying vec2 vUv; uniform sampler2D tColor,tDepth; uniform float uFocus,uAperture,uNear,uFar,uMaxBlur; uniform vec2 uPx;
float lin(float d){ float z=d*2.-1.; return 2.*uNear*uFar/(uFar+uNear-z*(uFar-uNear)); }
float coc(float z){ return clamp(uAperture*abs(z-uFocus)/max(z,0.05),0.,uMaxBlur); }
void main(){
  float z0=lin(texture2D(tDepth,vUv).x), c0=coc(z0); vec3 acc=texture2D(tColor,vUv).rgb; float w=1.;
  float rad=0.7, ang=0.;
  for(int i=0;i<56;i++){ ang+=2.39996323; vec2 o=vec2(cos(ang),sin(ang))*rad; vec2 uv=vUv+o*uPx;
    vec3 sc=texture2D(tColor,uv).rgb; float sz=lin(texture2D(tDepth,uv).x), cs=coc(sz);
    if(sz>z0) cs=clamp(cs,0.,c0*2.);
    float m=smoothstep(rad-.5,rad+.5,cs); acc+=mix(acc/w,sc,m); w+=1.; rad+=uMaxBlur/56.; if(rad>uMaxBlur) break; }
  gl_FragColor=vec4(acc/w,1.);
}`;
const FIN = `
precision highp float; varying vec2 vUv; uniform sampler2D tA,tB; uniform float uMix,uExposure,uFade,uFlash,uFrame,uSat,uVig,uGrain,uBar,uContrast; uniform vec3 uShadow,uHi,uFlashCol;
vec3 aces(vec3 x){ return clamp((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),0.,1.); }
float ih(vec2 p,float f){ uvec3 v=uvec3(uint(p.x),uint(p.y),uint(f)); v=v*1664525u+1013904223u; v.x+=v.y*v.z; v.y+=v.z*v.x; v.z+=v.x*v.y; v^=v>>16u; v.x+=v.y*v.z; v.y+=v.z*v.x; v.z+=v.x*v.y; return float(v.x>>8u)/16777216.; }

vec3 samp(vec2 uv){ vec3 a=texture2D(tA,uv).rgb; if(uMix>0.001) a=mix(a,texture2D(tB,uv).rgb,uMix); return a; }
void main(){
  vec2 d=vUv-.5; float r2=dot(d,d);
  vec3 c=vec3(samp(vUv+d*r2*0.012).r,samp(vUv).g,samp(vUv-d*r2*0.012).b);
  c=c*uExposure+uFlash*uFlashCol;
  c=aces(c);
  float l=dot(c,vec3(.2126,.7152,.0722));
  c=mix(vec3(l),c,uSat);
  c*=mix(uShadow,uHi,smoothstep(0.02,0.65,l));
  c=mix(c,c*c*(3.-2.*c),uContrast);
  c*=1.-uVig*smoothstep(0.12,0.62,r2*vec2(1.,1.).x+d.y*d.y*1.5);
  c=pow(max(c,0.),vec3(1./2.2));
  float g=ih(gl_FragCoord.xy,uFrame+7.)-.5; c+=g*uGrain*(1.-l*.6);
  c*=uFade;
  if(abs(vUv.y-.5)>.5-uBar) c=vec3(0.);
  gl_FragColor=vec4(c,1.);
}`;
export class Post {
  constructor(renderer, W, H) {
    this.r = renderer; this.W = W; this.H = H;
    const hdr = () => new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, depthBuffer: false });
    this.rtScene = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, samples: 4 });
    this.rtScene.depthTexture = new THREE.DepthTexture(W, H); this.rtScene.depthTexture.type = THREE.UnsignedIntType;
    this.rtFog = hdr(); this.rtOut = [hdr(), hdr()];
    const sm = (fs, u) => new FullScreenQuad(new THREE.ShaderMaterial({ vertexShader: VS, fragmentShader: fs, uniforms: u, depthTest: false, depthWrite: false }));
    this.fogU = { tColor: { value: null }, tDepth: { value: null }, uPI: { value: new THREE.Matrix4() }, uVI: { value: new THREE.Matrix4() }, uCam: { value: new THREE.Vector3() }, uTime: { value: 0 }, uFrame: { value: 0 },
      uDensity: { value: 0.05 }, uNoiseAmt: { value: 0.7 }, uNoiseScale: { value: 0.5 }, uHeightFall: { value: 0 }, uHeightBase: { value: 0 }, uMaxDist: { value: 60 }, uAmbient: { value: new THREE.Color(0) }, uWind: { value: new THREE.Vector3(0.05, 0.12, 0.03) },
      uLPos: { value: [0, 1, 2, 3].map(() => new THREE.Vector3()) }, uLCol: { value: [0, 1, 2, 3].map(() => new THREE.Color(0)) }, uBPos: { value: new THREE.Vector3() }, uBCol: { value: new THREE.Color(0) }, uPortal: { value: new THREE.Vector4(0, 1, 1, 0) }, uSunDir: { value: new THREE.Vector3(0, 1, 0) }, uSunCol: { value: new THREE.Color(0) } };
    this.fog = sm(FOG, this.fogU);
    this.dofU = { tColor: { value: null }, tDepth: { value: null }, uFocus: { value: 5 }, uAperture: { value: 4 }, uNear: { value: 0.1 }, uFar: { value: 200 }, uMaxBlur: { value: 18 }, uPx: { value: new THREE.Vector2(1 / W, 1 / H) } };
    this.dof = sm(DOF, this.dofU);
    this.finU = { tA: { value: null }, tB: { value: null }, uMix: { value: 0 }, uExposure: { value: 1 }, uFade: { value: 1 }, uFlash: { value: 0 }, uFlashCol: { value: new THREE.Color(1, 0.95, 0.85) }, uFrame: { value: 0 }, uSat: { value: 1.05 }, uVig: { value: 0.75 }, uGrain: { value: 0.032 }, uContrast: { value: 0.55 },
      uBar: { value: (1 - (W / 2.39) / H) / 2 }, uShadow: { value: new THREE.Color(0.9, 0.98, 1.12) }, uHi: { value: new THREE.Color(1.06, 1.0, 0.92) } };
    this.fin = sm(FIN, this.finU); this.bar0 = this.finU.uBar.value;
    this.bloom = new UnrealBloomPass(new THREE.Vector2(W, H), 0.6, 0.6, 1.0);
  }
  // Renders one shot into rtOut[slot]. P = per-shot post parameters.
  shot(scene, camera, P, slot, t, frame) {
    const r = this.r, f = this.fogU;
    camera.updateMatrixWorld(); camera.updateProjectionMatrix();
    r.setRenderTarget(this.rtScene); r.setClearColor(0x000000, 1); r.clear(); r.render(scene, camera);
    f.tColor.value = this.rtScene.texture; f.tDepth.value = this.rtScene.depthTexture; f.uPI.value.copy(camera.projectionMatrixInverse); f.uVI.value.copy(camera.matrixWorld); f.uCam.value.setFromMatrixPosition(camera.matrixWorld);
    f.uTime.value = t; f.uFrame.value = frame; const F = P.fog;
    f.uDensity.value = F.density; f.uNoiseAmt.value = F.noise ?? 0.7; f.uNoiseScale.value = F.scale ?? 0.5; f.uHeightFall.value = F.fall ?? 0; f.uHeightBase.value = F.base ?? 0; f.uMaxDist.value = F.maxDist ?? 60;
    f.uAmbient.value.fromArray(F.ambient || [0, 0, 0]); f.uWind.value.fromArray(F.wind || [0.05, 0.12, 0.03]);
    for (let i = 0; i < 4; i++) { const l = (F.lights || [])[i]; if (l) { f.uLPos.value[i].copy(l.pos); f.uLCol.value[i].copy(l.col); } else f.uLCol.value[i].setRGB(0, 0, 0); }
    if (F.beam) { f.uBPos.value.copy(F.beam.pos); f.uBCol.value.copy(F.beam.col); f.uPortal.value.set(F.beam.z, F.beam.halfW, F.beam.spring, 1); } else f.uPortal.value.w = 0;
    if (F.sun) { f.uSunDir.value.copy(F.sun.dir); f.uSunCol.value.copy(F.sun.col); } else f.uSunCol.value.setRGB(0, 0, 0);
    r.setRenderTarget(this.rtFog); this.fog.render(r);
    const d = this.dofU; d.tColor.value = this.rtFog.texture; d.tDepth.value = this.rtScene.depthTexture; d.uFocus.value = P.focus; d.uAperture.value = P.aperture; d.uNear.value = camera.near; d.uFar.value = camera.far; d.uMaxBlur.value = P.maxBlur ?? 18;
    r.setRenderTarget(this.rtOut[slot]); this.dof.render(r);
    this.bloom.strength = P.bloom ?? 0.6; this.bloom.threshold = P.bloomThreshold ?? 0.95; this.bloom.radius = 0.65;
    this.bloom.render(r, null, this.rtOut[slot], 0, false);
  }
  final(P, mix, fade, flash, frame) {
    const u = this.finU; u.tA.value = this.rtOut[0].texture; u.tB.value = this.rtOut[1].texture; u.uMix.value = mix; u.uFade.value = fade; u.uFlash.value = flash; u.uFrame.value = frame;
    u.uExposure.value = P.exposure ?? 1; u.uBar.value = P.bar ?? this.bar0; u.uGrain.value = P.grain ?? 0.032; u.uSat.value = P.sat ?? 1.05; u.uVig.value = P.vignette ?? 0.75;
    u.uShadow.value.fromArray(P.shadowTint || [0.9, 0.98, 1.12]); u.uHi.value.fromArray(P.hiTint || [1.06, 1.0, 0.92]);
    if (P.flashCol) u.uFlashCol.value.fromArray(P.flashCol); else u.uFlashCol.value.setRGB(1, 0.95, 0.85);
    this.r.setRenderTarget(null); this.fin.render(this.r);
  }
}
