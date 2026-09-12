# Unlisted asset sharing

Public pages supply [Open Graph](https://ogp.me/) title, description, image and MP4 video
metadata using permanent URLs, never expiring URLs in cached social metadata. Video shares require
a frame from the exact shared video, used for both the player poster and social image. Other non-image
shares use generic Panther artwork. Discord decides whether
to show an inline player; the no-login watch page remains the fallback. External services may cache
previews or copies after revocation, which Panther cannot erase.

`panther share create KEY --confirm-public` creates an explicitly authorized anyone-with-link
share of exactly one asset. The response includes a watch page, direct media link and forced-download
link. All three stay valid until revoked; no sign-in is needed to follow them. Sharing does not expose
the library, related assets, transcripts, players or source metadata. Treat links as bearer secrets:
do not commit them, log them in CI, or assume that unlisted means access-controlled.

For videos, also supply `--preview-key PREVIEW_KEY`. Extract a representative JPEG/PNG/WebP frame
locally from verified source bytes, inspect it, then upload it with Panther as `video-preview`.
Retain exact video `sourceKeys`, `extra.sourceVersionId` from `panther info`, the sampled timestamp,
generation metadata identifying local FFmpeg processing, and `extra.relationshipRole: intermediate`.
This derivative does not regenerate video or require inference. Never use unrelated artwork as a
substitute. The server checks same-game lineage, video-version provenance, image MIME/size, and pins
the preview's physical object/version. The same share revocation disables the preview endpoint.

Backfill existing active video shares using `panther share set-preview URL PREVIEW_KEY`.
This repeatable, conflict-guarded operation preserves the URL, video pin and audit fields; attaching
the same pinned preview is idempotent, and it cannot reactivate a revoked share or overwrite a prior
poster. Check the complete active share inventory after rollout. Revoked shares remain inaccessible
and do not need posters. Video shares missing a preview fail closed; generic previews are not a
legacy alternative. A new poster revision after attachment requires a fresh share, preserving the old
one. Discord may retain an older cached preview; posting the URL with `?preview=2` can request a fresh
fetch without changing access or expiry, but Panther cannot force Discord to invalidate its cache.

`panther share revoke URL` permanently disables that link. Previously issued S3 redirects can work
for up to five minutes and downloaded copies cannot be recalled. Re-sharing requires a fresh token.
Save the returned URL outside Git so it can be revoked. Failed create responses may leave an orphaned
share; the CLI prints its recovery URL so it can be revoked. Never reactivate a revoked token.

CDK provisions an on-demand retained DynamoDB table, separate public-read and publisher-management
Lambdas, and uncached `/s/*` routes through the existing CloudFront distribution. Tokens contain
256 random bits; only SHA-256 token hashes are stored. Records pin the catalog-resolved physical
object and S3 version. Public Lambda permissions are read-only and contain no list or write actions.
No public S3 ACL/policy, API key, signing secret, EC2 or NAT is introduced. Idle cost is storage;
requests and S3 transfer are usage-billed. Anyone with a link can consume transfer bandwidth.

The public page has no scripts, cookies, third-party resources or analytics, uses no-store,
no-referrer and noindex, and supplies an explicit Download file action for mobile browsers.
Active content such as HTML/SVG is attachment-only. Revoked/unknown tokens reveal no asset details.
Media redirects are short-lived internally; the shared Panther URL itself does not expire.

This is a new opt-in access record, not a change to the asset contract: existing assets are not
automatically shared and no migration/publication of the library is performed.
