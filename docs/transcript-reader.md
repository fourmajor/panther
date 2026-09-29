# Session transcript reader

The authenticated Transcripts section groups saved raw/corrected/edited artifacts by their explicit
session ID. Cards show observed speakers, unassigned segment counts, semantic version and reported
review status from the v2 catalog. File timestamps are not inferred session dates. Missing facts
remain unavailable. A player's presence in a roster alone does not establish attendance.

The structured reader keeps every source line, capture warning and uncertainty visible. Search
highlights speech/player-name matches and provides keyboard Enter/Shift+Enter and previous/next
navigation without removing evidence. The session-version selector opens exact immutable assets.
Source navigation follows explicit same-game lineage to a single recording and a completed
continuous playback derivative. Timestamp buttons seek that audio, not independently replayed chunks;
missing/ambiguous lineage or unavailable listening copies never select a guessed recording.

## Canonical reading selection

A separate `SessionTranscriptSelection` identifies the exact version chosen for reading. No
designation means no canonical version, regardless of recency or AI-review success. This pointer
does not assert human verification, correct source text, approve facts or regenerate adaptations.
Reported review/publication states remain independent. The reader links a designated different
version and exposes a reason/acknowledgment form for authorized publishers.

`panther transcripts selection --game GAME --session SESSION` reads the pointer. Authorized
publishers use `panther transcripts select --game GAME --session SESSION --key IMMUTABLE_KEY
--reason REASON --operation-id 32_HEX` and, after the first selection, `--expected-revision 32_HEX`.
The CLI prints the operation identity before submission. Retain it and all original arguments for
an exact retry after an uncertain response. Conflicts require reinspection, never blind overwriting.

The JWT-protected routes use the existing private publisher capability, matching the current asset
reader authorization without expanding account access or hardcoding users. CDK grants scoped writes to pointer, immutable audit
history and idempotency partitions, plus a condition check on the transcript index. The transaction
guards the previously observed pointer and exact indexed asset revision, saving all records atomically.
Operation reuse with different arguments is rejected; an exact replay reports both its historical
operation and the current pointer, which may have advanced. Source assets never change.

## Rollout

This requires CDK deployment and the all-game v2 catalog dry-run/apply/verify described in
`docs/asset-browse-index.md`. Keep reports/private application identities outside Git. Do not mark
the upgrade complete before production migration and verification. No new paid inference, automatic
canonical choices or generation workflow is introduced.
