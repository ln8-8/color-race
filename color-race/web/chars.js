// Non-human 3D racers: jelly blobs, ducks, cars and marbles.
// Each builder returns { model, mats, animate(st, vt) }. Model: facing +Z, bottom on y = 0.
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

// pivot height (com), centre height when lying (restY), final lying pitch (fall), eye height for close-ups
export const CHAR_CFG = {
  person: { com: 1.0, restY: 0.22, fall: -Math.PI / 2, eye: 1.45, title: 'RUNNERS' },
  jelly: { com: 0.55, restY: 0.55, fall: 0, eye: 0.8, title: 'JELLY BLOBS' },
  duck: { com: 0.62, restY: 0.45, fall: -Math.PI / 2, eye: 1.05, title: 'DUCKS' },
  car: { com: 0.5, restY: 0.6, fall: -Math.PI, eye: 0.75, title: 'TINY CARS' },
  marble: { com: 0.5, restY: 0.5, fall: 0, eye: 0.55, title: 'MARBLES' },
};

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

function std(color, env, envI, opts = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.4, metalness: 0.0, envMap: env, envMapIntensity: envI, ...opts });
}
function mesh(geo, mat, x = 0, y = 0, z = 0) {
  const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.castShadow = true; m.receiveShadow = true; return m;
}
function googlyEyes(parent, env, envI, y, z, gap, r) {
  const white = std(0xffffff, env, envI, { roughness: 0.2 }), black = std(0x111111, env, envI, { roughness: 0.1 });
  const pupils = [];
  for (const s of [-1, 1]) {
    parent.add(mesh(new THREE.SphereGeometry(r, 16, 12), white, s * gap, y, z));
    const p = mesh(new THREE.SphereGeometry(r * 0.5, 12, 10), black, s * gap, y + r * 0.05, z + r * 0.72);
    parent.add(p); pupils.push(p);
  }
  return pupils;
}

function buildJelly(color, env, envI, seed) {
  const model = new THREE.Group(), body = new THREE.Group(); model.add(body);
  const geo = new THREE.SphereGeometry(0.5, 40, 28), p = geo.attributes.position;
  for (let k = 0; k < p.count; k++) {
    const y = p.getY(k), w = y < 0 ? 1 + 0.16 * (-y / 0.5) : 1;
    p.setXYZ(k, p.getX(k) * w, y * 1.12, p.getZ(k) * w);
  }
  geo.computeVertexNormals(); geo.translate(0, 0.56, 0);
  const mat = std(color, env, envI * 1.5, { roughness: 0.06 });
  body.add(mesh(geo, mat));
  const pupils = googlyEyes(body, env, envI, 0.8, 0.38, 0.17, 0.13);
  const smile = mesh(new THREE.TorusGeometry(0.07, 0.018, 6, 14, Math.PI), std(0x3a0a14, env, envI), 0, 0.6, 0.48);
  smile.rotation.z = Math.PI; body.add(smile);
  const off = seed * 0.7;
  return {
    model, mats: [mat],
    animate(st, vt) {
      let sx = 1, sy = 1, y = 0;
      if (st.dead) {
        const splat = !st.flail && st.kind !== 'PIT' && !(st.kind === 'LIGHTNING' && st.deadDt < 0.5);
        if (splat) { sx = 1.9; sy = 0.22; } else if (st.flail) { sx = 0.85; sy = 1.25; }
      } else if (st.celebrate) {
        const h = Math.abs(Math.sin(vt * 4.2)); const q = Math.max(0, 1 - h / 0.2);
        sx = 1 + 0.3 * q; sy = 1 - 0.25 * q + 0.12 * h;
      } else if (st.wRun > 0.05) {
        const h = Math.abs(Math.sin(st.dist * 1.2 + off)) * st.wRun;
        if (h < 0.18) { const q = 1 - h / 0.18; sx = 1 + 0.3 * q * st.wRun; sy = 1 - 0.26 * q * st.wRun; }
        else { const q = Math.min(1, (h - 0.18) / 0.5); sx = 1 - 0.12 * q; sy = 1 + 0.16 * q; }
        y = h * 0.45;
      } else { const b = Math.sin(vt * 3 + off) * 0.04; sx = 1 + b; sy = 1 - b; }
      body.scale.set(sx, sy, sx); body.position.y = y;
      pupils.forEach((pp, k) => { pp.position.y = 0.8 + 0.006 + Math.sin(vt * 13 + k) * 0.015; });
    },
  };
}

function buildMarble(color, env, envI, seed) {
  const model = new THREE.Group(), ball = new THREE.Group(); ball.position.y = 0.5; model.add(ball);
  const c = document.createElement('canvas'); c.width = 512; c.height = 256;
  const g = c.getContext('2d'), col = new THREE.Color(color);
  g.fillStyle = '#' + col.getHexString(); g.fillRect(0, 0, 512, 256);
  g.strokeStyle = 'rgba(255,255,255,0.85)'; g.lineWidth = 22;
  for (let k = 0; k < 3; k++) {
    g.beginPath();
    for (let x = 0; x <= 512; x += 8) { const y = 128 + Math.sin(x / 512 * Math.PI * 2 * (k + 1) + seed + k) * (60 - k * 15); x ? g.lineTo(x, y) : g.moveTo(x, y); }
    g.stroke(); g.lineWidth = 10;
  }
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const mat = std(0xffffff, env, envI * 2, { map: tex, roughness: 0.04, metalness: 0.15 });
  const sphere = mesh(new THREE.SphereGeometry(0.5, 40, 28), mat); ball.add(sphere);
  return {
    model, mats: [mat],
    animate(st) { ball.rotation.x = st.dist / 0.5; },
    tint: true,
  };
}

function buildDuck(color, env, envI, seed) {
  const model = new THREE.Group(), body = new THREE.Group(); model.add(body);
  const col = new THREE.Color(color), belly = col.clone().lerp(new THREE.Color(0xffffff), 0.5);
  const mat = std(col, env, envI, { roughness: 0.55 }), bellyMat = std(belly, env, envI, { roughness: 0.6 });
  const orange = std(0xff9a1e, env, envI, { roughness: 0.5 });
  const b = mesh(new THREE.SphereGeometry(0.42, 28, 20), mat, 0, 0.56, 0); b.scale.set(0.9, 0.8, 1.15); body.add(b);
  const be = mesh(new THREE.SphereGeometry(0.3, 20, 14), bellyMat, 0, 0.5, 0.2); be.scale.set(0.85, 0.75, 0.9); body.add(be);
  body.add(mesh(new THREE.SphereGeometry(0.26, 24, 18), mat, 0, 1.0, 0.3));
  const beak = mesh(new THREE.SphereGeometry(0.12, 16, 10), orange, 0, 0.95, 0.58); beak.scale.set(1, 0.45, 1.6); body.add(beak);
  googlyEyes(body, env, envI, 1.06, 0.47, 0.13, 0.075);
  const tail = mesh(new THREE.ConeGeometry(0.13, 0.3, 10), mat, 0, 0.76, -0.52); tail.rotation.x = -1.0; body.add(tail);
  const wings = [-1, 1].map(s => {
    const piv = new THREE.Group(); piv.position.set(s * 0.36, 0.72, 0); body.add(piv);
    const w = mesh(new THREE.SphereGeometry(0.26, 16, 12), mat, s * 0.04, -0.14, -0.02); w.scale.set(0.3, 0.6, 1.0); piv.add(w);
    piv.userData.s = s; return piv;
  });
  const feet = [-1, 1].map(s => {
    const f = new THREE.Group(); model.add(f);
    f.add(mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.22, 6), orange, 0, 0.13, 0));
    f.add(mesh(new THREE.BoxGeometry(0.16, 0.04, 0.24), orange, 0, 0.02, 0.06));
    f.position.x = s * 0.15; f.userData.s = s; return f;
  });
  if (seed % 3 === 0) {          // party hat on some ducks
    const hat = mesh(new THREE.ConeGeometry(0.1, 0.26, 12), std(0xffffff, env, envI), 0.02, 1.33, 0.27); hat.rotation.z = -0.2; body.add(hat);
  }
  return {
    model, mats: [mat],
    animate(st, vt) {
      const p = st.dist * 2.3 + seed;
      const run = st.dead ? 0 : st.wRun;
      body.rotation.z = Math.sin(p) * 0.16 * run;
      body.position.y = Math.abs(Math.sin(p)) * 0.07 * run;
      feet.forEach(f => { const q = p + (f.userData.s > 0 ? 0 : Math.PI); f.position.z = Math.sin(q) * 0.16 * run; f.position.y = Math.max(0, -Math.cos(q)) * 0.08 * run; });
      const flap = st.celebrate ? 0.9 + 0.5 * Math.sin(vt * 25) : st.flail ? 1.2 + 0.6 * Math.sin(vt * 40) : 0.15 + 0.25 * Math.sin(p * 2) * run;
      wings.forEach(w => { w.rotation.z = w.userData.s * flap; });
    },
  };
}

function buildCar(color, env, envI, seed) {
  const model = new THREE.Group(), body = new THREE.Group(); model.add(body);
  const paint = std(color, env, envI * 1.6, { roughness: 0.18, metalness: 0.35 });
  const glass = std(0x152536, env, envI * 2, { roughness: 0.05, metalness: 0.6 });
  body.add(mesh(new RoundedBoxGeometry(0.92, 0.34, 1.6, 3, 0.1), paint, 0, 0.4, 0));
  body.add(mesh(new RoundedBoxGeometry(0.78, 0.34, 0.84, 3, 0.12), paint, 0, 0.7, -0.12));
  body.add(mesh(new RoundedBoxGeometry(0.81, 0.22, 0.87, 2, 0.08), glass, 0, 0.71, -0.12));
  const white = new THREE.MeshBasicMaterial({ color: 0xffffff }), black = new THREE.MeshBasicMaterial({ color: 0x111111 });
  for (const s of [-1, 1]) {                         // eyes on the windshield
    const e = new THREE.Mesh(new THREE.CircleGeometry(0.1, 20), white); e.position.set(s * 0.17, 0.72, 0.32); body.add(e);
    const pu = new THREE.Mesh(new THREE.CircleGeometry(0.05, 16), black); pu.position.set(s * 0.17 + 0.015, 0.71, 0.325); body.add(pu);
    const hl = mesh(new THREE.BoxGeometry(0.16, 0.08, 0.04), new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff2b0, emissiveIntensity: 2 }), s * 0.3, 0.44, 0.8); body.add(hl);
    const tl = mesh(new THREE.BoxGeometry(0.16, 0.07, 0.04), new THREE.MeshStandardMaterial({ color: 0xff2020, emissive: 0xff0000, emissiveIntensity: 1.2 }), s * 0.3, 0.44, -0.8); body.add(tl);
  }
  const stripe = mesh(new THREE.BoxGeometry(0.16, 0.012, 1.62), std(0xffffff, env, envI), 0, 0.575, 0); body.add(stripe);
  const tyre = std(0x161616, env, envI * 0.3, { roughness: 0.85 }), hub = std(0xcfd3d8, env, envI * 2, { roughness: 0.2, metalness: 0.9 });
  const wheels = [];
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    const w = new THREE.Group(); w.position.set(sx * 0.47, 0.22, sz * 0.5); model.add(w);
    const t = mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.17, 20), tyre); t.rotation.z = Math.PI / 2; w.add(t);
    const h = mesh(new THREE.CylinderGeometry(0.11, 0.11, 0.18, 6), hub); h.rotation.z = Math.PI / 2; w.add(h);
    wheels.push(w);
  }
  return {
    model, mats: [paint],
    animate(st, vt) {
      wheels.forEach(w => { w.rotation.x = st.dist / 0.22; });
      body.position.y = st.dead ? 0 : Math.abs(Math.sin(st.dist * 4 + seed)) * 0.02 * st.wRun;
      model.rotation.x = st.celebrate ? -0.35 * Math.abs(Math.sin(vt * 3)) : 0;   // wheelie
    },
  };
}

export function buildCharacter(kind, color, env, envI, seed) {
  return { jelly: buildJelly, duck: buildDuck, car: buildCar, marble: buildMarble }[kind](color, env, envI, seed);
}
