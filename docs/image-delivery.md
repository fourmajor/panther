# Private gallery delivery

Storyboards authorize all selected frames and cast portraits with one `POST /image-links`
request, then fetch image bytes concurrently straight from private S3. Images are not proxied
through Lambda and the page never calls `/object-url` once per gallery image. This removes
the API invocation fan-out that produced 503 responses under the account's low concurrency quota.

The reusable route accepts up to 60 same-game immutable image references and requires the
existing publisher capability plus API Gateway JWT authentication. It resolves each unique
location through the current validated catalog once, with bounded internal I/O, and signs locally.
It does not HEAD or read image payloads, scan assets, alter metadata, or expose a public bucket.
Missing locators are reported per image rather than hiding the whole gallery. File extensions
bound this image-only operation; browser decoding still verifies usable image content.

Links last five minutes and are held only in the page's scoped memory. Expiration or a failed
image triggers a coalesced batch renewal with bounded retries. Switching shot selection reuses
valid links; changing game/view ignores stale responses. A visible gallery retry button recovers
persistent failures. Refreshing image access never invokes generation or spending.

CDK owns the authenticated API route and existing integration; no new provisioned compute or
credential storage is required. Existing originals and source references are unchanged, so no
asset-format migration is necessary. `/object-url` remains for individual downloads/details,
not the storyboard gallery. Browser tests cover full galleries, concurrent byte transfers,
API failures, expired links and zero per-image API calls on desktop/mobile.
