# Asset versions

Each upload is immutable. A content revision is a **new asset**, never an overwrite or an S3
object-version change. `metadata.extra.version` is the version-1 contract:
`{schemaVersion:1, seriesId, number, previousKey?}`. First versions have number 1 and no
predecessor. The upload API assigns a deterministic series ID for a new asset; a later version
supplies only the predecessor key using `panther upload --new-version-of KEY`. The server derives
the series and next number, validating game and kind. Source lineage (`sourceKeys`) is separate:
a revised asset need not be derived from the prior bytes.

Character appearance selection is independent. Publishing an official portrait or web model creates
an immutable paired selection before conditionally changing its activation. The character page
reads structured history and lets a viewer inspect exact prior pairs without changing the current
selection. A candidate upload is not official until published. See `character-appearances.md`.

For pre-existing assets, `panther assets version-plan --output PRIVATE_PLAN.json` inventories
all games and complete typed appearance history. It preserves existing explicit semantic families
and verifies their predecessors. Missing version records become singletons: physical-state
membership or selection-record order cannot establish content revision lineage. Previously
established families are not renumbered or regrouped. Inspect the private plan, run
`panther assets migrate PLAN --report PRIVATE_DRYRUN.jsonl`, then `--apply` with a new report.
Run `panther assets rebuild-index --mode apply` and `--mode verify` with private reports; verify
all catalog records have version metadata. Do not claim rollout complete until that all-game
backfill and verification succeed. Source bytes, old metadata revisions and provenance remain
retained; plans and game inventories never enter Git.

The media asset page lists other records in its version series. This lookup shares the bounded
complete-game catalog load used for relationship links, with its existing 5,000-record cap; no
read-time S3 scan is permitted. If growth makes that cap insufficient, introduce a new versioned
DynamoDB projection and all-game rebuild before removing the cap. Never display an incomplete
list as complete.
