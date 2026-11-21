import assert from "node:assert/strict";
import test from "node:test";
import {formatTimestamp} from "../web/ui/src/format-time.js";

test("user-visible timestamps use 24-hour time", () => {
  const morning = formatTimestamp(new Date("2026-10-08T11:23:00Z"), "en-US");
  const evening = formatTimestamp(new Date("2026-10-08T23:23:00Z"), "en-US");
  assert.equal(morning, "Oct 8, 2026, 11:23");
  assert.equal(evening, "Oct 8, 2026, 23:23");
  assert.doesNotMatch(`${morning} ${evening}`, /\bAM\b|\bPM\b/);
});
