import assert from "node:assert/strict";
import test from "node:test";
import {recapInputs} from "../web/ui/src/session-record.js";

test("detail recap uses the same excerpt as the Sep 10 list card", () => {
  const card = {
    excerptKey: "games/example/assets/corrected.json",
    excerptLabel: "Excerpt from the corrected transcript",
  };
  const shell = {excerptKey: null, excerptLabel: null, title: "The Kitchen That Remembered — Five Against the Fire"};
  const full = {
    excerptKey: "games/example/assets/novel-chapter.json",
    excerptLabel: "Excerpt from the novel chapter",
    title: "Curse of the Crimson Throne — The Story So Far",
  };
  const listed = recapInputs(shell, card);
  const detailed = recapInputs(full, card);
  assert.equal(Boolean(listed.excerptKey), Boolean(detailed.excerptKey));
  assert.equal(listed.excerptKey, detailed.excerptKey);
  assert.equal(detailed.excerptKey, card.excerptKey);
  assert.equal(detailed.excerptLabel, "Excerpt from the corrected transcript");
});
