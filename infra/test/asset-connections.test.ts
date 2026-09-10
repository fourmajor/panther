import * as fs from "node:fs";
import * as path from "node:path";
import * as vm from "node:vm";
import test from "node:test";
import assert from "node:assert/strict";

const source = fs.readFileSync(path.join(__dirname, "../../../web/media-explorer/app.js"), "utf8");
const project = vm.runInNewContext(source.slice(source.indexOf("function finishedAssetConnections("),
  source.indexOf("function appendFinishedConnections(")) + "\nfinishedAssetConnections;");
const prefix = "games/test-game/assets/";
const asset = (id: string, kind: string, inputs: string[] = [], extra = {}) => ({
  key: prefix + id, name: id.split("/").at(-1), kind, sourceKeys: inputs.map(i => prefix + i),
  contentType: "application/json", metadata: { title: kind }, ...extra,
});
const keys = (items: any[]) => Array.from(items, a => a.key.slice(prefix.length)).sort();

test("connections traverse hidden stages in both directions and stop at finished assets", () => {
  const assets = [asset("raw.json", "raw-transcript"), asset("context.json", "context", ["raw.json"]),
    asset("correction.json", "correction", ["context.json"]), asset("corrected.json", "corrected-transcript", ["correction.json"]),
    asset("draft.json", "novel-draft", ["corrected.json"]), asset("proof.json", "novel-proof", ["draft.json"]),
    asset("novel.json", "novel-chapter", ["proof.json"]), asset("shots.json", "video-shot-list", ["corrected.json"]),
    asset("take.mp4", "video-comparison", ["shots.json"], {contentType: "video/mp4"})];
  assert.deepEqual(keys(project(assets, prefix + "raw.json", "test-game").outputs), ["corrected.json"]);
  const result = project(assets, prefix + "corrected.json", "test-game");
  assert.deepEqual(keys(result.inputs), ["raw.json"]);
  assert.deepEqual(keys(result.outputs), ["novel.json", "take.mp4"]);
  assert.deepEqual(keys(project(assets, prefix + "take.mp4", "test-game").inputs), ["corrected.json"]);
});

test("collapse only explicitly linked recording parts and playback; deduplicate paired exports", () => {
  const recording = "r/original/recording.json", part = "r/original/part-0000.flac";
  const assets = [asset(recording, "recording-manifest", [part], {recording: {partCount: 1}}),
    asset(part, "recording", [], {contentType: "audio/flac"}), asset("r/original/playback.json", "recording-playback-manifest", [recording, part],
      {playback: {recordingKey: prefix + recording, audioKey: prefix + "r/original/playback.mp3"}}),
    asset("r/original/playback.mp3", "recording-playback", ["r/original/playback.json"], {contentType:"audio/mpeg"}),
    asset("raw.json", "raw-transcript", [recording]), asset("raw.md", "raw-transcript", [recording]),
    asset("r/original/music.mp3", "music", [], {contentType:"audio/mpeg"})];
  const result = project(assets, prefix + recording, "test-game");
  assert.deepEqual(keys(result.inputs), []);
  assert.deepEqual(keys(result.outputs), ["raw.json"]);
  assert.deepEqual(keys(project(assets, prefix + "raw.md", "test-game").inputs), [recording]);
  assert.deepEqual(keys(project(assets, prefix + "r/original/playback.mp3", "test-game").outputs), ["raw.json"]);
  assert.deepEqual(keys(project(assets, prefix + "r/original/music.mp3", "test-game").outputs), []);
});

test("cycles, missing sources, unknown types, foreign games and intermediate images are safe", () => {
  const assets = [asset("raw.json", "raw-transcript"), asset("a.json", "context", ["raw.json", "b.json", "missing.json"]),
    asset("b.json", "correction", ["a.json"]), asset("boards.png", "video-storyboards", ["b.json"], {contentType:"image/png"}),
    asset("future.bin", "future-format", ["boards.png"], {metadata:{extra:{relationshipRole:"finished"}}}),
    asset("unclassified.json", "unknown", ["raw.json"]),
    {...asset("foreign.json", "novel-chapter", ["raw.json"]), key:"games/other-game/assets/foreign.json"}];
  const result = project(assets, prefix + "raw.json", "test-game");
  assert.deepEqual(keys(result.outputs), ["future.bin"]);
  assert.equal(result.incomplete, true);
  assert.deepEqual(keys(project(assets, prefix + "future.bin", "test-game").inputs), ["raw.json"]);
  assert.deepEqual(assets[1].sourceKeys, [prefix+"raw.json",prefix+"b.json",prefix+"missing.json"]);
});
