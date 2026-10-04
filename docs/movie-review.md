# Retained movie-review artifact contract

The prototype application now reviews scene-owned storyboards inside Episodes.
See [Episode production](episode-production.md). The former standalone movie-review
workspace and dashboard inbox are removed. The following documents the retained
immutable artifact/review service; it is not an application destination.

## Data and publication

Upload a private JSON document through `panther upload --kind movie-review-plan`, using immutable
asset revisions and `extra.relationshipRole: intermediate`, `extra.contextUse: exclude`. Supply
known `sessionId`, character IDs, sourceKeys and factual generation metadata. Plans are creative
adaptations, not canonical-source transcripts. The artifacts remain in the game-scoped catalog and retain their original provenance. Existing video files are not rewritten.

Version 1 document fields:

Campaign-wide plans explicitly use `scope: campaign` and `sessionId: null`; session plans
retain their real session identifier (`scope: session` is optional). This additive contract
does not invalidate existing plans or require inventing sessions. Optional shot `narration`
and `footagePlan` plain text appear on the storyboard cards and in the inspector. Distinguish
new motion, reused clips and still-image treatments, including their individual durations.
Optional `narratorSampleKey` references a separately uploaded same-game audio audition in
`sourceKeys`; it links to the asset player without autoplay or embedding a narrated slideshow.
Neither a scratch narrator nor an animatic replaces a requested storyboard review.

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
