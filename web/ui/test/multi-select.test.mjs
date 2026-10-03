import { test } from "node:test";
import assert from "node:assert/strict";
import { matchingOptions, addSelection } from "../src/components/ui/multi-select-options.js";

const characters = [
  { id: "character-1", name: "Ronin" },
  { id: "character-2", name: "Maximus" },
  { id: "character-3", name: "Ronan" },
];
test("typing finds display names case-insensitively and Enter's first candidate excludes selections", () => {
  assert.deepEqual(matchingOptions(characters, [], "  RON ").map(item => item.id), ["character-1", "character-3"]);
  assert.deepEqual(matchingOptions(characters, ["character-1"], "ron").map(item => item.id), ["character-3"]);
  assert.deepEqual(matchingOptions(characters, [], "character-1"), []);
});
test("multiple selections are ordered, immutable and cannot be duplicated", () => {
  const initial = ["character-1"];
  const added = addSelection(initial, "character-2");
  assert.deepEqual(added, ["character-1", "character-2"]);
  assert.deepEqual(initial, ["character-1"]);
  assert.equal(addSelection(added, "character-1"), added);
  assert.deepEqual(matchingOptions(characters, added, "").map(item => item.id), ["character-3"]);
});
test("duplicate option identifiers produce one suggestion, and tags support label text", () => {
  const tags = [{ id: "canonical", label: "Canonical" }, { id: "canonical", label: "Duplicate" }, { id: "battle", label: "Battle" }];
  assert.equal(matchingOptions(tags, [], "").length, 2);
  assert.equal(matchingOptions(tags, [], "can")[0].label, "Canonical");
  assert.deepEqual(matchingOptions(tags, ["canonical", "battle"], ""), []);
});
