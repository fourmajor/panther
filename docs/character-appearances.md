# Named character appearances

The consumer cutover removes mutable-profile writes from normal publishers and initializes,
selects and views artwork through the structured contract below. The temporary global staging
flag is removed; per-character verified migration seals gate normal reads and edits instead.
This document describes the implementation, not a claim that production has migrated.
Do not deploy before preparing the private operational rollout; expect artwork reads to fail
closed between deployment and all-game verification, rather than showing mixed old/new data.

Character is a stable identity. A named Appearance is a physical state, distinct from an
artwork revision. It may be permanent, temporary, alternate or unknown. Its development
parent is immutable, preventing edits from creating cycles. Story timing uses separately
nullable sessionId, eventId and date; file upload time never supplies missing story time.

An AppearanceAsset association explicitly ties an immutable asset to a same-character
appearance. Declared conflicting appearance metadata is rejected. Association records are
immutable. An immutable AppearanceSelection pins a portrait, optional model and model source/
provenance, plus the exact appearance descriptor revision. Portrait-only selections never
borrow another appearance's model. Replacing either member creates a new selection.

AppearanceActivation is the separate guarded current pointer and append-only story history.
Returning to an earlier look reuses its exact selection while adding a new activation event.
Promotions recheck selected indexed sources and commit source/pointer conflict guards in the
same transaction. Private official selection does not imply public visibility or canonical
approval of generated details. Candidate uploads do not become current automatically.

## Operations

`panther character appearances`, `appearance-assets`, `selections` and `appearance-current`
take --game and --character. Associations also require --appearance. Add --id and optionally
--revision for exact record history. appearance-current defaults to id=current.

Save commands are `save-appearances`, `save-appearance-assets`, `save-selections` and
`save-appearance-current`, each taking a private JSON file. All envelopes require gameId,
characterId, id, expectedRevision, operationId and reason. Revisions and operation IDs are
32 lowercase hex characters; initial expectedRevision is null. Retain identical operation
requests for uncertain-response retries. History records and retries never overwrite assets.

Additional fields:

- Appearance: name, description, state, developedFrom (nullable), story.
- Association: appearanceId, assetKey; id is SHA-256 of the exact asset key.
- Selection: appearanceId, portraitKey, modelKey, sourceKey, provenanceKey. The last three
  may be null; a portrait-only selection has all three null. Associate each selected source
  explicitly first. Existing selections cannot be edited.
- Activation: appearanceId, selectionId, story; id must be current. The expectedRevision
  guards the current activation, not the asset or descriptor revision.

story is an object with sessionId, eventId and date, each nullable. Unknown stays null.

The web viewer queries bounded metadata history, then signs only the selected pair. Links
pin `appearance` and `selection`; a portrait-only edition clears the previously loaded model.
Restoration adds a guarded activation event and retains identical retry arguments. Selection
record timestamps are labeled as technical recording times, never fictional dates.

An exact deep link may preview a stored, unactivated selection. The viewer adds only that
server-resolved pair (and its pinned descriptor if needed) to its temporary controls, labeled
**Unselected preview edition**. It never adds an activation event, marks it official or promotes
other candidates into history. Switching between that preview and official editions stays
aligned with the displayed image/model; viewing/reloading never changes the current selection.

Existing `character set-model` and `set-portrait` commands use the exact 32-hex activation
revision returned by `character show`. They create a new immutable pair; no S3 profile is
overwritten. Explicit semantic asset versions are preserved separately: appearance ordering
does not justify regrouping or renumbering existing asset families.

New model-reference jobs pin appearance/selection revisions and exact portrait/model/source
keys, with explicit character/appearance metadata on each checksum-pinned reference. New
editorial context snapshots retain the selected pair rather than independent current images.
Historical workflow inputs and raw evidence must remain unchanged.

## Required cutover gates

1. Deploy read-only legacy maintenance access and new structured APIs; prevent legacy
   mutable-profile publishers from continuing to change the old source of truth.
2. Prepare private all-game plans covering every registered character, current profile and
   retained profile snapshot, with exact byte hashes and source revision evidence. Orphans,
   unreadable sources and unresolved associations are blockers, not exemptions.
   A historical `legacy: true` game header is acceptable only after explicit character
   registration; an empty roster or orphaned artwork still blocks the import.
3. Import explicit selections into unknown-story-state records unless an existing source
   substantiates a named state. Preserve complete source bytes/evidence and old immutable
   assets. Do not infer transformations from appearance similarity, upload order or filenames.
4. Activate the exact imported current pair only after its complete history is verified.
   A source change invalidates the prepared plan. Roster-only characters remain explicitly
   without selected artwork, not a fabricated appearance.
   Verification also checks retained S3 profile/history object versions against imported
   source bytes and records their exact version IDs. A version available only in S3 history
   without a corresponding byte-preserving snapshot is an explicit migration blocker;
   extend the importer to capture that evidence before cutover, never exempt or delete it.
5. Verify every game and remove old read/write paths. Browser history must query bounded
   structured metadata, never scan or individually open every S3 profile snapshot.
6. Update model-reference jobs, publication commands, version-family maintenance and editorial
   appearance pins to consume the same selection contract. Keep workflow checksum pins and
   original derivation evidence intact.

Infrastructure belongs to CDK; record storage uses existing on-demand tables. Game files,
manifests, inventories and migration reports remain outside Git. No paid inference or
always-on compute is introduced by appearance organization.

## New characters and empty artwork

The trusted game/character creation producers record an explicit versioned
`appearanceContractJson` genesis marker (`schemaVersion: 1`, `origin: created-current`).
These characters start in the current appearance contract with no selected portrait/model;
they require no historical appearance migration to read their profile or edit artwork.
Normal character-detail edits cannot add or change the genesis marker. An empty profile
returns null appearance/selection identifiers, an empty model object, and no activation
revision. Reading it does not scan legacy storage or create migration records.

Characters created before this producer change still require the authenticated appearance
migration, even when the UI currently shows no artwork. Do not infer an empty retained
history from a missing current selection. Prepare, apply, and verify the complete all-game
inventory with private files outside the repository:

```sh
panther character prepare-appearance-migration --plan /private/path/appearances-plan.json
panther character apply-appearance-migration --plan /private/path/appearances-plan.json --report /private/path/appearances-apply.jsonl
panther character verify-appearance-migration --report /private/path/appearances-verify.json
```

The existing verification/finalization operations cover empty histories too: they inspect
retained current and historical source versions, preserve the evidence, and commit an audited
completion seal only after the verified inventory is unchanged. A source with no corresponding
preserved snapshot blocks finalization. No direct storage writes or fabricated appearances
are needed. New characters may also pass through this same maintenance operation; their
explicit current-contract genesis remains unchanged.
