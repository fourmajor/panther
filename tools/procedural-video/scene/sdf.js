// Signed-distance sculpting kit: primitives, smooth booleans and a surface-nets mesher (indexed, gradient normals).
// Used for organic forms that boxes and lathes cannot give: heads, skulls, jaws, pelvises.
import * as THREE from 'three';

export const smin = (a, b, k) => { const h = Math.max(k - Math.abs(a - b), 0) / k; return Math.min(a, b) - h * h * k * 0.25; };
export const smax = (a, b, k) => -smin(-a, -b, k);
export const sph = (x, y, z, r) => Math.sqrt(x * x + y * y + z * z) - r;
// ellipsoid (iq's bounded approximation); x,y,z already relative to the centre
export function ell(x, y, z, rx, ry, rz) {
  const ax = x / rx, ay = y / ry, az = z / rz, k0 = Math.sqrt(ax * ax + ay * ay + az * az);
  const bx = ax / rx, by = ay / ry, bz = az / rz, k1 = Math.sqrt(bx * bx + by * by + bz * bz);
  return k1 < 1e-9 ? -Math.min(rx, ry, rz) : k0 * (k0 - 1) / k1;
}
// capsule / round cone from a to b with radii r1 -> r2
export function cone(x, y, z, ax, ay, az, bx, by, bz, r1, r2 = r1) {
  const dx = bx - ax, dy = by - ay, dz = bz - az, px = x - ax, py = y - ay, pz = z - az;
  let t = (px * dx + py * dy + pz * dz) / (dx * dx + dy * dy + dz * dz); t = t < 0 ? 0 : t > 1 ? 1 : t;
  const qx = px - dx * t, qy = py - dy * t, qz = pz - dz * t;
  return Math.sqrt(qx * qx + qy * qy + qz * qz) - (r1 + (r2 - r1) * t);
}
export const box = (x, y, z, hx, hy, hz) => { const qx = Math.abs(x) - hx, qy = Math.abs(y) - hy, qz = Math.abs(z) - hz; const ox = Math.max(qx, 0), oy = Math.max(qy, 0), oz = Math.max(qz, 0); return Math.sqrt(ox * ox + oy * oy + oz * oz) + Math.min(Math.max(qx, qy, qz), 0); };
// torus in the XZ plane (axis y)
export const torus = (x, y, z, R, r) => { const q = Math.sqrt(x * x + z * z) - R; return Math.sqrt(q * q + y * y) - r; };

// Surface nets. f(x,y,z) -> distance (negative inside). Returns { position:Float32Array, normal:Float32Array, index:Uint32Array }.
export function surfaceNets(f, min, max, h) {
  const nx = Math.ceil((max[0] - min[0]) / h) + 1, ny = Math.ceil((max[1] - min[1]) / h) + 1, nz = Math.ceil((max[2] - min[2]) / h) + 1;
  const val = new Float32Array(nx * ny * nz); let n = 0;
  for (let k = 0; k < nz; k++) { const z = min[2] + k * h; for (let j = 0; j < ny; j++) { const y = min[1] + j * h; for (let i = 0; i < nx; i++) val[n++] = f(min[0] + i * h, y, z); } }
  const vid = new Int32Array(nx * ny * nz).fill(-1), pos = [], sx = 1, sy = nx, sz = nx * ny;
  const cx = [0, 1, 0, 1, 0, 1, 0, 1], cy = [0, 0, 1, 1, 0, 0, 1, 1], cz = [0, 0, 0, 0, 1, 1, 1, 1];
  const E = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]], c = new Float32Array(8);
  for (let k = 0; k < nz - 1; k++) for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
    const o = i + sy * j + sz * k; let m = 0;
    for (let q = 0; q < 8; q++) { c[q] = val[o + cx[q] * sx + cy[q] * sy + cz[q] * sz]; if (c[q] < 0) m |= 1 << q; }
    if (m === 0 || m === 255) continue;
    let px = 0, py = 0, pz = 0, cnt = 0;
    for (let e = 0; e < 12; e++) { const a = E[e][0], b = E[e][1]; if ((c[a] < 0) === (c[b] < 0)) continue; const t = c[a] / (c[a] - c[b]);
      px += cx[a] + (cx[b] - cx[a]) * t; py += cy[a] + (cy[b] - cy[a]) * t; pz += cz[a] + (cz[b] - cz[a]) * t; cnt++; }
    vid[o] = pos.length / 3; pos.push(min[0] + (i + px / cnt) * h, min[1] + (j + py / cnt) * h, min[2] + (k + pz / cnt) * h);
  }
  const idx = [], quad = (a, b, c2, d, flip) => { if (a < 0 || b < 0 || c2 < 0 || d < 0) return; if (flip) idx.push(a, d, c2, a, c2, b); else idx.push(a, b, c2, a, c2, d); };
  for (let k = 1; k < nz - 1; k++) for (let j = 1; j < ny - 1; j++) for (let i = 1; i < nx - 1; i++) {
    const o = i + sy * j + sz * k, v = val[o] < 0;
    if (v !== (val[o + sx] < 0)) quad(vid[o - sy - sz], vid[o - sz], vid[o], vid[o - sy], !v);
    if (v !== (val[o + sy] < 0)) quad(vid[o - sx - sz], vid[o - sx], vid[o], vid[o - sz], !v);
    if (v !== (val[o + sz] < 0)) quad(vid[o - sx - sy], vid[o - sy], vid[o], vid[o - sx], !v);
  }
  const P = new Float32Array(pos), N = new Float32Array(P.length), e = h * 0.5;
  for (let i = 0; i < P.length; i += 3) { const x = P[i], y = P[i + 1], z = P[i + 2];
    let gx = f(x + e, y, z) - f(x - e, y, z), gy = f(x, y + e, z) - f(x, y - e, z), gz = f(x, y, z + e) - f(x, y, z - e); const l = Math.hypot(gx, gy, gz) || 1;
    N[i] = gx / l; N[i + 1] = gy / l; N[i + 2] = gz / l; }
  let vote = 0; for (let t = 0; t < idx.length; t += 3) { const a = idx[t] * 3, b = idx[t + 1] * 3, c2 = idx[t + 2] * 3, ux = P[b] - P[a], uy = P[b + 1] - P[a + 1], uz = P[b + 2] - P[a + 2], vx = P[c2] - P[a], vy = P[c2 + 1] - P[a + 1], vz = P[c2 + 2] - P[a + 2];
    vote += (uy * vz - uz * vy) * N[a] + (uz * vx - ux * vz) * N[a + 1] + (ux * vy - uy * vx) * N[a + 2] > 0 ? 1 : -1; }
  if (vote < 0) for (let t = 0; t < idx.length; t += 3) { const q = idx[t + 1]; idx[t + 1] = idx[t + 2]; idx[t + 2] = q; }
  return { position: P, normal: N, index: new Uint32Array(idx) };
}
// Light Laplacian relaxation that keeps vertices on the surface band (removes the voxel staircase).
export function relax(m, iters = 2, k = 0.5) {
  const P = m.position, n = P.length / 3, I = m.index, acc = new Float32Array(P.length), cnt = new Uint16Array(n);
  for (let it = 0; it < iters; it++) { acc.fill(0); cnt.fill(0);
    for (let t = 0; t < I.length; t += 3) for (let e = 0; e < 3; e++) { const a = I[t + e], b = I[t + (e + 1) % 3]; acc[a * 3] += P[b * 3]; acc[a * 3 + 1] += P[b * 3 + 1]; acc[a * 3 + 2] += P[b * 3 + 2]; cnt[a]++; }
    for (let i = 0; i < n; i++) if (cnt[i]) for (let d = 0; d < 3; d++) P[i * 3 + d] += (acc[i * 3 + d] / cnt[i] - P[i * 3 + d]) * k; }
  return m;
}
export function toGeometry(m) {
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(m.position, 3)); g.setAttribute('normal', new THREE.BufferAttribute(m.normal, 3));
  if (m.color) g.setAttribute('color', new THREE.BufferAttribute(m.color, 3)); g.setIndex(new THREE.BufferAttribute(m.index, 1)); return g;
}
// March from far along dir toward origin o until the surface f=iso; returns the hit point [x,y,z].
export function project(f, o, dir, far = 0.3, iso = 0) {
  let t = far; for (let i = 0; i < 48; i++) { const d = f(o[0] + dir[0] * t, o[1] + dir[1] * t, o[2] + dir[2] * t) - iso; if (d < 2e-4) break; t -= d * 0.8; if (t < 0) { t = 0; break; } }
  return [o[0] + dir[0] * t, o[1] + dir[1] * t, o[2] + dir[2] * t];
}
