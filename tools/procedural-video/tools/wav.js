// Minimal WAV (16-bit PCM stereo) reader/writer.
const fs = require('fs');
exports.write = (file, L, R, sr = 48000) => {
  const n = L.length, b = Buffer.alloc(44 + n * 4);
  b.write('RIFF', 0); b.writeUInt32LE(36 + n * 4, 4); b.write('WAVEfmt ', 8); b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(2, 22); b.writeUInt32LE(sr, 24); b.writeUInt32LE(sr * 4, 28); b.writeUInt16LE(4, 32); b.writeUInt16LE(16, 34); b.write('data', 36); b.writeUInt32LE(n * 4, 40);
  for (let i = 0; i < n; i++) { b.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(L[i] * 32767))), 44 + i * 4); b.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(R[i] * 32767))), 46 + i * 4); }
  fs.writeFileSync(file, b);
};
exports.read = file => { const b = fs.readFileSync(file); let p = 12, fmt = null, data = null;
  while (p + 8 <= b.length) { const id = b.toString('ascii', p, p + 4), sz = b.readUInt32LE(p + 4); if (id === 'fmt ') fmt = { ch: b.readUInt16LE(p + 10), sr: b.readUInt32LE(p + 12), bits: b.readUInt16LE(p + 22) }; if (id === 'data') { data = b.subarray(p + 8, Math.min(b.length, p + 8 + sz)); break; } p += 8 + sz + (sz & 1); }
  if (!fmt || !data || fmt.bits !== 16) throw new Error('unsupported wav: ' + file);
  const n = Math.floor(data.length / (2 * fmt.ch)), L = new Float32Array(n), R = new Float32Array(n);
  for (let i = 0; i < n; i++) { L[i] = data.readInt16LE(i * 2 * fmt.ch) / 32768; R[i] = fmt.ch > 1 ? data.readInt16LE(i * 2 * fmt.ch + 2) / 32768 : L[i]; }
  return { L, R, sr: fmt.sr }; };
