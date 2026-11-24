// Color Race 3D renderer. Every frame is a pure function of (timeline, frame index),
// so several browser pages can render different frames in parallel.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { Sky } from 'three/addons/objects/Sky.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { buildCharacter, CHAR_CFG } from '/web/chars.js';

const W = 1080, H = 1920;
const LANE_W = 1.15, COM_H = 1.0, CYCLE_M = 4.4, G = 13;
const PI = Math.PI;

// ------------------------------------------------------------------ helpers
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const smooth = t => { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); };
function rng(seed) {
  let a = (seed * 2654435761) >>> 0 || 1;
  return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const V = (x, y, z) => new THREE.Vector3(x, y, z);

let TL, N, FPS, SIM, TRACK, trackW, half, events, killOf = {};
let renderer, scene, camera, sun, hemi, sky, P, hud, g, crowd, R = [], FX = [], lights = [];
let CH = CHAR_CFG.person, CHAR = 'person', curVt = 0, vtNow = 0;
let debris, theme, baseExposure = 0.55, envMap, envIntensity = 1;
const laneX = i => (i - (N - 1) / 2) * LANE_W;

function xAt(i, t) {
  if (t <= 0) return 0;
  const a = TL.xs[i], k = t * SIM, k0 = Math.min(a.length - 1, Math.floor(k)), k1 = Math.min(a.length - 1, k0 + 1);
  return lerp(a[k0], a[k1], k - k0);
}
const vAt = (i, t) => (xAt(i, t + 0.05) - xAt(i, Math.max(0, t - 0.05))) / 0.1;

// ------------------------------------------------------------------ procedural textures
function canvasTex(w, h, draw, repeat) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = window.ANISO ?? 1;
  if (repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(...repeat); }
  return t;
}
function noiseFill(ctx, w, h, base, amp, seed) {
  const r = rng(seed), img = ctx.getImageData(0, 0, w, h), d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const n = (r() - 0.5) * amp;
    d[i] = clamp(base[0] + n, 0, 255); d[i + 1] = clamp(base[1] + n * 0.8, 0, 255); d[i + 2] = clamp(base[2] + n * 0.6, 0, 255); d[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
}
function puffTex(soft = 1) {
  return canvasTex(128, 128, (c, w, h) => {
    const gr = c.createRadialGradient(64, 64, 0, 64, 64, 64);
    gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(0.35 * soft, 'rgba(255,255,255,0.6)'); gr.addColorStop(1, 'rgba(255,255,255,0)');
    c.fillStyle = gr; c.fillRect(0, 0, w, h);
  });
}
function smokeTex() {
  return canvasTex(128, 128, (c) => {
    const r = rng(77);
    for (let k = 0; k < 14; k++) {
      const x = 64 + (r() - 0.5) * 50, y = 64 + (r() - 0.5) * 50, rad = 18 + r() * 26;
      const gr = c.createRadialGradient(x, y, 0, x, y, rad);
      const v = 200 + r() * 55;
      gr.addColorStop(0, `rgba(${v},${v},${v},0.55)`); gr.addColorStop(1, `rgba(${v},${v},${v},0)`);
      c.fillStyle = gr; c.fillRect(0, 0, 128, 128);
    }
  });
}
function textTex(text, w, h, bg, fg, size) {
  return canvasTex(w, h, (c) => {
    c.fillStyle = bg; c.fillRect(0, 0, w, h);
    c.fillStyle = fg; c.font = `${size}px Race`; c.textAlign = 'center'; c.textBaseline = 'middle';
    c.fillText(text, w / 2, h / 2 + size * 0.05);
  });
}

// ------------------------------------------------------------------ particles
class Particles {
  constructor(max, map, blending) {
    this.max = max; this.n = 0;
    this.pos = new Float32Array(max * 3); this.col = new Float32Array(max * 4); this.size = new Float32Array(max);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(this.pos, 3));
    geo.setAttribute('rgba', new THREE.BufferAttribute(this.col, 4));
    geo.setAttribute('size', new THREE.BufferAttribute(this.size, 1));
    this.mat = new THREE.ShaderMaterial({
      uniforms: { map: { value: map }, scale: { value: 1000 } },
      vertexShader: `attribute float size; attribute vec4 rgba; varying vec4 vC; uniform float scale;
        void main(){ vC=rgba; vec4 mv=modelViewMatrix*vec4(position,1.0); gl_PointSize=min(1500.0, size*scale/-mv.z); gl_Position=projectionMatrix*mv; }`,
      fragmentShader: `uniform sampler2D map; varying vec4 vC;
        void main(){ vec4 t=texture2D(map, gl_PointCoord); gl_FragColor=vec4(vC.rgb*t.rgb, vC.a*t.a);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
        }`,
      transparent: true, depthWrite: false, blending,
    });
    this.pts = new THREE.Points(geo, this.mat); this.pts.frustumCulled = false; this.geo = geo;
  }
  reset() { this.n = 0; }
  push(x, y, z, s, r, g_, b, a) {
    if (this.n >= this.max || a <= 0.003) return;
    const i = this.n++;
    this.pos[i * 3] = x; this.pos[i * 3 + 1] = y; this.pos[i * 3 + 2] = z;
    this.col[i * 4] = r; this.col[i * 4 + 1] = g_; this.col[i * 4 + 2] = b; this.col[i * 4 + 3] = a; this.size[i] = s;
  }
  commit() {
    this.geo.setDrawRange(0, this.n);
    for (const k of ['position', 'rgba', 'size']) this.geo.attributes[k].needsUpdate = true;
    this.mat.uniforms.scale.value = H / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2));
  }
}

function explosionFX(I, t0, t, seed, scale = 1, smokeCol = 0.13) {
  const dt = t - t0;
  if (dt < 0 || dt > 6) return;
  const r = rng(seed);
  for (let k = 0; k < 80; k++) {           // fireball
    const life = 0.45 + r() * 0.8, th = r() * 2 * PI, up = 0.15 + r() * 0.85, sp = (3 + r() * 10) * scale, del = r() * 0.08;
    const d = dt - del; if (d < 0 || d > life) continue;
    const s = (1 - Math.exp(-3.5 * d)) / 3.5, hr = Math.sqrt(1 - up * up), a = d / life;
    const x = I.x + Math.cos(th) * hr * sp * s, y = I.y + 0.3 + up * sp * s + 1.5 * d, z = I.z + Math.sin(th) * hr * sp * s;
    const c = a < 0.12 ? [1, 0.95, 0.75] : a < 0.45 ? [1, lerp(0.75, 0.38, (a - 0.12) / 0.33), lerp(0.4, 0.08, (a - 0.12) / 0.33)] : [lerp(1, 0.35, (a - 0.45) / 0.55), lerp(0.38, 0.08, (a - 0.45) / 0.55), 0.03];
    P.fire.push(x, y, z, (1.0 + 3.2 * Math.sqrt(a)) * scale, c[0] * 3, c[1] * 3, c[2] * 3, Math.pow(1 - a, 1.3));
  }
  for (let k = 0; k < 50; k++) {           // smoke column
    const life = 2.5 + r() * 2.5, th = r() * 2 * PI, sp = (1 + r() * 4) * scale, del = 0.1 + r() * 0.3, rise = 1 + r() * 2.2;
    const d = dt - del; if (d < 0 || d > life) continue;
    const a = d / life, s = (1 - Math.exp(-2 * d)) / 2;
    const v = smokeCol + r() * 0.08;
    P.smoke.push(I.x + Math.cos(th) * sp * s, I.y + 0.5 + rise * d + sp * s * 0.5, I.z + Math.sin(th) * sp * s,
      (1.5 + 4.5 * Math.sqrt(a)) * scale, v, v * 0.95, v * 0.9, 0.8 * Math.min(1, d * 4) * (1 - a));
  }
  for (let k = 0; k < 60; k++) {           // embers
    const life = 0.8 + r() * 1.4, th = r() * 2 * PI, up = 0.3 + r() * 0.7, sp = (6 + r() * 12) * scale;
    if (dt > life) continue;
    const hr = Math.sqrt(1 - up * up);
    const y = I.y + 0.3 + up * sp * dt - 0.5 * 9.8 * dt * dt;
    if (y < 0.02) continue;
    P.fire.push(I.x + Math.cos(th) * hr * sp * dt, y, I.z + Math.sin(th) * hr * sp * dt, 0.14, 3, 1.6, 0.5, 1 - dt / life);
  }
}

function dustFX(I, t0, t, seed, n = 30, spread = 3, col = [0.55, 0.42, 0.33]) {
  const dt = t - t0; if (dt < 0 || dt > 3) return;
  const r = rng(seed);
  for (let k = 0; k < n; k++) {
    const life = 1.2 + r() * 1.6, th = r() * 2 * PI, sp = spread * (0.4 + r());
    if (dt > life) continue;
    const a = dt / life, s = (1 - Math.exp(-3 * dt)) / 3;
    P.smoke.push(I.x + Math.cos(th) * sp * s, I.y + 0.2 + 0.8 * dt, I.z + Math.sin(th) * sp * s, 0.8 + 2.2 * a,
      col[0], col[1], col[2], 0.6 * (1 - a));
  }
}

// ------------------------------------------------------------------ scene building
// ------------------------------------------------------------------ worlds (locations)
const WORLDS = {
  stadium: { title: 'STADIUM SPRINT', ground: [62, 122, 52], gAmp: 34, track: 'tartan', obstacle: 'hurdle', dust: [0.62, 0.45, 0.36], pit: 0x9e3a28 },
  desert: { title: 'DESERT DASH', ground: [214, 178, 122], gAmp: 26, track: 'dirt', trackCol: [178, 136, 90], obstacle: 'rock', dust: [0.8, 0.66, 0.47], pit: 0xa87a50, fog: 0xe8d4b4, fogNear: 90 },
  snow: { title: 'FROZEN PASS', ground: [228, 236, 246], gAmp: 12, track: 'snow', trackCol: [206, 219, 234], obstacle: 'ice', dust: [0.95, 0.97, 1.0], pit: 0xc8d6e6, fog: 0xdbe3ec, fogNear: 45, fogFar: 380, sunK: 0.75, hemiK: 1.35 },
  city: { title: 'CITY RUSH', ground: [78, 78, 82], gAmp: 18, track: 'asphalt', trackCol: [50, 50, 54], obstacle: 'barrier', dust: [0.5, 0.5, 0.52], pit: 0x333336 },
  forest: { title: 'FOREST TRAIL', ground: [56, 98, 40], gAmp: 30, track: 'dirt', trackCol: [122, 90, 60], obstacle: 'log', dust: [0.5, 0.4, 0.3], pit: 0x6e5034, fog: 0xb8c8b0, fogNear: 40, fogFar: 320 },
  volcano: { title: 'VOLCANO RUN', ground: [40, 34, 32], gAmp: 22, track: 'basalt', trackCol: [64, 56, 52], obstacle: 'rock', dust: [0.32, 0.3, 0.29], pit: 0x2a2422, fog: 0x3a1c14, fogNear: 60, fogFar: 520 },
};
let WORLD, worldAnim = [];

function colorize(geo, hex) {
  geo = geo.index ? geo.toNonIndexed() : geo;
  const c = new THREE.Color(hex), n = geo.attributes.position.count, a = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) a.set([c.r, c.g, c.b], i * 3);
  geo.setAttribute('color', new THREE.BufferAttribute(a, 3));
  return geo;
}
const place = (geo, x, y, z, rx = 0, ry = 0, rz = 0) => { geo.rotateX(rx); geo.rotateY(ry); geo.rotateZ(rz); geo.translate(x, y, z); return geo; };
const merge = parts => mergeGeometries(parts.map(p => { const g = p.index ? p.toNonIndexed() : p; if (!g.attributes.uv) g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(g.attributes.position.count * 2), 2)); return g; }));

// static instanced scenery, chunked along the track so off-screen chunks are culled
function scatter(geo, mat, items, shadow = false) {
  const CH = 40, groups = {};
  for (const it of items) (groups[Math.floor(it.z / CH)] ??= []).push(it);
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), c = new THREE.Color(), e = new THREE.Euler();
  for (const k in groups) {
    const arr = groups[k], im = new THREE.InstancedMesh(geo, mat, arr.length);
    arr.forEach((it, i) => {
      q.setFromEuler(e.set(it.rx || 0, it.ry || 0, it.rz || 0));
      m4.compose(V(it.x, it.y || 0, it.z), q, V(it.sx ?? it.s, it.sy ?? it.s, it.sz ?? it.s));
      im.setMatrixAt(i, m4);
      if (it.c != null) im.setColorAt(i, c.set(it.c));
    });
    im.castShadow = shadow; im.computeBoundingSphere(); scene.add(im);
  }
}
function sideItems(count, xMin, xMax, seed, fn) {
  const r = rng(seed), out = [];
  for (let k = 0; k < count; k++) {
    const s = r() < 0.5 ? -1 : 1, x = s * (half + xMin + r() * (xMax - xMin)), z = 120 - r() * (TRACK + 280);
    out.push(fn({ x, z, s, r }));
  }
  return out;
}

function buildWorld() {
  WORLD = WORLDS[TL.world] || WORLDS.stadium;
  const TH = {
    day: { elev: 38, az: 25, turb: 4, ray: 1.4, mie: 0.004, sunCol: 0xffffff, sunI: 3.4, hemiI: 0.9, exp: 0.55, fog: 0xbfd2e6 },
    sunset: { elev: 7, az: 120, turb: 9, ray: 2.8, mie: 0.01, sunCol: 0xffb36b, sunI: 3.2, hemiI: 0.55, exp: 0.62, fog: 0xe0a77d },
    night: { elev: -6, az: 60, turb: 1, ray: 0.3, mie: 0.002, sunCol: 0xdfe8ff, sunI: 2.6, hemiI: 0.35, exp: 0.95, fog: 0x0c1220 },
    volcano: { elev: 2, az: 150, turb: 12, ray: 4, mie: 0.03, sunCol: 0xff8050, sunI: 2.0, hemiI: 0.55, exp: 0.85, fog: 0x3a1c14 },
  }[theme];
  baseExposure = TH.exp;
  renderer.toneMappingExposure = TH.exp;

  sky = new Sky(); sky.scale.setScalar(4000);
  const u = sky.material.uniforms;
  u.turbidity.value = TH.turb; u.rayleigh.value = TH.ray; u.mieCoefficient.value = TH.mie; u.mieDirectionalG.value = 0.8;
  const sunDir = new THREE.Vector3().setFromSphericalCoords(1, THREE.MathUtils.degToRad(90 - TH.elev), THREE.MathUtils.degToRad(TH.az));
  u.sunPosition.value.copy(sunDir);
  const pm = new THREE.PMREMGenerator(renderer);
  const envScene = new THREE.Scene(); envScene.add(sky);
  envMap = pm.fromScene(envScene).texture;      // reflections only on runners (full-scene IBL is too slow on CPU)
  envIntensity = theme === 'night' ? 0.35 : 0.9;
  scene.add(sky);
  const fogCol = theme === 'night' ? TH.fog : (WORLD.fog ?? TH.fog);
  scene.fog = new THREE.Fog(fogCol, WORLD.fogNear ?? 140, WORLD.fogFar ?? 700);
  if (theme === 'night') {
    const r = rng(5), n = 1500, pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { const v = new THREE.Vector3().setFromSphericalCoords(1500, Math.acos(r() * 0.95), r() * 2 * PI); pos.set([v.x, v.y, v.z], i * 3); }
    const gs = new THREE.BufferGeometry(); gs.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    scene.add(new THREE.Points(gs, new THREE.PointsMaterial({ color: 0xffffff, size: 2, sizeAttenuation: false, fog: false })));
  }

  const keyDir = theme === 'night' ? V(0.35, 1, 0.25).normalize() : sunDir.clone().setY(Math.max(sunDir.y, 0.12)).normalize();
  sun = new THREE.DirectionalLight(TH.sunCol, TH.sunI * (WORLD.sunK ?? 1));
  sun.userData.dir = keyDir;
  sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -22, right: 22, top: 22, bottom: -22, near: 1, far: 250 });
  sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.03;
  scene.add(sun, sun.target);
  hemi = new THREE.HemisphereLight(theme === 'night' ? 0x6080b0 : 0xcfe3ff, TL.world === 'volcano' ? 0xff5020 : 0x5a4a3a, TH.hemiI * (WORLD.hemiK ?? 1));
  scene.add(hemi);
  { const l = new THREE.PointLight(0xff8a30, 0, 40, 1.6); scene.add(l); lights.push(l); }

  // ground
  const groundTex = canvasTex(512, 512, (c, w, h) => {
    noiseFill(c, w, h, WORLD.ground, WORLD.gAmp, 3);
    if (TL.world === 'stadium') { c.fillStyle = 'rgba(255,255,255,0.06)'; c.fillRect(0, 0, w, h / 2); }
  }, [40, 90]);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(900, 1600), new THREE.MeshStandardMaterial({ map: groundTex, roughness: 0.95 }));
  ground.rotation.x = -PI / 2; ground.position.set(0, -0.01, -TRACK / 2); ground.receiveShadow = true;
  scene.add(ground);

  // track surface
  const len = TRACK + 120;
  const tc = WORLD.trackCol || [176, 66, 44];
  const trackTex = canvasTex(1024, 1024, (c, w, h) => {
    noiseFill(c, w, h, tc, TL.world === 'snow' ? 18 : 46, 11);
    const lx = k => (0.6 + k * LANE_W) / trackW * w;
    if (WORLD.track === 'tartan') {
      c.fillStyle = '#f4efe6';
      for (let k = 0; k <= N; k++) c.fillRect(lx(k) - 3, 0, 6, h);
    } else if (WORLD.track === 'asphalt') {
      c.fillStyle = '#e8c23a'; c.fillRect(lx(0) - 5, 0, 10, h); c.fillRect(lx(N) - 5, 0, 10, h);
      c.fillStyle = '#e9e9e9';
      for (let k = 1; k < N; k++) for (let y = 0; y < h; y += 256) c.fillRect(lx(k) - 3, y, 6, 140);
    } else {
      const r = rng(21);   // ruts / footprints / cracks
      for (let k = 0; k < 900; k++) {
        const x = r() * w, y = r() * h;
        c.fillStyle = WORLD.track === 'basalt' ? `rgba(255,${80 + r() * 60},20,${0.15 + r() * 0.25})` : `rgba(0,0,0,${0.04 + r() * 0.07})`;
        c.fillRect(x, y, 2 + r() * 6, 8 + r() * 40);
      }
    }
  }, [1, len / 12]);
  const bumpTex = canvasTex(512, 512, (c, w, h) => noiseFill(c, w, h, [128, 128, 128], 120, 12), [trackW / 2, len / 2]);
  bumpTex.colorSpace = THREE.NoColorSpace;
  const trackMat = new THREE.MeshStandardMaterial({ map: trackTex, bumpMap: bumpTex, bumpScale: 1.2, roughness: TL.world === 'snow' ? 0.6 : 0.88 });
  if (WORLD.track === 'basalt') { trackMat.emissive.set(0xff5a10); trackMat.emissiveMap = trackTex; trackMat.emissiveIntensity = 0.25; }
  const track = new THREE.Mesh(new THREE.PlaneGeometry(trackW, len), trackMat);
  track.rotation.x = -PI / 2; track.position.set(0, 0, 30 - len / 2); track.receiveShadow = true;
  scene.add(track);
  if (TL.world === 'stadium') {
    const curbMat = new THREE.MeshStandardMaterial({ color: 0xf2f2f2, roughness: 0.6 });
    for (const s of [-1, 1]) {
      const curb = new THREE.Mesh(new THREE.BoxGeometry(0.25, 0.12, len), curbMat);
      curb.position.set(s * (half + 0.12), 0.06, 30 - len / 2); curb.receiveShadow = curb.castShadow = true; scene.add(curb);
    }
  }
  const startLine = new THREE.Mesh(new THREE.PlaneGeometry(trackW, 0.1), new THREE.MeshStandardMaterial({ color: 0xffffff }));
  startLine.rotation.x = -PI / 2; startLine.position.set(0, 0.004, 0.45); scene.add(startLine);
  const checker = canvasTex(256, 32, (c) => { for (let i = 0; i < 16; i++) for (let j = 0; j < 2; j++) { c.fillStyle = (i + j) % 2 ? '#111' : '#fff'; c.fillRect(i * 16, j * 16, 16, 16); } }, [trackW / 2, 1]);
  const finLine = new THREE.Mesh(new THREE.PlaneGeometry(trackW, 0.5), new THREE.MeshStandardMaterial({ map: checker, roughness: 0.7 }));
  finLine.rotation.x = -PI / 2; finLine.position.set(0, 0.004, -TRACK); scene.add(finLine);

  // start + finish arches
  const archMat = new THREE.MeshStandardMaterial({ color: 0xd8262b, roughness: 0.4, metalness: 0.3 });
  const arch = (z, label, bg) => {
    for (const s of [-1, 1]) { const p = new THREE.Mesh(new THREE.BoxGeometry(0.5, 5.2, 0.5), archMat); p.position.set(s * (half + 0.7), 2.6, z); p.castShadow = true; scene.add(p); }
    const tex = textTex(label, 1024, 160, bg, '#ffffff', 120);
    const b = new THREE.Mesh(new THREE.BoxGeometry(trackW + 1.9, 1.1, 0.4), new THREE.MeshStandardMaterial({ map: tex, emissive: 0xffffff, emissiveMap: tex, emissiveIntensity: 0.35 }));
    b.position.set(0, 5.2, z); b.castShadow = true; scene.add(b);
  };
  arch(-TRACK, 'FINISH', '#d8262b'); arch(1.5, 'START', '#1f3f9e');

  buildObstacles();
  ({ stadium: buildStadium, desert: buildDesert, snow: buildSnow, city: buildCity, forest: buildForest, volcano: buildVolcano }[TL.world] || buildStadium)();

  // distance signs
  for (let d = 50; d < TRACK; d += 50) {
    const sTex = textTex(`${d} M`, 256, 128, '#ffffff', '#111111', 80);
    const sign = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 0.8), new THREE.MeshStandardMaterial({ map: sTex }));
    sign.position.set(-(half + 1.2), 1.6, -d); sign.rotation.y = PI / 2 - 0.4; scene.add(sign);
  }

  debris = new THREE.InstancedMesh(new THREE.DodecahedronGeometry(0.13), new THREE.MeshStandardMaterial({ color: 0x3a2e26, roughness: 1 }), 400);
  debris.castShadow = true; debris.frustumCulled = false; scene.add(debris);

  P = {
    fire: new Particles(5000, puffTex(1), THREE.AdditiveBlending),
    smoke: new Particles(5000, smokeTex(), THREE.NormalBlending),
    conf: new Particles(1500, canvasTex(16, 16, (c) => { c.fillStyle = '#fff'; c.fillRect(2, 5, 12, 6); }), THREE.NormalBlending),
    flake: new Particles(1500, puffTex(1), THREE.NormalBlending),
  };
  scene.add(P.smoke.pts, P.fire.pts, P.conf.pts, P.flake.pts);
  if (!crowd) crowd = { list: [] };
}

function buildObstacles() {
  const kind = WORLD.obstacle;
  for (const hx of TL.hurdles) {
    if (kind === 'log') {
      const log = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.32, trackW + 1, 12), new THREE.MeshStandardMaterial({ color: 0x5a3e26, roughness: 0.95 }));
      log.rotation.z = PI / 2; log.position.set(0, 0.3, -hx); log.castShadow = log.receiveShadow = true; scene.add(log);
      continue;
    }
    for (let i = 0; i < N; i++) {
      if (kind === 'hurdle' || kind === 'barrier') {
        const stripe = canvasTex(256, 32, (c) => { for (let k = 0; k < 8; k++) { c.fillStyle = k % 2 ? (kind === 'barrier' ? '#ff6a00' : '#111') : '#fff'; c.fillRect(k * 32, 0, 32, 32); } });
        const postMat = new THREE.MeshStandardMaterial({ color: 0x333333, metalness: 0.6, roughness: 0.4 });
        for (const s of [-1, 1]) { const p = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.8, 0.05), postMat); p.position.set(laneX(i) + s * LANE_W * 0.42, 0.4, -hx); p.castShadow = true; scene.add(p); }
        const b = new THREE.Mesh(new THREE.BoxGeometry(LANE_W * 0.85, kind === 'barrier' ? 0.3 : 0.14, 0.04), new THREE.MeshStandardMaterial({ map: stripe, roughness: 0.5 }));
        b.position.set(laneX(i), kind === 'barrier' ? 0.68 : 0.76, -hx); b.castShadow = true; scene.add(b);
      } else if (kind === 'ice') {
        const b = new THREE.Mesh(new THREE.BoxGeometry(LANE_W * 0.8, 0.55, 0.45), new THREE.MeshStandardMaterial({ color: 0xa8d8ff, roughness: 0.08, metalness: 0.1, emissive: 0x204060, emissiveIntensity: 0.3 }));
        b.position.set(laneX(i), 0.27, -hx); b.rotation.y = (i % 2 - 0.5) * 0.15; b.castShadow = true; scene.add(b);
      } else {
        const g = new THREE.DodecahedronGeometry(0.4, 0); const b = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: TL.world === 'volcano' ? 0x2a2522 : 0x8a6a4a, roughness: 1, flatShading: true }));
        b.scale.set(1.2, 0.8, 0.9); b.position.set(laneX(i), 0.28, -hx); b.rotation.set(i, i * 2, 0); b.castShadow = true; scene.add(b);
      }
    }
  }
}

function makeCrowdMesh(bodies) {
  const bodyGeo = new THREE.CapsuleGeometry(0.2, 0.42, 1, 6), headGeo = new THREE.IcosahedronGeometry(0.13, 0);
  crowd = {
    list: bodies,
    body: new THREE.InstancedMesh(bodyGeo, new THREE.MeshStandardMaterial({ roughness: 0.8 }), Math.max(1, bodies.length)),
    head: new THREE.InstancedMesh(headGeo, new THREE.MeshStandardMaterial({ roughness: 0.6 }), Math.max(1, bodies.length)),
  };
  const col = new THREE.Color();
  bodies.forEach((b, i) => { crowd.body.setColorAt(i, col.set(b.c)); crowd.head.setColorAt(i, col.set(b.sk)); });
  scene.add(crowd.body, crowd.head);
}
const SHIRTS = [0xe8322f, 0x2f6df0, 0x25c26a, 0xf7cb15, 0xffffff, 0x222222, 0xff7a00, 0x9b4dea, 0x00c8d6, 0xff5fb4, 0x8a6b4a];
const SKINS = [0xf1c27d, 0xe0ac69, 0xc68642, 0x8d5524, 0xffdbac];

function buildStadium() {
  const ads = [['COLOR RACE', '#101820', '#ffd12e'], ['PICK YOUR COLOR', '#e8322f', '#ffffff'], ['SUBSCRIBE', '#ffffff', '#e8322f'], ['WHO SURVIVES?', '#2f6df0', '#ffffff']]
    .map(([t, bg, fg]) => textTex(t, 1024, 128, bg, fg, 90));
  const adGeo = new THREE.BoxGeometry(0.15, 0.9, 7.8);
  for (const s of [-1, 1]) for (let z = 20, k = 0; z > -TRACK - 60; z -= 8, k++) {
    const tex = ads[(k + (s > 0 ? 2 : 0)) % ads.length];
    const m = new THREE.Mesh(adGeo, new THREE.MeshStandardMaterial({ map: tex, emissive: 0xffffff, emissiveMap: tex, emissiveIntensity: theme === 'night' ? 0.9 : 0.4 }));
    m.position.set(s * (half + 2.2), 0.45, z); scene.add(m);
    tex.center.set(0.5, 0.5); tex.rotation = s > 0 ? PI / 2 : -PI / 2;
  }
  const concrete = new THREE.MeshStandardMaterial({ color: 0x9a9a9e, roughness: 0.9 });
  const seatsMat = new THREE.MeshStandardMaterial({ color: 0x29406e, roughness: 0.7 });
  const standLen = TRACK + 90, standZ = 25 - standLen / 2, ROWS = 10;
  const bodies = [], r = rng(TL.seed + 3);
  for (const s of [-1, 1]) {
    const x0 = s * (half + 5);
    for (let row = 0; row < ROWS; row++) {
      const hgt = 0.5 * (row + 1), x = x0 + s * row * 0.95;
      const step = new THREE.Mesh(new THREE.BoxGeometry(0.95, hgt, standLen), row % 2 ? seatsMat : concrete);
      step.position.set(x, hgt / 2, standZ); step.receiveShadow = true; scene.add(step);
      for (let z = 25; z > 25 - standLen; z -= 0.62) {
        if (r() < 0.12) { r(); r(); r(); continue; }
        bodies.push({ x: x + (r() - 0.5) * 0.15, y: hgt, z: z + (r() - 0.5) * 0.2, c: SHIRTS[Math.floor(r() * SHIRTS.length)], sk: SKINS[Math.floor(r() * SKINS.length)], ph: r() * 10 });
      }
    }
    const back = new THREE.Mesh(new THREE.BoxGeometry(0.6, 9, standLen), concrete);
    back.position.set(x0 + s * (ROWS * 0.95 + 0.3), 4.5, standZ); scene.add(back);
    const roof = new THREE.Mesh(new THREE.BoxGeometry(ROWS * 0.95 + 2, 0.3, standLen), new THREE.MeshStandardMaterial({ color: 0xdedede, metalness: 0.4, roughness: 0.5 }));
    roof.position.set(x0 + s * (ROWS * 0.95 / 2), 9.2, standZ); roof.castShadow = true; scene.add(roof);
    for (let z = 0; z > -TRACK - 20; z -= 70) {
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.45, 32, 8), concrete);
      pole.position.set(x0 + s * (ROWS * 0.95 + 3), 16, z); scene.add(pole);
      const panel = new THREE.Mesh(new THREE.BoxGeometry(0.5, 3, 5), new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff6dd, emissiveIntensity: theme === 'night' ? 6 : 0.6 }));
      panel.position.set(x0 + s * (ROWS * 0.95 + 2.6), 32, z); panel.rotation.z = s * 0.5; scene.add(panel);
    }
  }
  makeCrowdMesh(bodies);
}

function rockGeo(seed, detail = 1) {
  const g = new THREE.IcosahedronGeometry(1, detail), p = g.attributes.position, r = rng(seed);
  for (let k = 0; k < p.count; k++) { const f = 0.75 + r() * 0.45; p.setXYZ(k, p.getX(k) * f, p.getY(k) * f, p.getZ(k) * f); }
  g.computeVertexNormals(); return g;
}

function buildDesert() {
  const vc = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9, flatShading: true });
  const cactus = merge([
    colorize(new THREE.CylinderGeometry(0.28, 0.32, 4, 8).translate(0, 2, 0), 0x3f7a3a),
    colorize(place(new THREE.CylinderGeometry(0.18, 0.2, 1.6, 7), 0.55, 2.4, 0), 0x3f7a3a),
    colorize(place(new THREE.CylinderGeometry(0.2, 0.2, 0.7, 7), 0.35, 1.7, 0, 0, 0, PI / 2), 0x3f7a3a),
    colorize(place(new THREE.CylinderGeometry(0.16, 0.18, 1.2, 7), -0.5, 2.9, 0), 0x3f7a3a),
    colorize(place(new THREE.CylinderGeometry(0.18, 0.18, 0.6, 7), -0.32, 2.4, 0, 0, 0, PI / 2), 0x3f7a3a),
  ]);
  scatter(cactus, vc, sideItems(300, 7, 80, 31, ({ x, z, r }) => ({ x, z, s: 0.7 + r() * 0.8, ry: r() * 6, c: 0xffffff })), true);
  const rockMat = new THREE.MeshStandardMaterial({ color: 0xa8714a, roughness: 1, flatShading: true });
  scatter(rockGeo(4), rockMat, sideItems(420, 1.5, 90, 32, ({ x, z, r }) => ({ x, z, y: 0.1, s: 0.2 + r() * r() * 1.8, sy: 0.15 + r() * 0.6, ry: r() * 6 })), true);
  // mesas on the horizon
  const mesaMat = new THREE.MeshStandardMaterial({ color: 0xb4683c, roughness: 1, flatShading: true });
  const r = rng(33);
  for (let k = 0; k < 16; k++) {
    const s = k % 2 ? 1 : -1, h = 30 + r() * 60, rad = 25 + r() * 45;
    const m = new THREE.Mesh(new THREE.CylinderGeometry(rad * 0.85, rad, h, 7), mesaMat);
    m.position.set(s * (150 + r() * 250), h / 2 - 2, -r() * (TRACK + 500) + 100); m.rotation.y = r() * 6; scene.add(m);
  }
}

function pineGeo() {
  return merge([
    colorize(new THREE.CylinderGeometry(0.15, 0.22, 1.2, 6).translate(0, 0.6, 0), 0x4a3424),
    colorize(new THREE.ConeGeometry(1.6, 2.6, 8).translate(0, 2.0, 0), 0x2d5a3a),
    colorize(new THREE.ConeGeometry(1.25, 2.2, 8).translate(0, 3.2, 0), 0x2d5a3a),
    colorize(new THREE.ConeGeometry(0.85, 1.8, 8).translate(0, 4.3, 0), 0x2d5a3a),
  ]);
}

function buildSnow() {
  const vc = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.85, flatShading: true });
  scatter(pineGeo(), vc, sideItems(800, 7, 95, 41, ({ x, z, r }) => ({ x, z, s: 0.9 + r() * 1.3, ry: r() * 6, c: r() < 0.5 ? 0xffffff : 0xe6f0ff })), true);
  const snowMat = new THREE.MeshStandardMaterial({ color: 0xf4f8ff, roughness: 0.7 });
  for (const s of [-1, 1]) {      // snow banks along the path
    const bank = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.6, TRACK + 160, 10, 1, false, 0, PI), snowMat);
    bank.rotation.x = PI / 2; bank.rotation.y = 0; bank.position.set(s * (half + 0.5), 0, -TRACK / 2 + 20); bank.scale.set(1, 1, 0.6); bank.receiveShadow = true; scene.add(bank);
  }
  scatter(rockGeo(7), new THREE.MeshStandardMaterial({ color: 0x6f747c, roughness: 1, flatShading: true }),
    sideItems(200, 2, 60, 42, ({ x, z, r }) => ({ x, z, y: 0.1, s: 0.3 + r() * 1.2, sy: 0.3 + r() * 0.5, ry: r() * 6 })), true);
  const mtnMat = new THREE.MeshStandardMaterial({ color: 0xd9e2ee, roughness: 0.9, flatShading: true });
  const r = rng(43);
  for (let k = 0; k < 18; k++) {
    const s = k % 2 ? 1 : -1, h = 120 + r() * 180, rad = 90 + r() * 120;
    const m = new THREE.Mesh(new THREE.ConeGeometry(rad, h, 7), mtnMat);
    m.position.set(s * (180 + r() * 300), h / 2 - 5, -r() * (TRACK + 700) + 150); m.rotation.y = r() * 6; scene.add(m);
  }
}

function buildCity() {
  const sideMat = new THREE.MeshStandardMaterial({ color: 0x8c8c90, roughness: 0.85 });
  for (const s of [-1, 1]) {        // sidewalks
    const sw = new THREE.Mesh(new THREE.BoxGeometry(5, 0.15, TRACK + 200), sideMat);
    sw.position.set(s * (half + 2.5), 0.075, -TRACK / 2 + 20); sw.receiveShadow = true; scene.add(sw);
  }
  const winTex = (seed, lit) => canvasTex(256, 512, (c, w, h) => {
    const r = rng(seed);
    c.fillStyle = lit ? '#000' : ['#5b6170', '#7a6a5e', '#4d5866', '#8a8f99'][seed % 4]; c.fillRect(0, 0, w, h);
    for (let y = 12; y < h; y += 32) for (let x = 10; x < w; x += 30) {
      const on = r() < (theme === 'night' ? 0.55 : 0.25);
      c.fillStyle = lit ? (on ? '#ffd98a' : '#000') : (on ? '#cfd8e6' : '#1d2430');
      c.fillRect(x, y, 18, 20);
    }
  });
  const r = rng(51);
  for (const s of [-1, 1]) for (let z = 40; z > -TRACK - 160;) {
    const wdt = 12 + r() * 14, d = 10 + r() * 14, h = 14 + r() * 55, sd = Math.floor(r() * 4) + 1;
    const geo = new THREE.BoxGeometry(d, h, wdt), uv = geo.attributes.uv;
    for (let k = 0; k < uv.count; k++) uv.setXY(k, uv.getX(k) * wdt / 8, uv.getY(k) * h / 14);
    const map = winTex(sd, false), em = winTex(sd, true);
    for (const t of [map, em]) { t.wrapS = t.wrapT = THREE.RepeatWrapping; }
    const b = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map, emissive: 0xffffff, emissiveMap: em, emissiveIntensity: theme === 'night' ? 1.4 : 0.15, roughness: 0.7 }));
    b.position.set(s * (half + 5.5 + d / 2), h / 2, z - wdt / 2); scene.add(b);
    z -= wdt + 1.5;
  }
  // street lamps
  const poleMat = new THREE.MeshStandardMaterial({ color: 0x2a2d33, metalness: 0.6, roughness: 0.4 });
  const headMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffe6b0, emissiveIntensity: theme === 'night' ? 5 : 0.3 });
  for (const s of [-1, 1]) for (let z = 10; z > -TRACK - 40; z -= 22) {
    const p = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.1, 6, 6), poleMat); p.position.set(s * (half + 4.7), 3, z); scene.add(p);
    const hd = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.18, 0.35), headMat); hd.position.set(s * (half + 4.2), 6, z); scene.add(hd);
  }
  // spectators behind barriers on the sidewalks
  const bodies = [], rr = rng(TL.seed + 5);
  for (const s of [-1, 1]) for (let row = 0; row < 2; row++) for (let z = 25; z > -TRACK - 20; z -= 0.75) {
    if (rr() < 0.3) { rr(); rr(); rr(); continue; }
    bodies.push({ x: s * (half + 1.6 + row * 0.8) + (rr() - 0.5) * 0.2, y: 0.15, z: z + (rr() - 0.5) * 0.3, c: SHIRTS[Math.floor(rr() * SHIRTS.length)], sk: SKINS[Math.floor(rr() * SKINS.length)], ph: rr() * 10, stand: true });
  }
  const barMat = new THREE.MeshStandardMaterial({ color: 0xc8ccd2, metalness: 0.7, roughness: 0.35 });
  for (const s of [-1, 1]) {
    const bar = new THREE.Mesh(new THREE.BoxGeometry(0.06, 1.0, TRACK + 60), barMat); bar.position.set(s * (half + 1.1), 0.65, -TRACK / 2 + 5); scene.add(bar);
  }
  makeCrowdMesh(bodies);
}

function buildForest() {
  const vc = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9, flatShading: true });
  const tree = merge([
    colorize(new THREE.CylinderGeometry(0.22, 0.32, 4, 7).translate(0, 2, 0), 0x5a3e28),
    colorize(new THREE.IcosahedronGeometry(1.9, 1).translate(0, 5.0, 0), 0x3f7f35),
    colorize(new THREE.IcosahedronGeometry(1.5, 1).translate(0.9, 4.2, 0.4), 0x4a8c3a),
    colorize(new THREE.IcosahedronGeometry(1.3, 1).translate(-0.8, 4.5, -0.5), 0x37702e),
  ]);
  const greens = [0xffffff, 0xd8f0c0, 0xc0e0a0, 0xffe8b0];
  scatter(tree, vc, sideItems(900, 7, 85, 61, ({ x, z, r }) => ({ x, z, s: 0.9 + r() * 0.9, ry: r() * 6, c: greens[Math.floor(r() * greens.length)] })), true);
  scatter(pineGeo(), vc, sideItems(300, 9, 95, 62, ({ x, z, r }) => ({ x, z, s: 1.2 + r(), ry: r() * 6, c: 0xffffff })), true);
  const bush = merge([colorize(new THREE.IcosahedronGeometry(0.7, 1), 0x3d7a30), colorize(new THREE.IcosahedronGeometry(0.5, 1).translate(0.5, 0, 0.2), 0x4a8a38)]);
  scatter(bush, vc, sideItems(500, 0.8, 30, 63, ({ x, z, r }) => ({ x, z, y: 0.3, s: 0.6 + r() * 0.8, ry: r() * 6, c: 0xffffff })));
  scatter(rockGeo(9), new THREE.MeshStandardMaterial({ color: 0x7c7a72, roughness: 1, flatShading: true }),
    sideItems(200, 1, 40, 64, ({ x, z, r }) => ({ x, z, y: 0.1, s: 0.2 + r() * 0.8, sy: 0.3 + r() * 0.4, ry: r() * 6 })), true);
}

function buildVolcano() {
  const lavaTex = canvasTex(512, 512, (c, w, h) => {
    c.fillStyle = '#ff6a10'; c.fillRect(0, 0, w, h);
    const r = rng(71);
    for (let k = 0; k < 260; k++) {
      const x = r() * w, y = r() * h, rad = 8 + r() * 40;
      const gr = c.createRadialGradient(x, y, 0, x, y, rad);
      gr.addColorStop(0, 'rgba(30,10,5,0.95)'); gr.addColorStop(0.7, 'rgba(60,15,5,0.6)'); gr.addColorStop(1, 'rgba(60,15,5,0)');
      c.fillStyle = gr; c.fillRect(x - rad, y - rad, rad * 2, rad * 2);
    }
    c.fillStyle = 'rgba(255,230,120,0.35)';
    for (let k = 0; k < 120; k++) c.fillRect(r() * w, r() * h, 2 + r() * 10, 30 + r() * 80);
  }, [4, 60]);
  const lavaMat = new THREE.MeshStandardMaterial({ color: 0x401005, emissive: 0xffffff, emissiveMap: lavaTex, emissiveIntensity: 1.6, roughness: 0.6 });
  for (const s of [-1, 1]) {
    const lava = new THREE.Mesh(new THREE.PlaneGeometry(14, TRACK + 300), lavaMat);
    lava.rotation.x = -PI / 2; lava.position.set(s * (half + 3 + 7), 0.02, -TRACK / 2); scene.add(lava);
  }
  worldAnim.push(vt => { lavaTex.offset.y = vt * 0.02; });
  const rockMat = new THREE.MeshStandardMaterial({ color: 0x24201e, roughness: 1, flatShading: true });
  scatter(rockGeo(5), rockMat, sideItems(260, 0.6, 2.6, 72, ({ x, z, r }) => ({ x, z, y: 0.1, s: 0.3 + r() * 0.6, sy: 0.3 + r() * 0.5, ry: r() * 6 })), true);
  scatter(rockGeo(6), rockMat, sideItems(300, 18, 120, 73, ({ x, z, r }) => ({ x, z, y: 0, s: 1 + r() * 5, sy: 1 + r() * 7, ry: r() * 6 })), true);
  const cone = new THREE.Mesh(new THREE.CylinderGeometry(40, 260, 200, 16, 1, true), new THREE.MeshStandardMaterial({ color: 0x2a2220, roughness: 1, flatShading: true }));
  cone.position.set(30, 95, -TRACK - 420); scene.add(cone);
  const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: puffTex(1), color: 0xff5010, blending: THREE.AdditiveBlending, depthWrite: false, fog: false }));
  glow.position.set(30, 200, -TRACK - 420); glow.scale.setScalar(220); scene.add(glow);
}

function updateCrowd(vt, excite, camZ, lookZ) {
  if (!crowd.body) return;
  // only spectators near what the camera sees are drawn (big speed-up in software rendering)
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), one = V(1, 1, 1), col = new THREE.Color();
  const zMin = Math.min(camZ, lookZ) - 110, zMax = Math.max(camZ, lookZ) + 12;
  let n = 0;
  for (const b of crowd.list) {
    if (b.z < zMin || b.z > zMax) continue;
    const jump = Math.max(0, Math.sin(vt * (7 + (b.ph % 3)) + b.ph)) * (0.06 + 0.22 * excite);
    const st = b.stand ? 1.75 : 1;
    m.compose(V(b.x, b.y + 0.42 * st + jump, b.z), q, V(1, st, 1)); crowd.body.setMatrixAt(n, m);
    m.compose(V(b.x, b.y + (b.stand ? 1.62 : 0.88) + jump, b.z), q, one); crowd.head.setMatrixAt(n, m);
    crowd.body.setColorAt(n, col.set(b.c)); crowd.head.setColorAt(n, col.set(b.sk));
    n++;
  }
  crowd.body.count = crowd.head.count = n;
  crowd.body.instanceMatrix.needsUpdate = crowd.head.instanceMatrix.needsUpdate = true;
  crowd.body.instanceColor.needsUpdate = crowd.head.instanceColor.needsUpdate = true;
}

// ------------------------------------------------------------------ runners
async function buildRunners() {
  if (CHAR !== 'person') {
    TL.runners.forEach((rr, i) => {
      const c = buildCharacter(CHAR, rr.color, envMap, envIntensity, TL.seed + i * 7);
      c.model.traverse(o => { if (o.isMesh) o.frustumCulled = false; });
      c.model.position.y = -CH.com;
      const pivot = new THREE.Group(); pivot.add(c.model);
      const holder = new THREE.Group(); holder.add(pivot); scene.add(holder);
      R.push({ holder, pivot, custom: c, mats: c.mats, base: new THREE.Color(c.tint ? 0xffffff : rr.color) });
    });
    return;
  }
  const gltf = await new GLTFLoader().loadAsync('/web/models/Xbot.glb');
  const clips = Object.fromEntries(gltf.animations.map(a => [a.name, a]));
  TL.runners.forEach((rr, i) => {
    const model = SkeletonUtils.clone(gltf.scene);
    const mats = [];
    model.traverse(o => {
      if (!o.isMesh) return;
      o.castShadow = true; o.receiveShadow = true; o.frustumCulled = false;
      const joint = /Joints/i.test(o.material.name);
      o.material = o.material.clone();
      if (joint) { o.material.color.set(0x1b1b20); o.material.roughness = 0.3; o.material.metalness = 0.7; }
      else { o.material.color.set(rr.color); o.material.roughness = 0.38; o.material.metalness = 0.05; mats.push(o.material); }
      o.material.envMap = envMap; o.material.envMapIntensity = envIntensity;
    });
    model.position.y = -CH.com;
    const pivot = new THREE.Group(); pivot.add(model);
    const holder = new THREE.Group(); holder.add(pivot); scene.add(holder);
    const mixer = new THREE.AnimationMixer(model);
    const acts = {};
    for (const nm of ['run', 'idle']) { const a = mixer.clipAction(clips[nm]); a.play(); acts[nm] = a; }
    R.push({ holder, pivot, mixer, acts, mats, base: new THREE.Color(rr.color), dur: { run: clips.run.duration, idle: clips.idle.duration } });
  });
}

function setPose(rr, wRun, runT, idleT) {
  rr.acts.run.setEffectiveWeight(wRun); rr.acts.idle.setEffectiveWeight(1 - wRun);
  rr.acts.run.time = ((runT % rr.dur.run) + rr.dur.run) % rr.dur.run;
  rr.acts.idle.time = ((idleT % rr.dur.idle) + rr.dur.idle) % rr.dur.idle;
  rr.mixer.update(0);
}

// body launched by a blast: analytic ballistic flight + one bounce, then lying still
function flight(P0, v0, dt, spins, seed) {
  const r = rng(seed);
  const restY = CH.restY;
  const T1 = (v0.y + Math.sqrt(v0.y * v0.y + 2 * G * (P0.y - restY))) / G;
  const finalPitch = CH.fall - 2 * PI * spins, roll = CH.fall === 0 ? 0 : (r() - 0.5) * 2.2;
  const pos = new THREE.Vector3(); let pitch, rl, flail;
  if (dt < T1) {
    pos.set(P0.x + v0.x * dt, P0.y + v0.y * dt - 0.5 * G * dt * dt, P0.z + v0.z * dt);
    pitch = finalPitch * (dt / T1); rl = roll * (dt / T1); flail = true;
  } else {
    const L = V(P0.x + v0.x * T1, restY, P0.z + v0.z * T1);
    const vy2 = Math.min(4, (G * T1 - v0.y) * 0.28), T2 = 2 * vy2 / G, d2 = dt - T1;
    const k = Math.min(d2, T2 + 0.6);
    const fr = 0.3 * (1 - Math.exp(-3 * k)) / 3 * 3;
    pos.set(L.x + v0.x * fr, restY + (d2 < T2 ? vy2 * d2 - 0.5 * G * d2 * d2 : 0), L.z + v0.z * fr);
    pitch = finalPitch + (d2 < T2 ? Math.sin(d2 / T2 * PI) * 0.4 : 0); rl = roll; flail = d2 < T2;
  }
  return { pos, pitch, roll: rl, flail };
}

function runnerState(i, t, f) {
  const lx = laneX(i);
  const kill = killOf[i];
  const st = { pos: V(lx, CH.com, 0), pitch: 0, roll: 0, yaw: PI, wRun: 0, runT: 0, idleT: f / FPS + i * 0.7, visible: true, char: 0, glow: 0, dist: 0 };
  const runDur = R[i].dur ? R[i].dur.run : 1;
  if (kill && t >= kill.t) {
    const dt = t - kill.t, P0 = V(lx, CH.com, -kill.x), seed = TL.seed * 31 + i;
    st.wRun = 1; st.runT = kill.x / CYCLE_M * runDur;
    st.dead = true; st.kind = kill.kind; st.deadDt = dt; st.dist = kill.x;
    const side = (rng(seed)() - 0.5) * 2;
    let fl = null;
    if (kill.kind === 'METEOR') { fl = flight(P0, V(side * 2.5, 11, 3.5), dt, 1, seed); st.char = Math.min(1, dt * 4) * 0.75; }
    else if (kill.kind === 'MINE') { fl = flight(P0, V(side * 1.5, 14, -1.5), dt, 2, seed); st.char = Math.min(1, dt * 4) * 0.7; }
    else if (kill.kind === 'BOULDER') { fl = flight(P0, V(side * 1.2, 6.5, 11), dt, 1, seed); }
    if (fl) {
      st.pos.copy(fl.pos); st.pitch = fl.pitch; st.roll = fl.roll;
      st.wRun = fl.flail ? 1 : 0; st.runT = dt * 2.6; st.idleT = 0.3; st.flail = fl.flail;
    } else if (kill.kind === 'LIGHTNING') {
      st.char = dt < 0.5 ? 0.3 : 1;
      st.glow = dt < 0.5 ? (Math.sin(dt * 90) > 0 ? 1 : 0.2) : 0;
      if (dt < 0.5) { st.roll = Math.sin(dt * 77) * 0.12; st.pitch = Math.sin(dt * 63) * 0.1; st.wRun = 1; st.runT = dt * 0.2; }
      else {
        const p = clamp((dt - 0.5) / 0.55, 0, 1), e = p * p;
        st.pitch = CH.fall * e; st.pos.y = lerp(CH.com, CH.restY, e); st.pos.z += 0.9 * e; st.wRun = 0.4; st.runT = 0.1;
      }
    } else if (kill.kind === 'PIT') {
      st.pos.y = CH.com - 0.5 * G * dt * dt; st.pos.z -= Math.min(dt, 0.25) * 4;
      st.pitch = Math.min(dt, 0.6) * 0.8; st.wRun = 1; st.runT = dt * 3;
      if (st.pos.y < -3) st.visible = false;
    }
    return st;
  }
  const x = xAt(i, t), v = vAt(i, t);
  st.pos.z = -x; st.dist = x;
  if (t > 0) {
    st.wRun = clamp(v / 2.5, 0, 1);
    st.runT = x / CYCLE_M * runDur;
    st.pitch = 0.1 * clamp(v / 9, 0, 1);
    const tripE = events.find(e => e.type === 'trip' && e.who === i && t >= e.t && t < e.t + 0.9);
    for (const h of TL.hurdles) {
      const d = x - h;
      if (Math.abs(d) < 1.3 && !(tripE && Math.abs(tripE.x - h) < 0.1)) st.pos.y += 0.62 * (1 - (d / 1.3) ** 2);
    }
    if (tripE) { const p = (t - tripE.t) / 0.9, s = Math.sin(p * PI); st.pitch += s * 1.0; st.pos.y -= s * 0.45; }
    const miss = events.find(e => e.type === 'miss' && e.who === i && t >= e.t && t < e.t + 0.7);
    if (miss) { const s = Math.sin((t - miss.t) / 0.7 * PI); st.roll = -miss.side * s * 0.5; st.pos.x -= miss.side * s * 0.35; }
  }
  // winner celebration in outro
  if (i === TL.winner && f >= TL.raceEndFrame) {
    const lt = (f - TL.raceEndFrame) / FPS;
    st.wRun = 0; st.pitch = 0; st.idleT = lt;
    st.pos.y = CH.com + Math.abs(Math.sin(lt * 4.2)) * 0.55;
    st.celebrate = true;
  }
  return st;
}

function applyRunner(i, st, camPos) {
  const rr = R[i];
  rr.holder.visible = st.visible;
  rr.holder.position.copy(st.pos);
  rr.holder.rotation.set(0, st.celebrate ? Math.atan2(camPos.x - st.pos.x, camPos.z - st.pos.z) : st.yaw, 0);
  rr.pivot.rotation.set(st.pitch, 0, st.roll);
  const c = rr.base.clone().lerp(new THREE.Color(0x0d0d0d), st.char);
  for (const m of rr.mats) { m.color.copy(c); m.emissive.setRGB(0.5 * st.glow, 0.7 * st.glow, 1.0 * st.glow); }
  if (rr.custom) rr.custom.animate(st, curVt); else setPose(rr, st.wRun, st.runT, st.idleT);
}

// ------------------------------------------------------------------ hazard effects (one object per event)
function bolt(seed, from, to, segs = 16) {
  const r = rng(seed), pts = [];
  for (let k = 0; k <= segs; k++) {
    const p = from.clone().lerp(to, k / segs);
    if (k > 0 && k < segs) { const j = 1.8 * (1 - k / segs) + 0.25; p.x += (r() - 0.5) * j * 2; p.z += (r() - 0.5) * j * 2; }
    pts.push(p);
  }
  return pts;
}
function tubeOf(points, radius, mat) {
  const grp = new THREE.Group();
  for (let k = 0; k < points.length - 1; k++) {
    const a = points[k], b = points[k + 1], len = a.distanceTo(b);
    const m = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, len, 6), mat);
    m.position.copy(a).lerp(b, 0.5);
    m.quaternion.setFromUnitVectors(V(0, 1, 0), b.clone().sub(a).normalize());
    grp.add(m);
  }
  return grp;
}

function buildEffects() {
  const fireGlow = new THREE.SpriteMaterial({ map: puffTex(1), color: 0xff7a20, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true });
  const craterTex = canvasTex(256, 256, (c) => {
    const gr = c.createRadialGradient(128, 128, 0, 128, 128, 128);
    gr.addColorStop(0, 'rgba(15,10,8,1)'); gr.addColorStop(0.55, 'rgba(30,20,15,0.9)'); gr.addColorStop(1, 'rgba(30,20,15,0)');
    c.fillStyle = gr; c.fillRect(0, 0, 256, 256);
  });
  const craterMat = new THREE.MeshStandardMaterial({ map: craterTex, transparent: true, depthWrite: false, roughness: 1, polygonOffset: true, polygonOffsetFactor: -2 });
  const ringMat = () => new THREE.MeshBasicMaterial({ color: 0xffc080, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide });
  const warnMat = () => new THREE.MeshBasicMaterial({ color: 0xff2020, transparent: true, depthWrite: false, side: THREE.DoubleSide });
  const rockMat = new THREE.MeshStandardMaterial({ color: 0x6d6259, roughness: 1, flatShading: true });
  const meteorMat = new THREE.MeshStandardMaterial({ color: 0x2a160c, emissive: 0xff5a10, emissiveIntensity: 2.5, roughness: 1, flatShading: true });
  const boltCore = new THREE.MeshBasicMaterial({ color: 0xffffff });
  const boltGlow = new THREE.MeshBasicMaterial({ color: 0x8fb4ff, transparent: true, opacity: 0.35, blending: THREE.AdditiveBlending, depthWrite: false });
  const WARN = TL.warn;

  events.forEach((e, ei) => {
    const seed = TL.seed * 1000 + ei * 17;
    const lx = laneX(e.who);
    if (e.type === 'kill' || e.type === 'miss') {
      const kind = e.kind;
      let I;
      if (e.type === 'kill') I = V(lx, 0, -e.x);
      else { const xm = xAt(e.who, e.t) + 2.2; I = V(lx + e.side * (LANE_W * 0.55), 0, -xm); }
      const fx = { e, I, kind, seed, objs: [] };
      const add = o => { o.visible = false; scene.add(o); fx.objs.push(o); return o; };
      if (kind === 'METEOR' || kind === 'MINE') {
        fx.crater = add(new THREE.Mesh(new THREE.CircleGeometry(kind === 'METEOR' ? 1.8 : 1.3, 32), craterMat));
        fx.crater.rotation.x = -PI / 2; fx.crater.position.set(I.x, 0.015, I.z);
        fx.ring = add(new THREE.Mesh(new THREE.RingGeometry(0.85, 1, 48), ringMat()));
        fx.ring.rotation.x = -PI / 2; fx.ring.position.set(I.x, 0.06, I.z);
        fx.debris = Array.from({ length: 24 }, (_, k) => { const r = rng(seed + k); return { v: V((r() - 0.5) * 12, 5 + r() * 11, (r() - 0.5) * 12), s: 0.5 + r() * 1.4, w: r() * 20 }; });
      }
      if (kind === 'METEOR') {
        const geo = new THREE.IcosahedronGeometry(0.75, 1);
        fx.rock = add(new THREE.Mesh(geo, meteorMat));
        fx.glow = add(new THREE.Sprite(fireGlow)); fx.glow.scale.setScalar(5);
        fx.from = I.clone().add(V(14, 70, -45));
        fx.target = add(new THREE.Mesh(new THREE.RingGeometry(0.9, 1.15, 40), warnMat()));
        fx.target.rotation.x = -PI / 2; fx.target.position.set(I.x, 0.03, I.z);
      }
      if (kind === 'MINE') {
        fx.mine = add(new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.32, 0.09, 16), new THREE.MeshStandardMaterial({ color: 0x3d4a2f, metalness: 0.6, roughness: 0.5 })));
        fx.mine.position.set(I.x, 0.045, I.z);
        fx.led = add(new THREE.Mesh(new THREE.SphereGeometry(0.07, 8, 8), new THREE.MeshBasicMaterial({ color: 0xff1010 })));
        fx.led.position.set(I.x, 0.11, I.z);
        fx.ledGlow = add(new THREE.Sprite(new THREE.SpriteMaterial({ map: puffTex(1), color: 0xff2020, blending: THREE.AdditiveBlending, depthWrite: false })));
        fx.ledGlow.position.copy(fx.led.position); fx.ledGlow.scale.setScalar(0.9);
      }
      if (kind === 'LIGHTNING') {
        const top = V(lx + 6, 48, I.z - 14), head = V(lx, 1.8, I.z - 0.1);
        const main = bolt(seed, top, head);
        fx.bolt = add(new THREE.Group());
        fx.bolt.add(tubeOf(main, 0.05, boltCore), tubeOf(main, 0.28, boltGlow));
        for (let b = 0; b < 3; b++) {
          const st = main[4 + b * 3], br = bolt(seed + b + 1, st, st.clone().add(V((b - 1) * 5, -9, 3)), 6);
          fx.bolt.add(tubeOf(br, 0.03, boltCore), tubeOf(br, 0.15, boltGlow));
        }
        fx.crater = add(new THREE.Mesh(new THREE.CircleGeometry(1.0, 32), craterMat));
        fx.crater.rotation.x = -PI / 2; fx.crater.position.set(I.x, 0.015, I.z);
      }
      if (kind === 'PIT') {
        fx.hole = add(new THREE.Mesh(new THREE.PlaneGeometry(LANE_W * 0.9, 1.7), new THREE.MeshBasicMaterial({ color: 0x050505 })));
        fx.hole.rotation.x = -PI / 2; fx.hole.position.set(I.x, 0.008, I.z - 0.3);
        const flapMat = new THREE.MeshStandardMaterial({ color: WORLD.pit, roughness: 0.9 });
        fx.flaps = [-1, 1].map(s => {
          const hinge = add(new THREE.Group()); hinge.position.set(I.x + s * LANE_W * 0.45, 0.01, I.z - 0.3);
          const flap = new THREE.Mesh(new THREE.BoxGeometry(LANE_W * 0.45, 0.04, 1.7), flapMat); flap.position.x = -s * LANE_W * 0.225; hinge.add(flap);
          hinge.userData.s = s; return hinge;
        });
        const stripe = canvasTex(64, 64, (c) => { for (let k = -64; k < 128; k += 16) { c.fillStyle = '#ffcc00'; c.beginPath(); c.moveTo(k, 0); c.lineTo(k + 8, 0); c.lineTo(k + 72, 64); c.lineTo(k + 64, 64); c.fill(); } });
        fx.frame = add(new THREE.Mesh(new THREE.PlaneGeometry(LANE_W * 0.98, 1.85), new THREE.MeshBasicMaterial({ map: stripe, transparent: true, depthWrite: false })));
        fx.frame.rotation.x = -PI / 2; fx.frame.position.set(I.x, 0.006, I.z - 0.3);
      }
      if (kind === 'BOULDER') {
        const geo = new THREE.IcosahedronGeometry(1.35, 3), p = geo.attributes.position, r = rng(seed);
        const bumps = Array.from({ length: 7 }, () => V(r() - 0.5, r() - 0.5, r() - 0.5).normalize());
        for (let k = 0; k < p.count; k++) {
          const v = V(p.getX(k), p.getY(k), p.getZ(k)), n = v.clone().normalize();
          let d = 1; for (const b of bumps) d += 0.12 * Math.max(0, n.dot(b)) ** 3;
          v.multiplyScalar(d * (0.94 + 0.06 * Math.sin(v.x * 7) * Math.cos(v.z * 6))); p.setXYZ(k, v.x, v.y, v.z);
        }
        geo.computeVertexNormals();
        fx.boulder = add(new THREE.Mesh(geo, rockMat)); fx.boulder.castShadow = true;
      }
      FX.push(fx);
    }
  });
}

function updateEffects(t, vt) {
  const WARN = TL.warn;
  let shake = 0, flash = 0;
  const lightSrc = [];
  const d = new THREE.Matrix4(), q = new THREE.Quaternion(), e3 = new THREE.Euler();
  let dCount = 0;
  for (const fx of FX) {
    const te = fx.e.t, dt = t - te, I = fx.I, kind = fx.kind;
    fx.objs.forEach(o => (o.visible = false));
    if (kind === 'METEOR' || kind === 'MINE') {
      if (dt >= 0) {
        fx.crater.visible = true;
        explosionFX(I, te, t, fx.seed, kind === 'METEOR' ? 1.15 : 0.95);
        if (dt < 0.6) { fx.ring.visible = true; const s = 1 + 16 * smooth(dt / 0.6); fx.ring.scale.set(s, s, s); fx.ring.material.opacity = 0.9 * (1 - dt / 0.6); }
        shake += 0.55 * Math.exp(-dt * 3.5); flash += 0.9 * Math.exp(-dt * 7);
        if (dt < 1.5) lightSrc.push({ p: I.clone().add(V(0, 2.5, 0)), i: 900 * Math.exp(-dt * 3.5), c: 0xff8a30 });
        for (const db of fx.debris) {
          if (dCount >= 400) break;
          const Tl = (db.v.y + Math.sqrt(db.v.y ** 2 + 2 * 9.8 * 0.3)) / 9.8, tt = Math.min(dt, Tl);
          const pos = V(I.x + db.v.x * tt, Math.max(0.06, 0.3 + db.v.y * tt - 4.9 * tt * tt), I.z + db.v.z * tt);
          e3.set(db.w * tt, db.w * 0.7 * tt, 0); q.setFromEuler(e3);
          d.compose(pos, q, V(db.s, db.s, db.s)); debris.setMatrixAt(dCount++, d);
        }
      } else if (dt > -WARN) {
        const p = (dt + WARN) / WARN;
        if (kind === 'METEOR') {
          const pos = fx.from.clone().lerp(I, Math.pow(p, 1.7));
          fx.rock.visible = fx.glow.visible = fx.target.visible = true;
          fx.rock.position.copy(pos); fx.rock.rotation.set(t * 5, t * 3, 0); fx.glow.position.copy(pos);
          fx.target.material.opacity = 0.5 + 0.5 * Math.sin(t * 25);
          const s = 0.8 + 0.4 * p; fx.target.scale.set(s, s, s);
          const r = rng(fx.seed + 5);
          for (let k = 0; k < 70; k++) {                  // fiery trail
            const lag = k * 0.012, pp = (dt + WARN - lag) / WARN; if (pp < 0) break;
            const tp = fx.from.clone().lerp(I, Math.pow(pp, 1.7));
            const a = 1 - k / 70;
            P.fire.push(tp.x + (r() - 0.5) * 0.6, tp.y + (r() - 0.5) * 0.6, tp.z + (r() - 0.5) * 0.6, 1.6 * a + 0.4, 3, 1.3 * a + 0.2, 0.3 * a, a);
            if (k % 3 === 0) P.smoke.push(tp.x, tp.y + 0.5, tp.z, 2.2 * (1 - a) + 0.8, 0.15, 0.14, 0.13, 0.5 * a);
          }
          lightSrc.push({ p: pos, i: 300, c: 0xff7a20 });
        } else {
          fx.mine.visible = fx.led.visible = true;
          const blink = Math.sin((dt + WARN) * (10 + 25 * p)) > 0;
          fx.ledGlow.visible = blink;
        }
      }
    } else if (kind === 'LIGHTNING') {
      if (dt > -WARN && dt < 3) {   // storm cloud gathering above victim
        const r = rng(fx.seed + 2), dens = dt < 0 ? (dt + WARN) / WARN : Math.max(0, 1 - dt / 3);
        for (let k = 0; k < 45; k++) {
          const ox = (r() - 0.5) * 16, oz = (r() - 0.5) * 16, oy = 14 + r() * 5, sz = 5 + r() * 6;
          P.smoke.push(I.x + ox + Math.sin(t + k) * 0.5, oy, I.z + oz - 6, sz, 0.08, 0.08, 0.1, 0.85 * dens);
        }
        if (dt < 0 && Math.sin(dt * 47) > 0.92) flash += 0.25;
      }
      if (dt >= 0) {
        fx.crater.visible = true;
        const on = dt < 0.4 && Math.floor(dt * 30) % 3 !== 2;
        fx.bolt.visible = on;
        if (on) { flash += 3.0; lightSrc.push({ p: I.clone().add(V(0, 3, 0)), i: 2500, c: 0xbad0ff }); }
        shake += 0.35 * Math.exp(-dt * 4);
        const r = rng(fx.seed + 9);
        for (let k = 0; k < 40; k++) {                 // sparks
          const life = 0.4 + r() * 0.8, th = r() * 2 * PI, sp = 3 + r() * 6, up = 0.4 + r() * 0.6;
          if (dt > life) continue;
          P.fire.push(I.x + Math.cos(th) * sp * dt, 0.3 + up * sp * dt - 4.9 * dt * dt, I.z + Math.sin(th) * sp * dt, 0.12, 2.5, 2.8, 3, 1 - dt / life);
        }
        if (dt < 5) {                                    // smoke from the body
          const st = runnerState(fx.e.who, t, 0);
          for (let k = 0; k < 14; k++) { const a = ((dt * 0.7 + k / 14) % 1); P.smoke.push(st.pos.x + Math.sin(k * 3) * 0.3, st.pos.y + 0.2 + a * 3, st.pos.z, 0.5 + a * 1.6, 0.25, 0.25, 0.27, 0.45 * (1 - a) * Math.max(0, 1 - dt / 5)); }
        }
      }
    } else if (kind === 'PIT') {
      if (dt > -WARN) { fx.frame.visible = dt < 0.1; fx.frame.material.opacity = 0.4 + 0.4 * Math.sin(t * 20); }
      if (dt >= -0.05) {
        fx.hole.visible = true;
        const o = smooth((dt + 0.05) / 0.2);
        fx.flaps.forEach(h => { h.visible = true; h.rotation.z = h.userData.s * o * 1.6; });
        dustFX(I.clone().add(V(0, 0, -0.3)), te + 0.05, t, fx.seed, 30, 2.5);
        shake += 0.12 * Math.exp(-Math.max(0, dt) * 5);
      }
    } else if (kind === 'BOULDER') {
      const spawn = te - WARN - 0.35, BV = 13;
      if (t >= spawn && dt < 3.5) {
        fx.boulder.visible = true;
        const z = I.z - 1.2 + BV * (t - te);                // rolls toward +Z, through the victim
        const drop = clamp((t - spawn) / 0.4, 0, 1), y = 1.35 + (1 - drop) * 9 + (drop < 1 ? 0 : Math.abs(Math.sin((t - spawn) * 6)) * 0.25 * Math.exp(-(t - spawn) * 2));
        fx.boulder.position.set(I.x, y, z);
        fx.boulder.rotation.set((z - I.z) / 1.35, 0, 0);
        const r = rng(fx.seed + 3);
        for (let k = 0; k < 14; k++) {                     // dust trail
          const a = r(); const zz = z - a * 6;
          P.smoke.push(I.x + (r() - 0.5) * 2, 0.3 + a * 1.2, zz, 1 + a * 2, 0.55, 0.45, 0.36, 0.45 * (1 - a));
        }
        shake += 0.1;
      }
      if (dt >= 0) { dustFX(V(I.x, 0.5, I.z), te, t, fx.seed, 30, 3); shake += 0.4 * Math.exp(-dt * 4); }
    }
  }
  for (let k = dCount; k < 400; k++) { d.makeScale(0, 0, 0); debris.setMatrixAt(k, d); }
  debris.instanceMatrix.needsUpdate = true;
  lightSrc.sort((a, b) => b.i - a.i);
  lights.forEach((l, k) => {
    const s = lightSrc[k];
    l.intensity = s ? s.i : 0;
    if (s) { l.position.copy(s.p); l.color.set(s.c); }
  });
  return { shake, flash };
}

function updateMiscParticles(t, f, states) {
  // footstep dust
  for (let i = 0; i < N; i++) {
    const st = states[i];
    if (!st.visible || t <= 0 || (killOf[i] && t >= killOf[i].t)) continue;
    const x = xAt(i, t), v = Math.max(1, vAt(i, t)), stepLen = CYCLE_M / 2;
    for (let k = 0; k < 4; k++) {
      const xs = Math.floor(x / stepLen - k) * stepLen; if (xs <= 0) break;
      const age = (x - xs) / v, a = age / 0.9; if (a > 1) continue;
      const dc = WORLD.dust;
      if (CHAR === 'car') { P.smoke.push(laneX(i) + 0.3, 0.3 + 0.5 * a, -xs + 1.0 + a * 0.8, 0.3 + 0.8 * a, 0.7, 0.7, 0.72, 0.35 * (1 - a)); continue; }
      P.smoke.push(laneX(i) + ((Math.floor(xs / stepLen) % 2) ? 0.12 : -0.12), 0.08 + 0.3 * a, -xs, 0.35 + 0.9 * a, dc[0], dc[1], dc[2], (TL.world === 'snow' ? 0.5 : 0.3) * (1 - a));
    }
  }
  // boost trail
  for (const e of events) {
    if (e.type !== 'boost' || t < e.t || t > e.t + 1.6) continue;
    const i = e.who; if (killOf[i] && t >= killOf[i].t) continue;
    const x = xAt(i, t), r = rng(e.t * 100 | 0);
    for (let k = 0; k < 40; k++) {
      const back = r() * 3.5, a = back / 3.5;
      P.fire.push(laneX(i) + (r() - 0.5) * 0.5, 0.2 + r() * 1.5, -(x - back), 0.35 * (1 - a) + 0.1, 0.4, 1.5, 3.0, 0.9 * (1 - a));
    }
  }
  // ambient weather: snowfall / volcanic embers / desert dust, around the camera
  if (TL.world === 'snow' || TL.world === 'volcano' || TL.world === 'desert') {
    const r = rng(1234), vt = f / FPS, cp = camera.position, BX = 30, BY = 16, BZ = 45;
    const n = TL.world === 'snow' ? 900 : TL.world === 'volcano' ? 350 : 120;
    for (let k = 0; k < n; k++) {
      const ox = r() * BX, oy = r() * BY, oz = r() * BZ, sp = 0.6 + r(), ph = r() * 6;
      let x, y, z;
      if (TL.world === 'snow') { y = ((oy - vt * 1.3 * sp) % BY + BY) % BY; x = ox + Math.sin(vt * 0.8 + ph) * 0.6; z = oz; }
      else if (TL.world === 'volcano') { y = ((oy + vt * 1.6 * sp) % BY + BY) % BY; x = ox + Math.sin(vt + ph); z = oz; }
      else { y = oy * 0.15; x = ((ox + vt * 6 * sp) % BX + BX) % BX; z = oz; }
      const wx = cp.x - BX / 2 + x, wy = Math.max(0.05, cp.y - 4 + y), wz = cp.z - BZ * 0.8 + z;
      if (TL.world === 'snow') P.flake.push(wx, wy, wz, 0.07 + 0.05 * sp, 1, 1, 1, 0.9);
      else if (TL.world === 'volcano') P.fire.push(wx, wy, wz, 0.08, 3, 1.1, 0.25, 0.4 + 0.6 * Math.abs(Math.sin(vt * 3 + ph)));
      else P.smoke.push(wx, wy, wz, 1.5, 0.85, 0.72, 0.52, 0.12);
    }
  }
  if (TL.world === 'volcano') {      // smoke plume from the volcano
    const r = rng(77), vt = f / FPS;
    for (let k = 0; k < 40; k++) { const a = ((vt * 0.05 + k / 40) % 1); P.smoke.push(30 + Math.sin(k) * 20 * a, 200 + a * 260, -TRACK - 420 - a * 80, 60 + a * 160, 0.12, 0.1, 0.1, 0.7 * (1 - a)); }
  }
  // confetti over winner in outro
  if (f >= TL.raceEndFrame) {
    const lt = (f - TL.raceEndFrame) / FPS, w = states[TL.winner].pos, r = rng(99);
    const cols = TL.runners.map(x => new THREE.Color(x.color));
    for (let k = 0; k < 500; k++) {
      const ox = (r() - 0.5) * 12, oz = (r() - 0.5) * 12, y0 = 6 + r() * 10, sp = 1.2 + r() * 1.5, ph = r() * 6;
      const y = y0 - sp * lt; if (y < 0) continue;
      const c = cols[k % cols.length];
      P.conf.push(w.x + ox + Math.sin(lt * 2 + ph) * 0.6, y, w.z + oz + Math.cos(lt * 1.7 + ph) * 0.6, 0.12, c.r, c.g, c.b, 1);
    }
  }
}

// ------------------------------------------------------------------ camera
function shotAt(f) { return TL.shots.find(s => f >= s.f0 && f < s.f1) || TL.shots[TL.shots.length - 1]; }

function cameraFor(f, t, states) {
  const s = shotAt(f), lt = (f - s.f0) / FPS, ln = (s.f1 - s.f0) / FPS;
  const lead = TL.lead[f], tail = TL.tail[f], mid = (lead + tail) / 2;
  let pos, look, fov = 50;
  switch (s.type) {
    case 'lineup': pos = V(lerp(-2, 2, lt / ln), 2.0, -12); look = V(0, 1.0, 0); fov = 58; break;
    case 'lineup2': pos = V(0, 2.4, -14 + lt * 1.5); look = V(0, 1.0, 0); fov = 54; break;
    case 'close': { const lx = laneX(s.who), ey = CH.eye; pos = V(lx + 0.35, ey + 0.2, -(CHAR === 'person' ? 2.7 : 2.9) + lt * 0.5); look = V(lx, ey - (CHAR === 'person' ? 0.05 : 0.3), 0); fov = 38; break; }
    // ---- original cinematic cameras
    case 'start_cine': pos = V(half * 0.25, 0.5, -(7.5 + 0.6 * Math.max(0, lead))); look = V(0, 1.0, -Math.max(0, lead) * 0.6); fov = 62; break;
    case 'chase': pos = V(Math.sin(lt * 0.5) * 1.5, 5 + (lead - tail) * 0.1, -(tail - 7)); look = V(0, 0.6, -(lead + 7)); fov = 52; break;
    case 'front': pos = V(Math.cos(lt * 0.6) * 1.5, 1.6, -(lead + 10)); look = V(0, 1.1, -mid); fov = 42; break;
    case 'side': pos = V(-(half + 3.2), 2.8, -(mid - 4)); look = V(0.5, 1.0, -(mid + 1.5)); fov = 50; break;
    case 'drone': pos = V(half * 0.5, 22 - lt, -(mid - 10)); look = V(0, 0, -(mid + 4)); fov = 50; break;
    case 'finish_cine': pos = V(-(half + 2.6), 1.3, -(TRACK + 6)); look = V(0, 1.1, -(TRACK - 5)); fov = 46; break;
    case 'kill_cine': {
      const i = s.who, lx = laneX(i), k = killOf[i], xk = k.x, body = states[i].pos.clone(), dt = t - k.t, ey = CH.eye;
      if (s.kind === 'METEOR') {
        pos = V(lx - 4.8, 1.1, -(xk - 6));
        const fx = FX.find(q => q.e === k);
        const mp = dt < 0 ? fx.from.clone().lerp(fx.I, Math.pow(clamp((dt + TL.warn) / TL.warn, 0, 1), 1.7)) : body;
        look = dt < 0 ? V(lx, 1.5, -xk).lerp(mp, 0.3) : body.clone().lerp(V(lx, 2, -xk), 0.3);
        fov = 58;
      } else if (s.kind === 'MINE') { pos = V(lx + 3.4, 1.3, -(xk + 5)); look = body.clone().add(V(0, 0.4, 0)); fov = 50; }
      else if (s.kind === 'LIGHTNING') { pos = V(lx - 3.8, 1.2, -(xk + 3.4)); look = body.clone().add(V(0, ey * 0.6 + (dt > -0.3 && dt < 0.6 ? 0.6 : 0), 0)); fov = 50; }
      else if (s.kind === 'PIT') { pos = V(lx - 2.4, 2.6, -(xk + 3.8)); look = V(lx, 0.6, -(Math.max(xk - 2, Math.min(xk, -body.z)))); fov = 46; }
      else { pos = V(lx + 1.8, 2.6, -(xk - 9) + Math.max(0, dt) * 6); look = dt < 0 ? V(lx, 1.2, -(xk + 6)) : body; fov = 56; }
      pos.add(look.clone().sub(pos).normalize().multiplyScalar(lt * 0.4));
      break;
    }
    // ---- endless-runner style cameras: behind the racers, looking down the track
    case 'start': { const tl0 = Math.max(0, tail); pos = V(0, CH.eye + 1.5, -(tl0 - 5.5)); look = V(0, CH.eye * 0.6, -(tl0 + 14)); fov = 66; break; }
    case 'pack': pos = V(Math.sin(vtNow * 0.9) * 0.6, CH.eye + 2.2 + (lead - tail) * 0.04, -(tail - 6.5)); look = V(0, CH.eye * 0.5, -(tail + 14)); fov = 70; break;
    case 'hero': case 'hero_high': case 'finish': {
      const i = s.who, lx = laneX(i), xi = Math.min(xAt(i, t), TRACK + (s.type === 'finish' ? 1.5 : 50));
      const hi = s.type === 'hero_high', bob = Math.sin(vtNow * 9) * 0.03, sway = Math.sin(vtNow * 0.8) * 0.25;
      pos = V(lx * 0.7 + sway, CH.eye + (hi ? 3.6 : 1.3) + bob, -(xi - (hi ? 6.5 : 4.0)));
      look = V(lx * 0.8, CH.eye * (hi ? 0.3 : 0.7), -(xi + (hi ? 9 : 8)));
      fov = hi ? 64 : 60; break;
    }
    case 'kill': {
      const i = s.who, lx = laneX(i), k = killOf[i], xk = k.x, body = states[i].pos.clone(), dt = t - k.t;
      // chase cam right behind the victim; the hazard comes at them from ahead, then the camera holds
      const xv = dt < 0 ? xAt(i, t) : xk;
      const back = s.kind === 'BOULDER' ? 6.5 + Math.max(0, dt) * 13 : s.kind === 'METEOR' || s.kind === 'MINE' ? 5.0 + Math.max(0, dt) * 2.5 : 4.2;
      const up = s.kind === 'METEOR' ? 1.6 : s.kind === 'BOULDER' ? 2.0 + Math.max(0, dt) * 1.5 : 1.4;
      pos = V(lx * 0.8 + 0.35, CH.eye + up, -(xv - back));
      if (s.kind === 'METEOR' && dt < 0) {
        const fx = FX.find(q => q.e === k);
        const mp = fx.from.clone().lerp(fx.I, Math.pow(clamp((dt + TL.warn) / TL.warn, 0, 1), 1.7));
        look = V(lx, CH.eye * 0.6, -(xv + 8)).lerp(mp, 0.25);
      } else if (dt < 0) look = V(lx, CH.eye * 0.6, -(xv + 8));
      else look = body.clone().lerp(V(lx, CH.eye * 0.6, -(xk + 6)), s.kind === 'PIT' ? 0.4 : 0.15);
      look.z = Math.min(look.z, pos.z - 3);          // always keep looking down the track
      fov = s.kind === 'METEOR' ? 66 : 60;
      break;
    }
    case 'outro': {
      const w = states[TL.winner].pos, a = 0.5 + lt * 0.5, small = CHAR !== 'person', rad = small ? 3.4 : 4.2;
      pos = V(w.x + Math.sin(a) * rad, small ? 1.3 : 1.7, w.z - Math.cos(a) * rad); look = V(w.x, small ? 1.05 : 1.4, w.z); fov = 44; break;
    }
  }
  const clear = { stadium: 3.4, city: 1.0 }[TL.world] ?? 5.5;   // never put the camera inside stands / crowd / trees
  if (s.type !== 'drone') pos.x = clamp(pos.x, -(half + clear), half + clear);
  return { pos, look, fov, shot: s, lt };
}

// ------------------------------------------------------------------ HUD
function txt(s, x, y, size, fill, o = {}) {
  g.font = `${size}px Race`; g.textAlign = o.align || 'center'; g.textBaseline = 'middle'; g.lineJoin = 'round';
  const sw = o.stroke ?? size * 0.16;
  if (sw > 0) { g.lineWidth = sw; g.strokeStyle = o.sc || '#090910'; g.strokeText(s, x, y); }
  g.fillStyle = fill; g.fillText(s, x, y);
}
const KILL_WARN = { METEOR: 'METEOR INCOMING!', MINE: 'LANDMINE!', LIGHTNING: 'STORM OVERHEAD!', PIT: 'TRAPDOOR!', BOULDER: 'BOULDER!' };

function drawHUD(f, t, cam) {
  const s = cam.shot, vt = f / FPS;
  // cinematic vignette
  const vg = g.createRadialGradient(W / 2, H / 2, H * 0.3, W / 2, H / 2, H * 0.75);
  vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(0,0,0,0.55)');
  g.fillStyle = vg; g.fillRect(0, 0, W, H);
  const names = TL.runners;
  if (f < TL.introFrames) {
    const p = 1 + 0.05 * Math.sin(vt * 7);
    txt('PICK YOUR', W / 2, 190, Math.round(96 * p), '#ffffff');
    txt('COLOR!', W / 2, 310, Math.round(130 * p), '#ffd12e');
    g.fillStyle = 'rgba(0,0,0,0.5)'; g.beginPath(); g.roundRect(W / 2 - 380, 382, 760, 70, 35); g.fill();
    txt(`${WORLD.title}  ·  ${CH.title}`, W / 2, 418, 42, '#ffffff', { stroke: 0 });
    if (s.type === 'close') {
      const r = names[s.who], pop = Math.min(1, cam.lt / 0.12);
      g.fillStyle = 'rgba(0,0,0,0.45)'; g.fillRect(0, 1240, W, 240);
      txt(r.name, W / 2, 1335, Math.round(170 * pop), r.color, { stroke: 18 });
      txt(`RUNNER ${s.who + 1} OF ${N}`, W / 2, 1440, 44, '#ffffff', { stroke: 8 });
    } else {
      txt(s.type === 'lineup2' ? 'LAST CHANCE TO PICK!' : 'Comment before the race starts!', W / 2, 1420, 56, s.type === 'lineup2' ? '#ff5a5a' : '#ffffff', { stroke: 10 });
    }
    return;
  }
  // countdown
  const cd = vt - TL.raceStartFrame / FPS;
  if (cd > -1.8 && cd < 0.8) {
    const lab = cd < 0 ? String(Math.ceil(-cd / 0.6)) : 'GO!';
    const ph = cd < 0 ? ((cd + 1.8) % 0.6) / 0.6 : cd / 0.8;
    txt(lab, W / 2, 900, Math.round(cd < 0 ? lerp(380, 250, ph) : 300 + ph * 60), cd < 0 ? '#ffffff' : '#41ff7a', { stroke: 24 });
  }
  const alive = i => !(killOf[i] && t >= killOf[i].t);
  if (f < TL.raceEndFrame) {
    txt('WHO SURVIVES?', W / 2, 150, 80, '#ffffff', { stroke: 12 });
    // standings chips
    const order = [...Array(N).keys()].sort((a, b) => (alive(b) - alive(a)) || (alive(a) ? xAt(b, t) - xAt(a, t) : killOf[b].t - killOf[a].t));
    const cw = Math.min(130, (W - 100) / N), x0 = W / 2 - cw * N / 2 + cw / 2;
    order.forEach((i, k) => {
      const cx = x0 + k * cw, cy = 262, rr = cw * 0.38, a = alive(i);
      g.beginPath(); g.arc(cx, cy, rr, 0, 2 * PI); g.fillStyle = a ? names[i].color : '#4a4a50'; g.fill();
      g.lineWidth = 6; g.strokeStyle = '#090910'; g.stroke();
      if (a) txt(String(k + 1), cx, cy + 2, Math.round(rr * 1.1), '#ffffff', { stroke: 7 });
      else { g.strokeStyle = '#ff3030'; g.lineWidth = 8; g.beginPath(); g.moveTo(cx - rr * .55, cy - rr * .55); g.lineTo(cx + rr * .55, cy + rr * .55); g.moveTo(cx + rr * .55, cy - rr * .55); g.lineTo(cx - rr * .55, cy + rr * .55); g.stroke(); }
    });
    // mini track
    const bx0 = 110, bx1 = W - 110, by = 350;
    g.fillStyle = 'rgba(10,10,16,0.75)'; g.beginPath(); g.roundRect(bx0 - 14, by - 14, bx1 - bx0 + 28, 28, 14); g.fill();
    g.fillStyle = '#ffffff'; g.fillRect(bx1 - 4, by - 18, 8, 36);
    for (let i = 0; i < N; i++) if (alive(i)) {
      const px = bx0 + (bx1 - bx0) * clamp(xAt(i, t) / TRACK, 0, 1);
      g.beginPath(); g.arc(px, by, 15, 0, 2 * PI); g.fillStyle = names[i].color; g.fill(); g.lineWidth = 4; g.strokeStyle = '#000'; g.stroke();
    }
  }
  // slow-mo badge
  const slow = TL.slow.some(([a, b]) => t >= a && t < b);
  if (slow && f < TL.raceEndFrame) {
    g.fillStyle = Math.floor(vt * 4) % 2 ? '#ff2a2a' : '#7a0f0f'; g.beginPath(); g.arc(W - 270, 440, 14, 0, 2 * PI); g.fill();
    txt('SLOW-MO', W - 140, 442, 44, '#ffffff', { stroke: 8 });
  }
  // event callouts
  for (const e of events) {
    const dt = t - e.t;
    if (e.type === 'kill') {
      if (s.type.startsWith('kill') && s.who === e.who && dt < 0 && dt > -TL.warn) {
        if (Math.floor(vt * 6) % 2 === 0) txt(KILL_WARN[e.kind], W / 2, 530, 78, '#ff3b3b', { stroke: 12 });
        txt(`${names[e.who].name} IN DANGER`, W / 2, 620, 52, names[e.who].color, { stroke: 10 });
      }
      if (dt >= 0 && dt < 1.25) {
        const pop = Math.min(1, dt / 0.08), left = N - events.filter(q => q.type === 'kill' && q.t <= t).length;
        g.fillStyle = `rgba(255,0,0,${0.2 * Math.max(0, 1 - dt * 4)})`; g.fillRect(0, 0, W, H);
        g.fillStyle = 'rgba(8,8,12,0.72)'; g.fillRect(0, 1120, W, 330);
        g.fillStyle = names[e.who].color; g.fillRect(0, 1120, W, 10); g.fillRect(0, 1440, W, 10);
        txt(names[e.who].name, W / 2, 1210, Math.round(150 * pop), names[e.who].color, { stroke: 16 });
        txt('ELIMINATED', W / 2, 1330, Math.round(96 * pop), '#ffffff', { stroke: 12 });
        txt(`${left} LEFT`, W / 2, 1405, 50, '#ffd12e', { stroke: 8 });
      }
    } else if (e.type === 'miss' && dt >= 0 && dt < 1.2) {
      txt('CLOSE CALL!', W / 2, 560, 96, '#ffd12e', { stroke: 14 });
      txt(names[e.who].name + ' SURVIVES', W / 2, 660, 50, names[e.who].color, { stroke: 9 });
    } else if ((e.type === 'boost' && dt >= 0 && dt < 1.3) || (e.type === 'trip' && dt >= 0 && dt < 1.0)) {
      if (!alive(e.who)) continue;
      const p = V(laneX(e.who), 2.4, -xAt(e.who, t)).project(camera);
      if (p.z < 1 && Math.abs(p.x) < 1.1 && Math.abs(p.y) < 1.1) {
        const sx = clamp((p.x + 1) / 2 * W, 170, W - 170), sy = clamp((1 - p.y) / 2 * H, 480, 1500);
        txt(e.type === 'boost' ? 'BOOST!' : 'OOF!', sx, sy, 64, e.type === 'boost' ? '#5fd7ff' : '#ffb03b', { stroke: 10 });
      }
    } else if (e.type === 'finish' && f < TL.raceEndFrame) {
      if (dt < 0 && dt > -1.5 && TL.margin < 0.5) txt('PHOTO FINISH!', W / 2, 560, 100, '#ffd12e', { stroke: 14 });
      if (dt >= 0) txt('FINISH!', W / 2, 600, 150, names[e.who].color, { stroke: 18 });
    }
  }
  if (f >= TL.raceEndFrame) {
    const lt = (f - TL.raceEndFrame) / FPS, w = names[TL.winner], pop = Math.min(1, lt / 0.2);
    const gr = g.createLinearGradient(0, 0, 0, 700); gr.addColorStop(0, 'rgba(0,0,0,0.7)'); gr.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = gr; g.fillRect(0, 0, W, 700);
    txt('WINNER', W / 2, 170, 70, '#ffd12e', { stroke: 10 });
    txt(w.name, W / 2, 330, Math.round(200 * pop), w.color, { stroke: 22 });
    txt('WINS!', W / 2, 500, Math.round(150 * pop), '#ffffff', { stroke: 18 });
    if (lt > 1.0) txt(`Did you pick ${w.name}?`, W / 2, 1330, 68, '#ffffff', { stroke: 12 });
    if (lt > 1.8) txt('New race every day - Subscribe!', W / 2, 1430, 52, '#ffd12e', { stroke: 10 });
  }
}

// ------------------------------------------------------------------ public API
window.init = async (timeline) => {
  TL = timeline; N = TL.runners.length; FPS = TL.fps; SIM = TL.simHz; TRACK = TL.trackLen; theme = TL.theme;
  events = TL.events; trackW = N * LANE_W + 1.2; half = trackW / 2;
  CHAR = TL.character || 'person'; CH = CHAR_CFG[CHAR];
  for (const e of events) if (e.type === 'kill') killOf[e.who] = e;
  const ff = new FontFace('Race', 'url(/assets/font.otf)'); await ff.load(); document.fonts.add(ff);

  renderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1); renderer.setSize(W, H, false);
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  document.body.appendChild(renderer.domElement);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(50, W / H, 0.1, 5000);
  hud = document.createElement('canvas'); hud.width = W; hud.height = H; g = hud.getContext('2d');

  buildWorld();
  await buildRunners();
  buildEffects();
  return true;
};

window.renderFrame = (f) => {
  const t = TL.simT[f], vt = f / FPS; curVt = vt; vtNow = vt;
  P.fire.reset(); P.smoke.reset(); P.conf.reset(); P.flake.reset();
  worldAnim.forEach(fn => fn(vt));
  const states = R.map((_, i) => runnerState(i, t, f));
  const cam = cameraFor(f, t, states);
  const { shake, flash } = updateEffects(t, vt);
  // camera with shake
  const sk = Math.min(0.6, shake) * (cam.shot.type.startsWith('kill') ? 1 : 0.6);
  const off = V(Math.sin(vt * 53) + Math.sin(vt * 31), Math.sin(vt * 47 + 1) + Math.sin(vt * 23), Math.sin(vt * 41 + 2)).multiplyScalar(sk * 0.25);
  camera.position.copy(cam.pos).add(off); camera.fov = cam.fov; camera.updateProjectionMatrix();
  camera.lookAt(cam.look.clone().add(off.clone().multiplyScalar(0.5)));
  camera.updateMatrixWorld();
  states.forEach((st, i) => applyRunner(i, st, camera.position));
  updateMiscParticles(t, f, states);
  P.fire.commit(); P.smoke.commit(); P.conf.commit(); P.flake.commit();

  const excite = Math.min(1, events.reduce((a, e) => a + ((t >= e.t && t < e.t + 3 && e.type !== 'boost') ? 1 : 0), 0) + (f >= TL.raceEndFrame - 60 ? 1 : 0.15));
  updateCrowd(vt, excite, camera.position.z, cam.look.z);
  // shadows follow the action
  const focus = V(cam.look.x * 0.5, 0, cam.look.z);
  sun.target.position.copy(focus); sun.position.copy(focus).add(sun.userData.dir.clone().multiplyScalar(90));
  renderer.toneMappingExposure = baseExposure * (1 + flash);

  renderer.render(scene, camera);
  g.drawImage(renderer.domElement, 0, 0);
  drawHUD(f, t, cam);
  return hud.toDataURL('image/jpeg', 0.92);
};
window._dbg = () => ({ scene, renderer, crowd, P, sun, lights, hemi });
window.ready = true;
