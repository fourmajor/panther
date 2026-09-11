# Game visual style

Each structured game stores `visualStyle`, an identifier selected from the API's
`visualStyles` catalog. New games default to `photorealistic`. The web game toolbar
provides a Visual style dropdown with an explicit Save action. Updates require Panther
authentication, compare the previous value to prevent stale writes, and preserve an
immutable change record. They do not change rulesets, rosters or existing assets.

Presets: Photorealistic, Anime, Illustrated fantasy, Comic book, Watercolor,
Oil painting, Stylized 3D, and Pixel art. These are provider-neutral visual treatments,
not genres, artist impersonations or model selections. The concise selection is based
on [Adobe's documented style categories](https://developer.adobe.com/firefly-services/docs/firefly-api/guides/concepts/style-presets/)
and [Midjourney's photographic/anime distinction](https://docs.midjourney.com/hc/en-us/articles/33329788681101-Website-Overview),
reviewed September 11, 2026. This adds no paid provider integration.

## Production contract

Before preparing new visual assets, fetch `panther game show GAME`. Apply the selected
style's prompt guidance from `visualStyles` and record the selected identifier in the
preparation document. Identity references supply faces, clothing and equipment; their
rendering style must not override the game's chosen style. Photorealistic means plausible
live-action anatomy, lighting and materials, including when references are illustrations.
The editorial context stage already snapshots the complete game catalog for each job.
Pinned jobs retain that snapshot; a style change is not permission to restart or spend.

Uploaded originals and previous generated revisions remain intact. A style change guides
future generation, not retroactive transformations. Regeneration creates a new revision
with exact original input references. Actual generation model and cost remain separate
metadata, not inferred from visual style.

## Version 1 rollout

After deploying, inventory every game with Panther authentication. For each existing game
with no `visualStyle`, select the owner-directed style and run:

```sh
panther game set-style GAME --style photorealistic --if-unset
```

For deliberate changes use `--expected-style PREVIOUS` instead. The API refuses missing
structured headers and conflicts. Save the before/after inventory outside Git and verify
every game has a supported persisted style. Re-running skips already compliant games;
never replace an existing choice as part of initialization. There is no read-time default
for missing old records. Account/game identities and rollout reports stay out of Git.
