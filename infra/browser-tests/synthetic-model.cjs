// A self-contained colored tetrahedron, not a game asset.
module.exports = function syntheticModel(version = 1, embeddedPng) {
  const vertices = new Float32Array([0, 1, 0, -1, -1, 1, 1, -1, 1, 0, -1, -1]);
  const indices = new Uint16Array([0, 1, 2, 0, 2, 3, 0, 3, 1, 1, 3, 2]);
  const uv = new Float32Array([0.5, 1, 0, 0, 1, 0, 0.5, 0.5]);
  const geometry = Buffer.concat([Buffer.from(vertices.buffer), Buffer.from(indices.buffer)]);
  const textureBytes = embeddedPng ? Buffer.concat([embeddedPng, Buffer.alloc((4 - embeddedPng.length % 4) % 4)]) : Buffer.alloc(0);
  const bin = embeddedPng ? Buffer.concat([geometry, Buffer.from(uv.buffer), textureBytes]) : geometry;
  const model = { asset: { version: '2.0' }, scene: 0, scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0 }], meshes: [{ primitives: [{ attributes: { POSITION: 0 }, indices: 1, material: 0 }] }],
    materials: [{ doubleSided: true, pbrMetallicRoughness: { baseColorFactor: version === 1 ? [0.8, 0.2, 0.1, 1] : [0.1, 0.6, 0.9, 1], metallicFactor: 0, roughnessFactor: 0.8 } }],
    buffers: [{ byteLength: bin.length }],
    bufferViews: [{ buffer: 0, byteOffset: 0, byteLength: vertices.byteLength }, { buffer: 0, byteOffset: vertices.byteLength, byteLength: indices.byteLength }],
    accessors: [{ bufferView: 0, componentType: 5126, count: 4, type: 'VEC3', min: [-1, -1, -1], max: [1, 1, 1] }, { bufferView: 1, componentType: 5123, count: 12, type: 'SCALAR' }],
  };
  if (embeddedPng) {
    model.meshes[0].primitives[0].attributes.TEXCOORD_0 = 2;
    model.materials[0].pbrMetallicRoughness.baseColorFactor = [1, 1, 1, 1];
    model.materials[0].pbrMetallicRoughness.baseColorTexture = { index: 0 };
    model.bufferViews.push({ buffer: 0, byteOffset: geometry.length, byteLength: uv.byteLength },
      { buffer: 0, byteOffset: geometry.length + uv.byteLength, byteLength: embeddedPng.length });
    model.accessors.push({ bufferView: 2, componentType: 5126, count: 4, type: 'VEC2' });
    model.images = [{ bufferView: 3, mimeType: 'image/png' }];
    model.textures = [{ source: 0 }];
  }
  const text = Buffer.from(JSON.stringify(model));
  const json = Buffer.concat([text, Buffer.alloc((4 - text.length % 4) % 4, 32)]);
  const header = Buffer.alloc(12); header.write('glTF'); header.writeUInt32LE(2, 4); header.writeUInt32LE(28 + json.length + bin.length, 8);
  const jsonHeader = Buffer.alloc(8); jsonHeader.writeUInt32LE(json.length); jsonHeader.write('JSON', 4);
  const binHeader = Buffer.alloc(8); binHeader.writeUInt32LE(bin.length); binHeader.write('BIN\0', 4);
  return Buffer.concat([header, jsonHeader, json, binHeader, bin]);
};
