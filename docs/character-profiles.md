# Structured character profiles

Character entity schema 2 adds revisioned details (schema 1) in the private DynamoDB
catalog. It does not change Character identity, Player membership, or official artwork
selections. Character browsing reads bounded metadata pages, not S3 profile scans. Load
more remains visible when another page exists. A game roster over 500 records fails closed
rather than displaying a partial roster as complete.

Details hold aliases, pronouns, role, status, subtitle, overview, backstory, notes,
statistics, relationships, and a selected thumbnail. Unknown text is null; unknown lists
are empty. Statistics have group, name, and text/finite-number/boolean/null values, without
hard-coding a game system. Relationships explicitly target existing same-game Character,
Player, or immutable Asset records. Future entity kinds require extending the typed resolver;
arbitrary URLs and guessed connections are rejected. Ownership remains a Player membership
fact, not a login identity.

The web editor provides text fields and typed statistic rows, an advanced connections JSON
field, and thumbnail choices from explicitly character-tagged images. The thumbnail does not
replace the official portrait. Media groups show actual kinds and recorded categories, with
Unclassified for missing classification. New media kinds remain visible. Downloads, asset
versions, source lineage, and the existing appearance viewer retain their shared contracts.
Named paired physical appearances remain separate work in #37.

## Guarded editing

`panther character list --game GAME` follows all bounded pages. `panther character details
--game GAME --character CHARACTER` returns current facts and a revision. Use the web editor
or `panther character edit-details /PRIVATE/edit.json` with a complete envelope containing:

- gameId, characterId, mode `edit`, and the complete details document returned by the read;
- expectedRevision from that read, expectedSourceHash null, and a new 32-character lowercase
  hexadecimal operationId;
- a factual change reason and dryRun false.

Every transaction retains immutable history, previous facts, actor, reason, and any explicit
source evidence. Stale revisions return 409. Reconcile after reloading, never blindly overwrite.
Keep the exact body and operationId after an uncertain result: replay is idempotent and returns
the operation revision and current facts (which may have changed since that operation).
Different content under the same operationId is rejected.

Create-only artwork publication is separate. It initializes only unknown summary/subtitle/
thumbnail facts. Its response includes `detailsSynchronization`; inspect a reported conflict
and explicitly reconcile current facts. It does not roll back the published original or silently
replace newer facts. Never retry profile creation as an overwrite.

## Deployment and all-game migration

Review a private CDK diff for the intended account/us-west-2 before deployment. Deployment
and backfill are completion gates. No legacy fact reader or source-scan fallback is supported.
Use Panther authentication, not ad hoc AWS writes. Migration endpoints require the existing
private ASSET_MIGRATORS capability; regular edits use catalog-editor permissions. Formal
application roles are separate work.

```sh
panther character prepare-details-migration --plan /PRIVATE/character-plan.json
panther character apply-details-migration /PRIVATE/character-plan.json --report /PRIVATE/character-apply.jsonl
panther character verify-details-migration --report /PRIVATE/character-verification.json
```

Plans/reports are create-only, mode 0600, forbidden in Git checkouts. Preparation enumerates
every discovered game, registered character, and existing artwork-profile prefix. This bounded
source inventory is maintenance-only. Unregistered games/orphan profiles, conflicting facts,
unsupported old stats, invalid references, and unavailable selected thumbnails are blockers,
not legacy exceptions. Missing artwork can still yield a valid roster-only migration.
A game header may retain `legacy: true` after a character is explicitly registered. The
all-game inventory accepts that historical flag only when a nonempty structured roster exists
and every artwork profile belongs to a registered character; it never infers a roster from files.

Dry runs do not write. Plans pin serialized roster facts and artwork ETag/version/SHA-256;
application rechecks observed sources and refuses changed plans. Transactions preserve the
complete original catalog record, source evidence, and migration revision. Artwork bytes,
semantic asset versions, selection history, and workflow checksum pins are untouched.
Apply durably records a pending operation before each request and its result afterward. It
stops on failure. Retry the original plan into a new report using the same operation identities.
Verification re-enumerates all games/profiles, validates facts and references, and checks
migration history. Resolve blockers privately and verify the full inventory before closing #23.
