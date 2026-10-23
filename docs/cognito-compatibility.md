# Cognito additive token compatibility

Cognito may add ID/access-token claims and OIDC discovery members without removing existing
fields. Consumers must ignore unknown fields, preserve documented types (`amr` is an array,
including password-only authentication), and continue enforcing existing authentication guards.

Panther's browser decodes the JSON payload for display/session expiry; it does **not** validate
signatures. API Gateway's managed JWT authorizer owns API signature/issuer/audience/expiry
validation. CLI and web-session handlers transport tokens without a fixed claim schema.
Panther currently does not parse OIDC discovery documents itself, so there is no discovery
parser to change or simulated discovery result to claim verified. Review any future OIDC library
against extended metadata before adopting it. Do not treat `acr`/`amr` as new permissions.

## Regression coverage

- `tests/test_web_session.py`: code exchange and refresh preserve a larger synthetic ID token
  containing password-only/MFA `amr`, `acr` and unknown fields. Refresh credentials remain in
  secure HttpOnly cookies; unrelated provider response fields/access tokens are not returned.
- `tests/test_cloud_cli.py`: login, secure-store round trip, renewal and API Authorization header
  preserve the extended token unchanged without printing it.
- `infra/browser-tests/auth.spec.cjs`: desktop/mobile PKCE callback, expired-session renewal,
  bounded API-401 recovery and actual authenticated navigation accept those extended payloads.
  Unknown nested Unicode fields and tokens larger than 4 KiB exercise parsing/transport growth.
  Existing negative state, revoked-session and transient-failure tests remain required.

Fixtures are deliberately unsigned and synthetic. These checks do not prove live Cognito
issuance, managed JWT signature acceptance, live account authentication or unlimited token size.
Existing service/header limits still apply; no security limits are removed for this notice.
No production configuration/deployment is necessary when only these tests/documentation change.
The normal full self-hosted CI includes the regressions, including nightly main execution.

## Sources

- [AWS ID-token parsing contract](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-id-token.html#user-pool-id-token-parse-safely)
- [AWS discovery forward compatibility](https://docs.aws.amazon.com/cognito/latest/developerguide/federation-endpoints.html#user-pool-oidc-discovery-parse-safely)

Checked October 22, 2026. The owner's AWS Health notice specifies gradual rollout beginning
November 4, 2026, an opt-out request cutoff of November 2, 2026, and universal default adoption
by February 28, 2027. Those dates come from the notice, not a claim of observed pool rollout.
No opt-out is indicated by the current code review; investigate any failed compatibility check.
