// Procedural surface materials evaluated in object space (no UVs needed): cloth, leather, damask, chain mail, fur,
// wood planks, worn metal, rust, aged bone; plus a soft-skin material with wrap/SSS lighting for hands and limbs.
import * as THREE from 'three';

export const NOISE_GLSL = `
float h3(vec3 p){ p=fract(p*0.3183099+.1); p*=17.; return fract(p.x*p.y*p.z*(p.x+p.y+p.z)); }
float n3(vec3 x){ vec3 i=floor(x), f=fract(x); f=f*f*(3.-2.*f); return mix(mix(mix(h3(i),h3(i+vec3(1,0,0)),f.x),mix(h3(i+vec3(0,1,0)),h3(i+vec3(1,1,0)),f.x),f.y),mix(mix(h3(i+vec3(0,0,1)),h3(i+vec3(1,0,1)),f.x),mix(h3(i+vec3(0,1,1)),h3(i+vec3(1,1,1)),f.x),f.y),f.z); }
float fbm3(vec3 p){ return n3(p)*.5+n3(p*2.03+5.)*.3+n3(p*4.1+11.)*.2; }
float cell(vec3 p){ vec3 i=floor(p), f=fract(p); float d=1.; for(int a=-1;a<=1;a++)for(int b=-1;b<=1;b++)for(int c=-1;c<=1;c++){ vec3 g=vec3(float(a),float(b),float(c)); vec3 o=vec3(h3(i+g),h3(i+g+7.3),h3(i+g+13.7)); d=min(d,length(g+o-f)); } return d; }
vec2 cell2(vec3 p){ vec3 i=floor(p), f=fract(p); float d=1., e=1.; for(int a=-1;a<=1;a++)for(int b=-1;b<=1;b++)for(int c=-1;c<=1;c++){ vec3 g=vec3(float(a),float(b),float(c)); vec3 o=vec3(h3(i+g),h3(i+g+7.3),h3(i+g+13.7)); float l=length(g+o-f); if(l<d){e=d;d=l;} else if(l<e) e=l; } return vec2(d,e); }`;
// each kind: void fab(vec3 p, float fw, inout vec3 col, inout float rough, inout float metal, out float h)   (p in metres, object space)
const KINDS = {
  cloth: `float m=fbm3(p*34.); col*=.86+.3*m; float fade=smoothstep(.004,.001,fw); float u=atan(p.x,p.z)*.13, w=sin(u*2600.)*sin(p.y*2600.); h=(w*.00004+n3(p*420.)*.00012)*fade; rough+=.06*(m-.5); col*=1.+.05*w*fade;`,
  linen: `float m=fbm3(p*30.); col*=.9+.2*m; float fade=smoothstep(.004,.001,fw); float fold=sin(p.y*90.+4.*n3(p*14.)); col*=1.+.05*fold; h=(fold*.0006+n3(p*500.)*.0001)*mix(.3,1.,fade);`,
  leather: `float m=fbm3(p*26.); vec2 c=cell2(p*340.); float cr=smoothstep(.0,.09,c.y-c.x); float fade=smoothstep(.005,.0012,fw); col*=(.72+.5*m)*mix(1.,.62+.38*cr,fade); float sc=smoothstep(.72,.8,n3(p*vec3(60.,9.,60.))); col=mix(col,col*1.7+.02,sc*.35); rough=mix(rough,rough-.14*cr,fade)+.12*sc; h=(cr*.00022-sc*.0002)*fade;`,
  damask: `float m=fbm3(p*30.); float u=atan(p.x,p.z)*.16, K=140.; float q=sin(u*K)*sin(p.y*K)+.55*sin(u*K*2.+1.3*sin(p.y*K))*sin(p.y*K*2.)+.35*sin((u+p.y)*K*1.5); float pat=smoothstep(.15,.45,q); float fade=smoothstep(.02,.004,fw); col=mix(col,uColB,pat*mix(.45,1.,fade)); col*=.85+.3*m; rough=rough-.22*pat; h=pat*.00025*fade;`,
  chain: `float u=atan(p.x,p.z)*.14; vec2 g=vec2(u,p.y)*190.; g.x+=.5*floor(g.y); vec2 f=fract(g)-.5; float r=abs(length(f*vec2(1.,1.25))-.34); float ring=smoothstep(.16,.04,r); float fade=smoothstep(.006,.0015,fw); col*=mix(.6,.25+.95*ring,fade)*(.8+.4*n3(p*50.)); metal=mix(.75,.4+.55*ring,fade); rough=.42+.25*(1.-ring); h=ring*.0009*fade;`,
  fur: `float s=n3(p*vec3(260.,34.,260.)); float t=n3(p*vec3(90.,16.,90.)+7.); col*=.6+.75*s*t+.25*t; h=(s*.0018+t*.003)*smoothstep(.02,.003,fw); rough=1.;`,
  wood: `float pl=p.x*11.+.3*n3(p*3.); float e=abs(fract(pl)-.5); float gap=smoothstep(.47,.5,e); float gr=n3(vec3(p.x*380.,p.y*7.+floor(pl)*3.,p.z*40.)); float ring=n3(vec3(p.x*40.,p.y*2.,floor(pl)*9.)); col*=(.62+.5*gr+.25*ring)*(1.-.75*gap)*(.85+.3*h3(vec3(floor(pl),1.,2.))); float sc=smoothstep(.75,.82,n3(p*vec3(14.,70.,30.))); col=mix(col,col*.5,sc*.5); h=(-gap*.002+gr*.0003-sc*.0005); rough=.78+.15*gr;`,
  metal: `float m=fbm3(p*22.); float sc=smoothstep(.62,.7,n3(p*vec3(240.,30.,240.)))+smoothstep(.66,.72,n3(p*vec3(30.,260.,30.)+3.)); float pat=smoothstep(.45,.75,fbm3(p*9.+2.)); col*=(.7+.5*m)*(1.-.45*pat); col=mix(col,col*1.5+.03,clamp(sc,0.,1.)*.4); rough=clamp(rough+.25*pat-.1*clamp(sc,0.,1.)+.1*(m-.5),.12,1.); metal=mix(metal,metal*.6,pat); h=(-pat*.0003+sc*.00008)*smoothstep(.006,.001,fw);`,
  rust: `float m=fbm3(p*18.); float r=smoothstep(.36,.62,fbm3(p*31.+4.)+.25*(n3(p*130.)-.5)); float pit=smoothstep(.3,.05,cell(p*190.)); vec3 rc=mix(vec3(.30,.11,.035),vec3(.12,.05,.025),n3(p*70.)); col=mix(col*(.5+.5*m),rc*(.55+.9*m),r); col*=1.-.35*pit*r; metal=mix(metal,.08,r); rough=mix(rough,.95,r); h=(r*.0006-pit*r*.0005+n3(p*300.)*.00012)*smoothstep(.008,.0015,fw);`,
  bone: `float m=fbm3(p*24.); float crack=smoothstep(.022,.004,abs(n3(p*44.+1.7)-.5))*smoothstep(.35,.6,n3(p*9.)); float crack2=smoothstep(.014,.003,abs(n3(p*120.+9.)-.5))*smoothstep(.5,.7,n3(p*17.+3.)); float pore=smoothstep(.3,.06,cell(p*520.)); float stain=smoothstep(.42,.72,fbm3(p*12.+8.));
    col*=.74+.42*m; col=mix(col,col*vec3(.55,.4,.24),stain*.85); col=mix(col,vec3(.05,.035,.02),clamp(crack+crack2*.8,0.,1.)*.85); col*=1.-.22*pore; rough=clamp(.62+.3*stain+.2*pore-.1*m,0.,1.); h=(-(crack+crack2*.6)*.0007-pore*.00016+m*.0005)*smoothstep(.008,.0012,fw);`,
};
const cacheF = new Map();
// fabric(kind, color, { colorB, rough, metal, side, bump, vertexColors }) -> MeshStandardMaterial
export function fabric(kind, color, o = {}) {
  const key = kind + ':' + color + ':' + JSON.stringify(o); if (cacheF.has(key)) return cacheF.get(key);
  const m = new THREE.MeshStandardMaterial({ color, roughness: o.rough ?? ({ leather: 0.62, metal: 0.38, chain: 0.5, damask: 0.72, bone: 0.7 }[kind] ?? 0.92), metalness: o.metal ?? ({ metal: 0.9, chain: 0.8, rust: 0.7 }[kind] ?? 0), side: o.side ?? THREE.FrontSide, vertexColors: !!o.vertexColors });
  const u = { uColB: { value: new THREE.Color(o.colorB ?? color) }, uBump: { value: o.bump ?? 1 } }; m.userData.u = u;
  m.customProgramCacheKey = () => 'fab-' + kind;
  m.onBeforeCompile = sh => { Object.assign(sh.uniforms, u);
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vObj;').replace('#include <begin_vertex>', '#include <begin_vertex>\nvObj=position;');
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', `#include <common>\nvarying vec3 vObj; uniform vec3 uColB; uniform float uBump; float gRough, gMetal, gH;\n${NOISE_GLSL}\nvoid fab(vec3 p, float fw, inout vec3 col, inout float rough, inout float metal, out float h){ h=0.; ${KINDS[kind] || KINDS.cloth} }`)
      .replace('#include <color_fragment>', `#include <color_fragment>\n gRough=roughness; gMetal=metalness; fab(vObj, length(fwidth(vObj)), diffuseColor.rgb, gRough, gMetal, gH);`)
      .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>\n roughnessFactor=clamp(gRough,.05,1.);`)
      .replace('#include <metalnessmap_fragment>', `#include <metalnessmap_fragment>\n metalnessFactor=clamp(gMetal,0.,1.);`)
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
        { float hh=gH*uBump; vec3 dpx=dFdx(-vViewPosition), dpy=dFdy(-vViewPosition); float hx=dFdx(hh), hy=dFdy(hh); vec3 r1=cross(dpy,normal), r2=cross(normal,dpx); float det=dot(dpx,r1);
          if(abs(det)>1e-12) normal=normalize(abs(det)*normal-sign(det)*(hx*r1+hy*r2)); }`); };
  cacheF.set(key, m); return m;
}
// plain-colour skin with the same wrap/SSS light response as the face shader (hands, forearms, bare limbs)
const cacheS = new Map();
export function softSkin(color, rough = 0.55) {
  const key = color + ':' + rough; if (cacheS.has(key)) return cacheS.get(key);
  const m = new THREE.MeshStandardMaterial({ color, roughness: rough });
  m.customProgramCacheKey = () => 'softskin';
  m.onBeforeCompile = sh => {
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vObj;').replace('#include <begin_vertex>', '#include <begin_vertex>\nvObj=position;');
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', `#include <common>\nvarying vec3 vObj;\n${NOISE_GLSL}`)
      .replace('#include <lights_physical_pars_fragment>', THREE.ShaderChunk.lights_physical_pars_fragment.replace('vec3 irradiance = dotNL * directLight.color;',
        `vec3 irradiance = dotNL * directLight.color; float nlr = dot( geometryNormal, directLight.direction ); vec3 irrD = mix( vec3( smoothstep(-0.34,1.0,nlr), smoothstep(-0.13,1.0,nlr), smoothstep(-0.07,1.0,nlr) ), vec3(dotNL), 0.35 ) * directLight.color;`)
        .replace('reflectedLight.directDiffuse += irradiance * diffuseBRDF', 'reflectedLight.directDiffuse += irrD * diffuseBRDF'))
      .replace('#include <color_fragment>', `#include <color_fragment>\n diffuseColor.rgb*=.9+.2*n3(vObj*120.); diffuseColor.r*=1.+.05*(n3(vObj*300.)-.5);`)
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
        { float fw=length(fwidth(vObj)); float fade=smoothstep(.003,.0008,fw); if(fade>0.){ float hh=(-smoothstep(.4,.05,cell(vObj*700.))*.0002-smoothstep(.25,.0,abs(sin(vObj.y*1500.+3.*n3(vObj*200.))))*.00006)*fade; vec3 dpx=dFdx(-vViewPosition), dpy=dFdy(-vViewPosition); float hx=dFdx(hh), hy=dFdy(hh); vec3 r1=cross(dpy,normal), r2=cross(normal,dpx); float det=dot(dpx,r1);
          if(abs(det)>1e-12) normal=normalize(abs(det)*normal-sign(det)*(hx*r1+hy*r2)); } }`); };
  cacheS.set(key, m); return m;
}
export const gold = (c = 0xb08a3a, rough = 0.36) => fabric('metal', c, { rough, metal: 0.95 });
