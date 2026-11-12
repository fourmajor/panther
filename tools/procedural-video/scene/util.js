// Deterministic helpers: seeded PRNG, smooth noise, easing. No Math.random, no clocks.
export function mulberry32(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, t) => a + (b - a) * t;
export const sstep = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
export const ease = t => { t = clamp(t); return t * t * (3 - 2 * t); };
export const easeOut = t => 1 - Math.pow(1 - clamp(t), 3);
export function hash1(n) { const s = Math.sin(n * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); }
export function noise1(x, seed = 0) { const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f); return lerp(hash1(i + seed * 57.31), hash1(i + 1 + seed * 57.31), u) * 2 - 1; }
export function fbm1(x, seed = 0) { return noise1(x, seed) * 0.6 + noise1(x * 2.13, seed + 3) * 0.28 + noise1(x * 4.31, seed + 7) * 0.12; }
export const flicker = (t, seed = 0) => 0.8 + 0.2 * fbm1(t * 6.5, seed) + 0.06 * noise1(t * 19, seed + 11);
// pulse centred at t0: fast attack, exponential decay
export const pulse = (t, t0, atk = 0.04, dec = 0.5) => t < t0 ? 0 : (t - t0 < atk ? (t - t0) / atk : Math.exp(-(t - t0 - atk) / dec));
