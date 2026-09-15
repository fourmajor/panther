import { test } from "node:test";
import assert from "node:assert/strict";
import { webRelease } from "../lib/web-release";

test("release names follow bytes, HTML changes change release identity", () => {
  const html = '<head><script src="/app.js"></script><link href="/styles.css"></head>';
  const assets = { "app.js": "old", "styles.css": "body{}" };
  const first = webRelease(html, assets);
  assert.deepEqual(first, webRelease(html, assets));
  assert.match(first.html, /app\.[a-f0-9]{20}\.js/);
  assert.match(first.html, /styles\.[a-f0-9]{20}\.css/);
  const second = webRelease(html, { ...assets, "app.js": "new" });
  assert.notEqual(first.version, second.version);
  assert.equal(Object.keys(first.files)[1], Object.keys(second.files)[1]);
  assert.notEqual(first.version, webRelease(html + "changed", assets).version);
  assert.equal(JSON.parse(first.manifest).version, first.version);
});
