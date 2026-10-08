# Film delivery retrospective

## Failures and required changes

- Final review used one frame per second after source review used four. Short impacts and
  cork-release transitions were missed, and contradictory findings stopped delivery. Workflow
  version 3 uses four frames per second for the assembled movie and carries the actual selected
  footage reviews as attributed evidence. These are not automatic passes. A disputed interval
  needs denser actual delivery frames before recommending replacement, not repeated full renders.
- Preparation and footage certification were conflated. Preparation checks the visible pose and
  feasible action, not nonexistent future footage. Preserve the existing phase-specific review
  instructions and regression tests. A claw-shaped starting image cannot reliably become intangible
  smoke merely through negative prompting: repair and review the plate first.
- Exact opening-frame pixel compliance was treated as more important than coherent story action.
  Accept a crop only through a new editorial selection and independent review, retaining original
  failed request compliance. Lost cast, changed props and weapon swaps still fail.
- No spoken dialogue was planned, and each prompt explicitly excluded it. Native sound cannot
  produce an unplanned screenplay. Before approval, state dialogue/narration/music/effects intent
  explicitly, show the actual words and speakers, and disclose omitted components. Premium voice
  production remains separately authorized; never invent cloned voices or silently add spending.
- Repeated local one-off coordination left failures hidden behind append-only historical logs.
  Use durable receipts, the current attempt and a terminal publication outcome. Notify on a stopped
  process immediately; never report process presence or generation completion as movie delivery.
- A spending ceiling was confused with a quality-iteration allowance. Keep original charges,
  exact retry approvals and uncertain reservations. Inspect a representative high-risk take first.
- Owner acceptance and AI review are different facts. An owner can explicitly accept an imperfect
  exact cut as final. Record that decision separately, preserve failed review evidence and prior
  versions, and never change `visualReviewPassed` to true. This is not a standing quality override.
- Delivery estimates excluded preparation, review, encoding and upload. Estimate those phases
  separately from generation, report missed deadlines promptly, and provide an inspectable actual
  assembly without mislabeling it quality-passed.

Do not reconstruct historical dialogue, approval, billing or provenance. These lessons apply to
future production; immutable existing outputs and failed reviews remain preserved.

## Implementation status

Version 3 implements denser final review with selected-footage evidence, structured preparation
sound disclosure, and checksum-pinned explicit owner acceptance without rewriting AI review.
Regression tests exercise normal failure blocking, accepted imperfect publication, unchanged
review bytes, immutable revisions and retry conflict guards.

The end-to-end durable coordinator, immediate terminal-stop notifications, phase estimates and
browser presentation of sound intent remain tracked in [issue 206](https://github.com/fourmajor/panther/issues/206).
They are not claimed fixed by the local workflow changes above.
