# Account management and credential cutover

Cognito is the only password authority. Do not keep retrievable permanent passwords in any
application store, private configuration, outputs, logs, or support documents. Actual identities
and invitation addresses are private deployment data, never repository fixtures or issue text.

## Credential-policy version 2

The existing `User-USERNAME` constructs and physical identities remain unchanged. The CDK
custom-resource property `CredentialPolicyVersion: 2` forces each configured account through
the safe migration, even if its private configuration has not changed. The handler:

1. Confirms whether the same Cognito account already exists.
2. Leaves every existing account's attributes, status, password and MFA unchanged. A missing
   legacy parameter is **not** permission to reset a password.
3. For a genuinely new account only, requires an address in private `invitationEmails`, sends
   a Cognito email invitation with an in-memory temporary credential, and requires Cognito's
   first-login password-change challenge. It never marks the email verified on the user's behalf.
4. Deletes the exact legacy `/panther/media-explorer/users/USERNAME/password` parameter.
   Missing copies are an idempotent success. It never retrieves/decrypts their contents.

The provisioner has only scoped `AdminCreateUser`, `AdminGetUser` and `DeleteParameter`
permissions. It cannot set permanent passwords, delete users, read secrets or write parameters.
Account resources and the pool are retained on removal. Removing a name from private configuration
is therefore **not** account deactivation; explicit revocation/deprovisioning needs its own reviewed
operation. A pool/username change fails closed rather than replacing an account.

Existing accounts need no invitation address for this migration. An invitation setting supplied
later does not overwrite an existing account's email or resend/reset its credentials. If an
invitation delivery fails after account creation, inspect the account privately and use a separate
explicit resend operation; do not delete/recreate it or reintroduce password copies.

## Recovery without replacing the pool

CDK enables verified-email recovery, automatic email verification and retention of the original
email until a replacement is verified. Username-only sign-in remains unchanged: no email alias,
required schema attribute, new pool or new user identity is introduced. Accounts without a verified
email cannot recover by email yet; never invent one or mark an unverified address verified.

These are in-place [CloudFormation user-pool settings](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cognito-userpool.html).
[Cognito's pending attribute updates](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_UserAttributeUpdateSettingsType.html)
keep the original address active until the new value is verified. Recovery email delivery still
depends on Cognito's configured sender limits and actual account verification.

## Deployment gate and verification

Use the private configuration and CDK workflow in `private-account-configuration.md`. Keep the
deployment diff and account inventory outside Git. Before deployment, confirm the target account
and `us-west-2`, then inspect a private CDK diff: existing pool/client/user logical IDs must remain,
there must be **no** account or pool replacement, no password reset, and no capability expansion.
The deliberate changes are recovery/verification settings, retention policies, the policy-version
trigger, removal of reset/read/write permissions and the obsolete password-location output.

After deployment, privately verify every configured account's identity/status/access is unchanged
and every corresponding legacy parameter is absent. Check removal by name/metadata only, never
decrypt a password. Report any remaining copy or failed account migration as a blocker. Preserve
the migration's CloudFormation/custom-resource result, not the deleted credential value. The
credential copies are intentionally unrecoverable through Panther; the actual Cognito passwords
are unchanged. Earlier private backups, exports and historical logs are outside this deletion's
scope and must not be claimed erased.

## Self-service web controls

The **Account** button opens an accessible, scrollable settings dialog with a permanently visible
close control. Display name and a first-party preset avatar are Cognito profile attributes. These
are account profiles, not Players or Character portraits. Uploaded personal avatars and structured
future preferences can extend this surface without mixing account data into a game catalog.

Email changes send a verification request; the current address remains until verification.
Password change requires the current password. Signed-out **Forgot password?** sends a generic
acknowledgement that does not reveal account existence; completing recovery requires the email code
and a policy-compliant password. Forms clear passwords after attempts and discard all fields when
closed. No automatic mutation retries are made after ambiguous/network errors.

Authenticator setup displays an ephemeral manual TOTP key, then verifies a six-digit code before
enabling MFA. Closing settings discards the key, including delayed responses. Disabling MFA requires
explicit acknowledgement. Cognito does not supply Panther recovery codes: back up the authenticator
securely. If it is lost, email password reset does **not** bypass MFA; an administrator must review
identity and disable/reset the factor through a separately authorized CDK-managed operation.

Cookie-authenticated `/auth/account` operations use Cognito's short-lived access token server-side.
They accept no target user, pool or caller-supplied token. Only the signed-in user can be affected.
The web client requests [Cognito's self-service scope](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html);
both clients can write only name, picture and email, never a future role/capability attribute. Existing
remembered sessions may need **one** fresh sign-in to acquire the new scope; regular asset access is
not invalidated just to force that upgrade. Tokens and credential values are excluded from errors
and logs; the rotated refresh credential is saved even if a subsequent account operation fails.

All `/auth/*` operations are JSON POSTs with exact first-party Origin checking and SameSite/HttpOnly
cookies. Recovery does not require a cookie. Cognito throttling and client existence protection apply;
no always-on gateway or paid inference is added. Responses are private/no-store, including setup keys.

**Sign out everywhere** revokes Cognito credentials and prevents refresh, clears this browser's
remembered cookie and ends hosted sign-in. This is not instantaneous invalidation of already issued
Panther API JWTs: the JWT authorizer can continue accepting them until their one-hour expiry. The UI
states that limit explicitly. Do not claim that global sign-out remotely clears another browser's
storage or overrides offline token caches.

Local security tests and self-hosted Playwright exercise these paths with fictional credentials.
Completion of #21 still requires production deployment, confirming private account preservation,
deletion of every managed legacy parameter, and an actual verified-email recovery/MFA check. Test
fixtures are not evidence that a real user's email is verified or that a real invitation was received.
