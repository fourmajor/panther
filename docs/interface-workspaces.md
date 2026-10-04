# Storyboard review navigation

The application uses the shared stable layout. Design Atlas and alternate
home shells were removed by the merged interface changes; they are not
restored by storyboard navigation.

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
