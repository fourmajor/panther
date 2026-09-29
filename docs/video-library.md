# Private video library and ordered collections

Videos is a shared library for episodes, experiments and playful derivatives, not another top-level
tab. Cards use recorded titles, descriptions, dates, tags, character IDs and creator text. Category
comes from the existing metadata contract: playful derivative, creative reimagining, grounded
adaptation, canonical source, reference or unclassified. Appearance, filenames, collection membership
and generation success never establish canon or creator identity. Missing facts stay unknown.

Search/category/tag/character controls filter **loaded** catalog pages. The display states that limit;
Load more fetches another bounded page rather than silently scanning source S3. Chosen collection
members are fetched by exact immutable index keys, even when absent from the initial library page.
Selected preview imagery uses the existing `extra.preview` same-game reference, batched image links
and bounded link caching. Filtering does not reauthorize every thumbnail. Missing images do not
prevent opening videos; an explicit retry refreshes their links. No image inference is triggered.

## Ordered collections

`VideoCollection` schema version 1 is structured private application data in the on-demand catalog
table. It contains gameId, slug id, name, description, ordered distinct assetKeys (1–50), revision,
previousRevision, updatedAt and actor. Referencing a video does not edit it or its provenance/review.
Saving uses a CAS transaction against the previously observed collection revision and indexed
members, plus immutable revision history and an idempotency record. Every referenced member must
be a current same-game indexed video. Exact retries retain the operation identity and arguments;
conflicts require inspection. Reusing an operation identity with different arguments is rejected.

Create a private JSON file outside Git with `gameId`, `id`, `name`, `description`, `assetKeys` and
`expectedRevision` (null only for initial creation). Then:

```sh
panther videos collections --game example-game
panther videos collections --game example-game --id favorites
panther videos save-collection /private/path/collection.json --operation-id 32_HEX
```

The CLI prints the operation identity before sending it; retain it for uncertain-response retries.
Existing collection edits require the exact current revision. Lists are paginated; the web app
offers Load more collections and the CLI follows scoped cursors. Membership lookup uses batches
of at most fifty exact metadata reads. Throttled/unprocessed reads fail explicitly, not as guessed
missing videos. Truly unavailable members are reported without substitution and retained in the
saved collection. Combined member metadata has a 4 MiB delivery limit; oversized collections fail
explicitly instead of exceeding the API response limit or discarding source links. Use a smaller
collection when that limit is reached. Previous/next playback preserves the available member order,
without autoplay.

## Posters and captions

An optional selected poster uses existing `extra.preview.imageKey`; absent selection means no
poster, not a guessed image from similar filenames. The same behavior applies to all old/new assets.
Separate WebVTT exports are associated only by direct same-game source links or the same immutable
asset identity/export directory, not by shared characters, titles or upstream provenance. The reader
offers the recorded exports and their original asset pages. Selecting one loads at most 512 KiB
with bounded streaming, verifies the WebVTT header and attaches an editable browser caption track.
It does not invent a language/author, strip uncertainty or assert human verification. Missing or
invalid captions leave video playback usable; burned-in subtitles remain part of the original.
Local caption object URLs are revoked on preview close/replacement. CDK permits media blob URLs
for that bounded caption delivery; credentials and arbitrary artifact URLs never enter tracks.

Novels can explicitly reference a collection using a typed same-game reader target
`{"type":"collection","id":"favorites"}`. Only an existing same-game collection resolves; unknown,
cross-game or conflicting references stay plain text. Summaries use the saved description or a
labeled count, not invented facts or a guessed first-member image. Metadata-only lookups do not
fetch member assets. Enrichment leaves the manuscript/clean export untouched; preview failures
leave the link usable. No inference runs when following or hovering over the reference.

## Deployment and existing data

CDK owns JWT routes, narrow DynamoDB write/condition-check grants and the caption CSP. Existing
publisher capability remains unchanged; no public bucket, new role assignment, paid inference,
always-on server or automatic generation is added. Sign-out clears transient collection state.
This uses existing asset metadata/index fields, not a new asset standard with legacy exceptions;
all existing videos get the same read-time presentation. No source files are altered. The new
collection data type has no earlier records to migrate. The catalog-v3 all-game rebuild,
verification and activation must complete before production browsing is declared upgraded.

Structured series, seasons and episode editions are documented in [TV library](tv-library.md).
