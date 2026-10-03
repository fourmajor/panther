# Interface workspaces

The original Studio stays available. Design Atlas previews five alternative
home architectures without reloading the route or remounting editors, recording
controls, playback, or model viewers. The saved selection is browser-local and
independent of a game's generated-media style.

| Workspace | Home structure | Interaction |
| --- | --- | --- |
| Chronicle | Facing contents and reading pages | Select a campaign chapter |
| Cinema | Featured screening doorway and horizontal shelves | Browse recent media |
| Production Board | Source, Make and Watch lanes | Follow the production path |
| Pinboard | Asymmetric connected collections and bottom launch strip | Explore numbered notes |
| Explorer | Searchable collection directory and inspector | Filter, select and inspect |

These are alternative navigation homes, not five independent implementations of
the same editors. Existing detail pages retain their shared behavior and each
shell's navigation. Home links are projections of the same bounded recent data.
Switching designs must preserve unsaved inputs and must not fetch game data.

## Storyboard approval

Every selected game exposes **Review & approve storyboards**. The dashboard and
Videos list prepared `movie-review-plan` assets with session identity, a direct
review link, and the server's current approval/readiness state. A prepared plan
is not automatically an unapproved or ready plan. Unknown status is explicit.

Catalog reads remain bounded and paginated; finding another page is explicit.
Plan-status reads have at most four concurrent requests. No home projection
scans source storage. An empty page is not proof the entire game has no plans.
Sessions still in preparation link to Workflows rather than inventing a ready
storyboard. The existing exact-revision review and spending guards are unchanged.

Browser regression checks cover all six homes at desktop and mobile sizes,
different structural elements, collection selection, game-scoped review links,
preference comparison/cancellation, and preservation of unsaved edits. Inspect
their rendered screenshots before merging visual changes.
