# Named character appearances

Stage one for issue 37: structured metadata and guarded migration tools. This is not a
claim that production has migrated or that the viewer has switched contracts. CDK sets
`APPEARANCE_WRITES_ENABLED=false`: reads and migration planning are available, but publication,
import and activation endpoints fail closed. Existing producers/readers remain unchanged.
The follow-up cutover must remove their mutable-profile write permissions, wire the new
contracts into those consumers, run the all-game migration, and then remove this temporary
staging flag. Never enable it through a manual Lambda configuration change.

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

## Required cutover gates

1. Deploy read-only legacy maintenance access and new structured APIs; prevent legacy
   mutable-profile publishers from continuing to change the old source of truth.
2. Prepare private all-game plans covering every registered character, current profile and
   retained profile snapshot, with exact byte hashes and source revision evidence. Orphans,
   unreadable sources and unresolved associations are blockers, not exemptions.
3. Import explicit selections into unknown-story-state records unless an existing source
   substantiates a named state. Preserve complete source bytes/evidence and old immutable
   assets. Do not infer transformations from appearance similarity, upload order or filenames.
4. Activate the exact imported current pair only after its complete history is verified.
   A source change invalidates the prepared plan. Roster-only characters remain explicitly
   without selected artwork, not a fabricated appearance.
5. Verify every game and remove old read/write paths. Browser history must query bounded
   structured metadata, never scan or individually open every S3 profile snapshot.
6. Update model-reference jobs, publication commands, version-family maintenance and editorial
   appearance pins to consume the same selection contract. Keep workflow checksum pins and
   original derivation evidence intact.

Infrastructure belongs to CDK; record storage uses existing on-demand tables. Game files,
manifests, inventories and migration reports remain outside Git. No paid inference or
always-on compute is introduced by appearance organization.
