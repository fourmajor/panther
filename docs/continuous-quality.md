# Continuous end-user quality

The owner must not be Panther's primary bug detector. Source tests, deployed frontend checks,
private production-data checks and visual review are distinct evidence, not substitutes.
An HTTP 200 or downloaded file does not establish that users can find and read/play it.

## Daily execution and failure ownership

`ci.yml` runs every day at 12:00 UTC on reviewed default-branch source, and manually on reviewed
`main`/`codex/` branches. Both jobs use the existing restricted, owned Docker runner. No hosted
runner, private credentials, paid inference, automatic merge/deploy or PR/fork execution is enabled.
The workflow is serialized and has explicit deadlines. Schedules only activate from the default
branch; merging the workflow and observing its first main run are rollout requirements.

1. `test` runs Python, React and infrastructure checks, then the critical reader/session journeys
   before the full browser suite and synthesis. Broken core journeys fail early rather than
   waiting behind hundreds of unrelated tests. This smoke gate never replaces the full suite.
   Infrastructure tests also compare every catalog-consuming IAM scope with the actual runtime
   catalog version/sections, including archive removal from Sessions. A migration must not pass
   source reader tests while leaving write/selection guards pointed at an obsolete partition.
2. `deployed-journeys` runs on nightly/manual main checks even when source tests fail, or when
   explicitly dispatched with `suite=deployed` (live checks only) or `suite=full-and-deployed`
   (both source and live checks) for post-rollout verification of a reviewed branch.
   Ordinary pre-merge branch CI does not compare unpublished web bytes to production (which would
   make every frontend PR impossible to merge). It reads real public HTML/JS/CSS/CSP,
   verifies script/style hashes against reviewed source, then runs desktop/mobile journeys with
   synthetic API/media fixtures. It blocks unmodelled requests and production mutations. Storage
   responses forbid framing, reproducing blank-text-preview failures.
3. The daily quality audit checks both jobs, last completed main run, queue/runner state, failed
   artifacts and flakes. More than 36 hours without a completed main run, an offline runner,
   timeout or skipped job is a coverage failure, not a green health report. New failures require
   sanitized reproduction and tracked follow-up. Deduplicate unchanged failures. Recovery requires
   a passing rerun, not simply closing an issue.

GitHub's normal workflow notifications follow account notification preferences. The daily audit
adds user-facing triage. CI tokens remain read-only and cannot file issues or deploy. Weekly
research is not a substitute for quality checks and its paid testing remains separately gated.

## User-story coverage matrix

| User story | Source browser coverage | Deployed coverage / explicit boundary |
| --- | --- | --- |
| Find sessions and read original/corrected transcripts | `session-library`, `end-user-audit` | Synthetic Sessions navigation/corrected reader; real catalog audited privately |
| Read and download text preserving line breaks | `end-user-audit` | Native text reader, literal HTML, wrapping, keyboard focus; no iframe |
| See usable portraits, videos and audio | `assets-browser`, `viewer`, `episode-playback` | Decoded synthetic image pixels; real private audiovisual content not claimed |
| Review a storyboard before spending | `movie-review`, `editorial-creation` | Source suite only; never click a real paid action in an audit |
| Understand stages, failure details and review requests | `workshop`, `notifications` | Source suite; actual workflow state checked privately |
| Read chapters and character previews | `novel` | Source suite; selected production chapter existence checked privately |
| Inspect appearances and older models | `character-details`, `appearance-history`, `viewer` | Source suite; actual model visual quality remains separate |
| Sign in/out, settings and notifications | `auth`, `account-settings`, `notifications` | Synthetic contracts do not establish production authentication |
| Use mobile/keyboard controls and recover from errors | Desktop/mobile cases throughout suite | Changed screenshots require primary-agent review |
| Receive the current website after updates | `web-release` | Actual public HTML/script/style hashes, not a guessed release label |

This matrix identifies boundaries, not a claim that every journey is verified in production.
Extend it and add failure regressions when introducing workflows or fixing reported defects.

## Private-data audit and release gate

Use existing Panther authentication on the trusted host for bounded read-only game, session,
transcript-selection, asset-document and workflow checks. Verify real content/readiness, not
process presence. Keep credentials, speech, identities, private inventories, embeddings and
game screenshots out of CI/issues/artifacts. Use private checkpoints and sanitized fingerprints.
Expired authentication requires action, never a bypass. Label API/data checks honestly.
Full authenticated production browser coverage needs a separately provisioned least-privilege
test identity and synthetic production fixtures; this change does not configure those. Do not
copy owner tokens into CI or create a privileged test account to make checks pass.

For each frontend repair: preserve the failure, add its regression, pass current-SHA self-hosted
tests, inspect desktop/mobile screenshots, review the diff and only then merge. Deployment needs
a fresh reviewed CDK diff and required migrations. Re-run deployed journeys after rollout and
separately verify the intended authenticated source. No success claims while rollout is pending.

Rotate deeper adversarial stories in daily reviews: blank/blocked media; expired URLs; 429/503
and bounded retry; lost sessions; later-page discovery; missing metadata; long/Unicode/inert-HTML
text; cross-game references; back/reopen position; mobile overlays and keyboard focus. Assert
observable content and action availability. Never manufacture completed jobs, names or media.

## Running and rollback

Dispatch the reviewed branch's `ci.yml` and shepherd the exact SHA. `npm run test:deployed` runs
inside the owned runner, not the laptop host or a personal browser. Seven-day artifacts
`browser-test-results` and `deployed-journey-results` contain synthetic screenshots only.
Inspect rendered output rather than relying solely on DOM assertions. Release mismatch is
rollout debt, not permission to mask the check or deploy automatically.

Removing the schedule disables recurring execution while preserving manual checks and evidence.
Never suppress an actual failing journey as a rollback strategy.
