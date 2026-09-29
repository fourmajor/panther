# TV episode library

The Videos section offers a separate TV episodes view. Series, seasons and episodes are
structured private organization records, not generated files or public sharing grants.
Normal video browsing remains available if episode organization cannot load.

Use `panther videos series` or `panther videos episodes` with `--game GAME` to list records.
Add `--id ID` and optionally `--revision REVISION` to read an exact saved organization revision.
Use `panther videos save-series /private/path/series.json` and
`panther videos save-episode /private/path/episode.json` for changes. Keep actual manifests
outside Git. The plural `videos` commands organize media; the singular `video` commands
control separately authorized paid production.

## Guarded records

Both write envelopes require `gameId`, `id`, `title`, `synopsis`, `reason`, `operationId`
and `expectedRevision`. Use null for an initial revision, or the exact current 32-hex
revision when editing. Retain the operation identity and identical complete request for
uncertain-response retries. Changed arguments with the same operation identity are rejected.
Current-pointer changes, immutable history and retry receipts commit atomically.

Series additionally require `seasons`: one to thirty records with `id`, positive integer
`number`, `title` and `synopsis`. Season IDs and numbers must be distinct. Previously
declared season IDs cannot be removed by editing, preventing orphan episodes.

Episodes require:

- `seriesId`, `seasonId`, positive integer `number` and `status` (`draft` or `approved`).
- `cuts`: one to ten records containing `id`, `title`, exact immutable `assetKey`,
  `durationSeconds` and `durationEvidence`. Unknown duration and evidence are both null.
  Known durations need explicit evidence; the UI labels them reported runtime.
- `selectedCutId`, identifying one declared cut.
- `posterAssetKey` (nullable), `captionAssetKeys`, `credits`, `sourceAssetKeys`,
  `relatedAssetKeys` and `preparationAssetKeys`, including empty arrays where appropriate.

Cuts must be finished same-game videos. Posters must be supported browser images no larger
than 8 MiB. Captions are declared WebVTT exports no larger than 512 KiB. Credits contain
`role` and `name`; record only supplied or substantiated credits. Sources and related assets
must be finished same-game assets. Preparation references remain separately labeled and
do not become ordinary finished Inputs/Outputs. Organization references do not rewrite a
video's immutable derivation evidence. Private approval is not canon approval, publication,
spending approval or authority to generate anything.

An episode number is unique within its series and season. Renumbering releases only that
episode's previous slot in the same guarded transaction. The selected exact cut, captions,
poster and references are checked against indexed metadata before saving. Missing references
are reported on viewing; no replacement cut or inferred association is substituted.

## Reading and playback

Series pages group episodes by season and number. Episode pages expose cut selection,
credits, source sessions, finished references, separate production preparation and previous
organization revisions. URLs pin the organization revision. Previous/next navigation opens
the next cut paused, never autoplaying it. Official caption selection does not automatically
apply the official cut's captions to an alternate cut.

## Deployment

CDK supplies JWT-protected routes and narrow permissions on existing on-demand tables.
There is no always-on compute, S3 source scanning, public publication, generation trigger or
new capability assignment. Existing media receives no guessed series/episode assignments;
there are no older typed episode records requiring conversion. Deploy the merged stack and
complete the catalog-v3 all-game rebuild, verification and activation before declaring the
production library upgraded. Keep migration reports and private inventories outside Git.
