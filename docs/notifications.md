# Account controls and workflow notifications

The circular avatar opens account settings and sign out. Existing profile presets
are reused; without an avatar it displays initials. The bell to its left indicates
unread notifications and shows at most ten. The Notifications page is paginated;
clicking an item marks it read and opens its run. Read items remain in history.
A read failure leaves the item unread and offers a retry rather than hiding it.

The CDK-managed retained, pay-per-request table stores separate history, unread
entries and deduplication markers for each deployed catalog-reader account.
Recipients come only from private deployment configuration, never source code.
Authentication determines the account partition; clients cannot name a recipient.
The current capability model allows these readers to see the same game catalog;
future per-game membership must constrain delivery as well as browsing.

DynamoDB stream observations create notices for failed runs and explicitly
reported human-review checkpoints, including READY_FOR_VIDEO_DISCUSSION. Generic
pauses, unknown progress and successful completion do not invent a review request.
Duplicate stream delivery or migration cannot re-notify a read item. One notice
per run/event category is retained, including after a later successful retry.
These notices do not grant approval or trigger generation. Links are typed local
workflow targets, not arbitrary source-supplied URLs. Stream errors retry through
partial-batch acknowledgments; the browser reports unavailable state honestly.

## Rollout

Review the CDK diff, confirm account/region, deploy after self-hosted browser checks.
Run `panther workflows rebuild` to verify the existing workflow projection first,
then `panther workflows import-video-ledger` to report explicit approval checkpoints
from retained local plans, and `panther notifications rebuild`. These use Panther authentication. The latter
pages through every indexed game/run, preserving source state and existing read
receipts. Notification browsing fails closed until the backfill completes. Rerun
after adding catalog readers to privately configured deployment identities so new
accounts receive retained relevant workflow notices. Keep inventories outside Git.

The SQLite development store projects real job writes transactionally and backfills
existing jobs at startup. Its single development identity and database never grant
production access. Browsing reads stored notifications, not job scans or fixtures.
The bell polls once per minute while the page is visible and refreshes on focus;
there is no always-on compute or polling when the application is closed.
