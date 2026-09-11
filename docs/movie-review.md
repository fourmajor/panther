# Movie review workspace

Open **Videos**, then a movie plan. A stable link is
`/games/GAME_ID/videos?project=URL_ENCODED_ASSET_KEY`. The storyboard, screenplay, pinned cast and
source assets share one workspace. Selecting a shot shows camera, continuity, dialogue, model
rationale and warnings. Check shots as reviewed and save shot-specific change requests. Notes stay
in memory until saved; copy unsaved notes before navigating away. The screenplay never includes
review notes. Missing images have labeled placeholders, not fabricated storyboards.

The owner can explicitly approve an exact revision only after reviewing every shot and clearing
all blockers. Other configured publishers can read and request changes. This uses existing
deployment-supplied publisher/worker capabilities, not invented member/admin roles or player roles.
Approval has a separate confirmation and records a USD ceiling including retries. The server
rechecks content hash, prior review ID, all shots, current quotes, cost ceiling and source assets.
Unknown cost is not zero. Missing starting frames, explicit blockers and quotes older than 24 hours
prevent approval. A new plan's bytes have a new hash and cannot inherit an old approval. Decisions
and comments have immutable audit rows; requesting changes replaces the current approved state.

**No button generates media.** This service has no provider credentials, billing integration,
workflow dispatch or paid adapter. Approval is an owner decision for a later, separately guarded
generation step, not a spend reservation. Before acting on it, the local operator must fetch the
current review for the exact plan, verify the approved hash/content/ceiling, refresh provider pricing
and prepare the same shots/references/models in `panther video`. Its existing plan approval, rights,
lifetime ledger and per-project cap still apply. Changed content or costs require a new review plan
and approval; do not reinterpret approval as authorization for a different executable manifest.
There is no automatic synchronization with the paid executor yet.

## Data and publication

Upload a private JSON document through `panther upload --kind movie-review-plan`, using immutable
asset revisions and `extra.relationshipRole: intermediate`, `extra.contextUse: exclude`. Supply
known `sessionId`, character IDs, sourceKeys and factual generation metadata. Plans are creative
adaptations, not canonical-source transcripts. The page discovers all existing plan assets through
the same game-scoped catalog; it does not hard-code a campaign or invent a movie from unrelated clips.
Prior plans remain available as separate cards. Existing video files are not rewritten.

Version 1 document fields:

- `schemaVersion: 1`, `entityType: MovieReviewPlan`, `gameId`, `projectId`, `revisionId`, `sessionId`.
- `title`, `summary`, `screenplay` (safe prose Markdown), `sourceKeys` (same-game immutable keys).
- `characters: [{id, name, portraitKey}]`; portraits must also occur in `sourceKeys`.
- `budget: {currency: USD, capUsd: decimal string, pricingCheckedAt: Unix seconds or null, notes}`.
  Record an actual, evidence-backed quote check time, never today's time merely to unlock approval.
- `shots`: 1–20, at most 30 seconds each / 300 seconds total. Each has `id`, `title`, `description`,
  `camera`, `continuity`, `model`, `modelReason`, `durationSeconds`, `characterIds`, `referenceKeys`,
  `frameKey` (null while missing), `costUsd` (decimal string or null), optional `dialogue`, and
  `warnings: [{severity: note | blocker, message}]`. Reference/frame keys must be in `sourceKeys`.
  Frame is a full starting composition; a portrait is not a substitute. List uncertain speaker,
  source or continuity decisions explicitly as blockers, not invented certainty.

The `movie_review.validate` function is the authoritative bounded validator. GET `/movie-review`
with gameId/key returns the plan, SHA-256, derived readiness and latest review. POST to the same
route supplies gameId/key/sha256, `expectedReviewId` (null initially), `action` (`changes-requested`
or `approved`), `comments: [{shotId, text}]`, and for approval the exact `capUsd` and complete
`reviewedShotIds`. Conflict returns 409; reload and preserve notes, never blind overwrite.

## Infrastructure and verification

CDK owns a retained pay-per-request review table and short-lived Lambda in the existing regional
stack. There are no idle pollers, NAT gateways, additional secrets, or provisioned compute. Reviews
are private application data, never Git fixtures or CI artifacts. JWT authentication is mandatory;
least-privilege permissions only read source assets and get/put review records.

Backend tests cover authorization, game boundaries, stale reviews, immutable revision binding,
unknown prices, stale quotes, missing frames and over-budget approval. CDK assertions prohibit
generation/workflow permissions. Self-hosted Playwright tests exercise desktop/mobile layout,
safe screenplay rendering, review persistence, explicit approval confirmation, conflict handling,
game switching and blocked plans. Only fictional assets are used in those tests.
