# Panther AWS Foundation Runbook

Status: Initial bootstrap

This runbook establishes the minimum AWS foundation needed to upload Panther assets. It creates no
game data and does not require automatic CI.

## 1. Create the dedicated account

Create a new dedicated AWS account through the AWS signup process. Use a unique account email,
enable root-user MFA immediately, and do not create root access keys.

Create an administrative CLI profile that uses short-lived credentials. The examples below call it
`panther-admin`; a different local name is fine.

Do not create IAM access keys. CDK creates a one-account AWS Organization, the Identity Center user,
and all permission sets and assignments. Because CloudFormation does not expose the Identity Store
user resource in `us-west-2`, CDK manages that user with an on-demand custom resource. Its Lambda
runs only when the stack creates, updates, or deletes the user.

Enabling the organization-level IAM Identity Center instance is the one access-related console
exception. AWS does not expose that operation through CloudFormation, CDK, or a public API.

## 2. Confirm the target

```bash
AWS_PROFILE=panther-admin aws sts get-caller-identity
```

Confirm that the returned account ID is the new Panther account before continuing.

The initial region is `us-west-2`. Override it at deployment time with
`PANTHER_AWS_REGION` or CDK context if needed.

## 3. Install and verify the CDK application

```bash
cd infra
npm ci
npm test
npm run synth -- --context account=ACCOUNT_ID
```

## 4. Bootstrap the account

```bash
AWS_PROFILE=panther-admin npx cdk bootstrap aws://ACCOUNT_ID/us-west-2
```

Replace `ACCOUNT_ID` with the verified Panther account ID.

## 5. Deploy the foundation and one-account Organization

```bash
AWS_PROFILE=panther-admin npm run deploy -- PantherFoundation \
  --context account=ACCOUNT_ID \
  --context budgetEmail=YOUR_EMAIL \
  --context monthlyBudgetUsd=10
```

The email context is optional, but without it the budget will not send notifications. AWS requires
the recipient to confirm the budget-notification subscription.

The account ID context is required. Requiring it prevents CDK from silently inheriting a different
default AWS profile.

## 6. Enable organization-level IAM Identity Center

In the AWS console, enable IAM Identity Center for the new Organization in `us-west-2`. This is a
documented manual exception because AWS does not provide a CloudFormation resource or public API
for enabling an organization instance.

Read the resulting instance identifiers with the CLI:

```bash
AWS_PROFILE=panther-admin aws sso-admin list-instances --region us-west-2
```

## 7. Deploy access

```bash
AWS_PROFILE=panther-admin npm run deploy -- PantherAccess \
  --context account=ACCOUNT_ID \
  --context administratorEmail=YOUR_EMAIL \
  --context identityCenterInstanceArn=INSTANCE_ARN \
  --context identityStoreId=IDENTITY_STORE_ID
```

CDK creates the first Identity Center user and two assigned permission sets:

- `PantherAdministrator` for infrastructure administration
- `PantherAssetUploader` for routine access to private game assets

Use `PantherAssetUploader` for game-specific sessions. Reserve `PantherAdministrator` for CDK and
account-administration work. The temporary root profile is only for account bootstrap and recovery.

The foundation stack outputs the private and published bucket names. The same names are also stored
in these standard SSM parameters:

```text
/panther/foundation/private-asset-bucket
/panther/foundation/published-asset-bucket
```

## 8. Verify the private bucket

```bash
AWS_PROFILE=panther-uploader aws ssm get-parameter \
  --name /panther/foundation/private-asset-bucket \
  --query Parameter.Value \
  --output text
```

The game-specific session can upload a portrait using a caller-supplied game ID and asset ID:

```bash
AWS_PROFILE=panther-uploader aws s3 cp /path/to/portrait.png \
  s3://PRIVATE_BUCKET/games/GAME_ID/assets/ASSET_ID/original/portrait.png \
  --content-type image/png \
  --metadata asset-kind=portrait
```

The actual game ID, asset ID, portrait, and related metadata remain outside this repository.
