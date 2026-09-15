# Cache-safe web releases

CDK builds content-addressed filenames for JavaScript, CSS, the update checker and
the model viewer. Immutable files are uploaded before the HTML and release manifest.
HTML, configuration and the manifest use `Cache-Control: no-cache`; CloudFront's
minimum TTL is zero so it honors revalidation. Hashed files can be cached for a year.

Old hashed files remain available for old documents and in-flight requests. They are
small static deployment history, not always-on compute. Do not prune them as part of
an ordinary deployment. The original unversioned files are also retained for tabs
from before this rollout, but new entry points never reference them.

Open tabs check the public release manifest once per minute while visible and on
returning to the tab. An accessible, in-flow notice offers a reload; it never reloads
automatically or discards edits without the user's action. Reload preserves the URL
(including the selected project and fragment), not unsaved form contents. Failed
update checks are non-blocking. Tabs opened before the checker was introduced still
need one manual reload.

The self-hosted Playwright release regression uses a real HTTP server with caching
headers, not request routing (which disables browser caching). It tests two releases,
desktop/mobile notice layout, offline checks, preservation of edits until reload,
fresh code after reload, route preservation and old-file availability.
