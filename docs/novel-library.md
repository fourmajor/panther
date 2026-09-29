# Private stories, books and reading editions

Chapters remain immutable editorial assets. Organization is separate structured application data
in the retained on-demand catalog: `NarrativeStory` and `NarrativeBook`, schema 1. No new S3 paths,
manuscript edits, paid generation, public sharing or provisioned compute are needed.

A story has an explicit title and synopsis. A book belongs to an existing same-game story and has
title, synopsis, nullable authorship credit and selected cover, creative classification, private
`draft`/`approved` status, book order, ordered volumes and exact immutable chapter keys. A volume
has an ID, title and chapter order. Limits are ten volumes/forty chapters per book and ten explicitly
related finished assets. Covers must be indexed PNG/JPEG/WebP/AVIF under 8 MiB. Related media can
include existing illustrations, narration, documents and video, not workflow internals.
Missing art/credits stay null; do not invent them.

Classifications are `grounded-adaptation`, `creative-reimagining`, `playful-derivative` and
`unclassified`. A grounded adaptation is not automatically canon. `approved` means an explicit
private reading selection, not public publication, AI review acceptance or source canon. Chapter
review status, generation evidence and provenance stay independent. New chapter editions never
silently replace pinned book selections.

## Panther operations

Run `panther instructions` before organizing actual game data. Keep manifests outside Git.

- `panther novels stories --game GAME_ID` and `panther novels books --game GAME_ID` follow every
  bounded page. `--id ID` selects one record; `--revision REVISION` reads immutable earlier history.
- `panther novels save-story /private/path/story.json` and `save-book /private/path/book.json`
  submit complete envelopes. Keep identical `operationId` and bytes for uncertain-response retries.
  Changed requests need a new operation ID; conflicts require rereading the current revision.

Common envelope fields: `gameId`, `id`, `title`, `synopsis`, `expectedRevision`, `operationId`
(32 hexadecimal characters), and descriptive `reason`. Creation uses null `expectedRevision`;
edits use the exact current revision. Books also require `storyId`, `authorCredit`, `coverAssetKey`,
`classification`, `status`, integer `order`, `volumes` and `relatedAssetKeys`. Every volume is
`{ "id": "volume-one", "title": "Volume One", "chapterKeys": ["EXACT_ASSET_KEY"] }`.
No field derives facts, identity, chronology or approval from filenames or upload dates.

Authenticated `/novel-stories` and `/novel-books` GET/POST writes atomically retain immutable history
and an operation fingerprint with a compare-and-swap current pointer. Book commits guard observed
source-index revisions, exact DONE editorial outputs and the parent story revision. Old operation
retries return the current record plus that operation's actual committed revision, not a new edit.
History is accessible by exact revision; the web offers previous-book-revision links.
The separate organization Lambda cannot mutate S3, editorial jobs, workflows or spend.

## Reader

The library displays stories, covers/synopses/credits, volumes, classification, approval and revisions.
Source session editions remain separately accessible, explicitly not an approved book order. Book
URLs pin the organization revision; unavailable chapters are reported, never replaced. Chapter
details retain sessions, review notes, immutable source lineage and generation evidence outside prose.
Reading position is local to this browser/device, scoped to the signed-in account and game. It records
immutable chapter ID, paragraph and approximate paragraph-based percentage, not manuscript text or
a claim of cross-device synchronization. Resume is explicit; refresh never jumps unexpectedly.
Another account does not see the previous account's position. Blocked storage reports a warning
without preventing reading.

## Rollout

Deploy through CDK after inspecting private account/region diffs. Complete catalog-v3 all-game
dry-run/apply/verify/activation in `asset-browse-index.md` before declaring readiness. Existing
chapters receive the same observed summary contract. The new organization types have no earlier
records to migrate; an unorganized source edition is a valid current state, not a legacy exception.
Do not invent book membership, approval, cover or chronology to populate them. Create explicit
reading arrangements through guarded operations when actual context supports them. Verify deployed
source chapters, private draft/approved selections, history, covers, keyboard/mobile navigation and
reading position before closing #17. Generated in-book illustrations remain separate work (#52).
