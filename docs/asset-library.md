# Audio, videos, transcripts and asset connections

**Videos** lists all actual video files in the selected game, regardless of kind: episodes,
comparison clips, and silly videos share the same browser player and provenance links.
Planning documents are not presented as completed videos. Browsing never starts paid generation.
Playback depends on browser codec support; the original file remains downloadable.

Character profiles show **Featuring this character**, covering every asset type and historical
version explicitly tagged with its ID in `metadata.characterIds`. Names, player identity and input
provenance do not imply an appearance. Untagged historical assets stay unassociated until explicitly
catalogued; this view does not invent tags or overwrite them. Refresh assets reloads the catalog.

Novel prose has quiet, dotted-underlined links that inherit the text color, with stronger hover and
keyboard-focus states. Exact, case-sensitive, whole-name mentions of current catalog characters and
unique asset titles link automatically. Duplicate titles/names remain plain text; no fuzzy matching,
first-name extraction or character-from-player inference occurs. This is a read-time navigation aid,
not a claim of historical identity, canon or derivation. Names spanning Markdown formatting boundaries
are left plain. Link enrichment never changes the manuscript or its clean download.

Optional `payload.readerReferences` on a novel JSON artifact can explicitly disambiguate a name or
associate an alias with a typed destination, separate from prose and editorial notes:

```json
{"schemaVersion":1,"mentions":[
  {"text":"the navigator","target":{"type":"character","id":"example-character"}},
  {"text":"the harbor chart","target":{"type":"asset","key":"games/example-game/assets/chart-a/original/chart.png"}}
]}
```

At most 200 mentions are accepted; each label is 2–160 characters. A mention applies to each exact
occurrence in a plain-text span, including emphasis, but not arbitrary Markdown links/code/HTML.
Only existing, same-game `character`, `asset`, and `chapter` targets resolve (chapter uses its job ID).
Optional target `gameId` must equal the selected game. Explicit references override automatic names;
conflicting explicit references stay unlinked. Unknown types and unavailable targets stay plain text.
Future entities extend the typed resolver registry when their data model and pages exist, not by
accepting artifact-supplied URLs. Existing chapters need no migration or regeneration for automatic
links. The current editorial worker does not yet generate optional alias annotations.
If the asset catalog is unavailable, the story remains readable with a visible retry notice.

Choose a game, then **Audio** or **Transcripts**. Both sections use existing private immutable
assets; no conversion, generation, transcription or new workflow is started by browsing.
Audio opens one continuous MP3 listening derivative produced by the completed-chunk-set
workflow. It has one source and timeline; part buttons seek within it instead of switching files.
Playback stops on navigation. Expired-link recovery restores the position in the same listening
file. Original lossless FLAC chunks remain unchanged under Inputs for download and reprocessing.
If the listening copy is not ready, the reader explains that completion and the laptop worker are
required; it never silently falls back to a gapped chunk playlist. Assembly cannot repair capture loss.
Loose audio files without a recording manifest are listed separately, including music.
Capture setup/checkpoint metadata is not a second recording: only structured Recording documents
with parts become session entries. Setup files remain accessible under Related files and Media.

Transcripts lists all raw, corrected and edited versions. When a JSON version has a matching Markdown
export, the section shows the structured reader once; its export remains under Related files.
Standalone Markdown versions are still listed. The JSON reader retains player identity, timestamps, original/correction annotations,
capture integrity and uncertainty. It renders text, never HTML supplied by an asset. A corrected
transcript is not presumed human-verified. This is a reader, not an in-place editing interface.

Every asset's preview has **Inputs** and **Outputs**. Inputs are its declared `sourceKeys`; outputs
are the reverse references found in the selected game's assets. Complete structured JSON can also
declare `inputArtifacts` (named references with `key`) and `rawReference`. Recording manifests
explicitly name their part files; raw PlayerTranscript documents identify their source recording.
Related files grouped under one asset ID are shown separately, never mislabeled as derivations.
Asset links are bookmarkable at `/games/GAME_ID/media?asset=URL_ENCODED_OBJECT_KEY`.

New derived assets must retain complete exact input provenance; outputs are derived rather than
written back onto immutable inputs. Historical absent links are not guessed or backfilled by this
change. Large provenance belongs in a separate structured JSON document when compact upload metadata
is insufficient. Existing editorial JSON already retains full `inputArtifacts` beyond compact metadata.

`GET /assets?gameId=...&cursor=...` lists 25 objects at a time, with at most eight concurrent storage
reads. JSON provenance parsing is capped at 2 MiB per object; larger/unreadable or foreign-game
documents show an incomplete-provenance warning. `GET /asset-document?gameId=...&key=...` returns
the bounded original document for the reader. Both require Cognito plus the current owner/DM
group policy and validate the selected game. No new access grants are added.

The browser caches a game catalog only in memory and follows every page before showing output
relationships; Refresh reloads it. A 5,000-object safety limit fails visibly rather than silently
showing incomplete reverse links. This initial read-time scan has request costs proportional to
game size, but no idle polling, database or always-on compute. A durable indexed relation catalog is
a future scaling improvement. Refresh after uploads to see new outputs. Missing explicit historical
provenance and unreadable documents can still leave output links incomplete; the UI says so.
