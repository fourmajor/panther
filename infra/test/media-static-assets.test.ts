import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as path from "node:path";
import test from "node:test";
import ts from "typescript";
import { MODEL_VIEWER_BUNDLE_PATH } from "../lib/panther-media-explorer-stack";

test("deployed model viewer has no unresolved static imports", () => {
  const source = ts.createSourceFile(
    "model-viewer.js",
    readFileSync(MODEL_VIEWER_BUNDLE_PATH, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.JS,
  );
  for (const statement of source.statements) {
    const specifier = ts.isImportDeclaration(statement) || ts.isExportDeclaration(statement)
      ? statement.moduleSpecifier : undefined;
    assert.equal(specifier, undefined, "Viewer must bundle its static dependencies");
  }
});

test("static assets resolve from nested character URLs", () => {
  const html = readFileSync(path.join(__dirname, "../../../web/media-explorer/index.html"), "utf8");
  const assets = [...html.matchAll(/<(?:script|link)\b[^>]*\b(?:src|href)="([^"]+)"/g)];
  assert.equal(assets.length, 4);
  for (const [, asset] of assets) {
    assert.ok(asset.startsWith("/"), `${asset} must resolve from the site root`);
    assert.equal(new URL(asset, "https://panther.place/characters/game/character").pathname, asset);
  }
});
