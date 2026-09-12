# Unlisted asset sharing

Public pages supply [Open Graph](https://ogp.me/) title, description, image and MP4 video
metadata using permanent URLs, never expiring URLs in cached social metadata. Non-image shares
use generic Panther artwork rather than exposing another private asset. Discord decides whether
to show an inline player; the no-login watch page remains the fallback. External services may cache
previews or copies after revocation, which Panther cannot erase.

`panther share create KEY --confirm-public` creates an explicitly authorized anyone-with-link
share of exactly one asset. The response includes a watch page, direct media link and forced-download
link. All three stay valid until revoked; no sign-in is needed to follow them. Sharing does not expose
the library, related assets, transcripts, players or source metadata. Treat links as bearer secrets:
do not commit them, log them in CI, or assume that unlisted means access-controlled.

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
