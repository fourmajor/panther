# Storyboard review navigation

Studio keeps the shared layout as the default. Design Atlas also offers five
deliberately different navigation homes: Chronicle (a facing-page campaign book),
Cinema (screening shelves), Production Board (Source / Make / Watch lanes),
Pinboard (oversized notes and a desktop bottom launch strip), and Explorer
(searchable entries with an inspector). Shared detail editors remain mounted;
these are distinct home architectures, not independent copies of every editor.
Open Design Atlas in the header or with Shift+D, preview, compare and keep.
Switching does not navigate away or discard unsaved edits.

## Storyboard approval

Each game's Dashboard, Sessions, Episodes and Workflows expose **Review & approve
storyboards**. Focused readers and editors retain their uncluttered layout. The dashboard and
Episodes list prepared `movie-review-plan` assets with session identity, a direct
review link, and the server's current approval/readiness state. A prepared plan
is not automatically an unapproved or ready plan. Unknown status is explicit.

Catalog reads remain bounded and paginated; finding another page is explicit.
Plan-status reads have at most four concurrent requests. No home projection
scans source storage. An empty page is not proof the entire game has no plans.
Sessions still in preparation link to Workflows rather than inventing a ready
storyboard. Recent session preparation runs appear separately, including explicit
failure and a direct run link. Missing progress remains unreported, not zero.
The existing exact-revision review and spending guards are unchanged.

Browser regression checks cover desktop and mobile first paint, game-scoped
review links, preparation status, and focused storyboard detail pages. Inspect
their rendered screenshots before merging visual changes.
