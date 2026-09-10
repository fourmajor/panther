# Audio, transcripts and asset connections

Choose a game, then **Audio** or **Transcripts**. Both sections use existing private immutable
assets; no conversion, generation, transcription or new workflow is started by browsing.
Audio opens an original FLAC recording as an ordered part playlist. It requests a fresh private
link for each part, stops on navigation, and offers part reselection on expiration/playback failure.
Chunk boundaries may briefly pause; browser codec support varies. Original downloads remain available.
Loose audio files without a recording manifest are listed separately, including music.

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
