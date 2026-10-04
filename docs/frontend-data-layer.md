# Frontend data and components

The static explorer hosts React islands built from `web/ui`. Run `npm ci` and
`npm run build` in that directory after editing React sources. Commit both
generated `ui-runtime.js` and `ui-system.css`; CI rebuilds and checks those bytes.
CDK publishes them through the same content-addressed release as the explorer.
The bundle contains React, TanStack Query, TanStack Table, Radix Select, Lucide,
and Tailwind 4; it does not fetch dependencies from a third-party CDN.
Dialog compositions must follow the [shared dialog contract](ui-components.md).

`window.PantherUI` is the bridge for existing views. Every authenticated API read
uses the shared QueryClient: account identity, endpoint and sorted parameters
form its cache key. Ordinary reads remain fresh for one minute and concurrent
reads deduplicate. Signed URLs and live job/transcription polling have zero
freshness. Successful mutations invalidate the relevant endpoints and game;
upload tickets, transcription submissions and read-only image-link batches do
not invalidate unrelated browsing data. Sign-out clears the cache. The cache is
memory-only and contains no durable account or game data. Legacy views have an
explicit foreground bridge: returning to the window revalidates at most twelve
stale reads belonging to the visible section and redraws only when data changes.
Warm queries, live polling, signed URLs, active recordings, drafts, previews and
an open chapter reader are excluded. Settings drafts stay under the user's control. Pagination, non-default filters
and a playing or paused media position are preserved while cached data is
revalidated for the next navigation.

New React views use the same QueryClientProvider. The current-game chooser uses
Radix Select's keyboard navigation, portalled popup and focus handling; its
hidden native element is only a temporary bridge to existing application state.
Media browsing uses TanStack Table for sorting and filtering. The component
directory follows the shadcn composition and `components.json` configuration,
with Tailwind 4 utilities and Panther's existing CSS variable palette.

Radix injects viewport and scroll-lock style elements whose values depend on
the user's scrollbar geometry. The CSP permits inline **style elements** for
this UI system through `style-src-elem`; script, style-attribute, object and frame
restrictions remain in place. Browser tests open the Select under the actual
CDK-generated policy and check for CSP violations.

Loading views use pulsing skeletons, with motion disabled when requested by the
operating system. Keep existing content visible while fetching another page or
checking a warm query. API errors should expose a useful action, rather than
adding manual refresh buttons to ordinary browsing screens.
