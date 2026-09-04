# Panther AWS Foundation Runbook

Status: Initial bootstrap

This runbook establishes the minimum AWS foundation needed to upload Panther assets. It creates no
game data and does not require automatic CI.

## 1. Create the standalone account

Create a new standalone AWS account through the AWS signup process. Use a unique account email,
enable root-user MFA immediately, and do not create root access keys.

Create an administrative CLI profile that uses short-lived credentials. The examples below call it
`panther-admin`; a different local name is fine.

Do not create IAM access keys. CDK creates the IAM Identity Center instance, its first user, and all
permission sets and assignments. Because CloudFormation does not expose the Identity Store user
resource in `us-west-2`, CDK manages that user with an on-demand custom resource. Its Lambda runs
only when the stack creates, updates, or deletes the user.

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
npm run synth
```

## 4. Bootstrap the account

```bash
AWS_PROFILE=panther-admin npx cdk bootstrap aws://ACCOUNT_ID/us-west-2
```

Replace `ACCOUNT_ID` with the verified Panther account ID.

## 5. Deploy the foundation

```bash
AWS_PROFILE=panther-admin npm run deploy -- \
  --context account=ACCOUNT_ID \
  --context administratorEmail=YOUR_EMAIL \
  --context budgetEmail=YOUR_EMAIL \
  --context monthlyBudgetUsd=10
```

The email context is optional, but without it the budget will not send notifications. AWS requires
the recipient to confirm the budget-notification subscription.

The account ID and administrator email contexts are required. Requiring the account ID prevents CDK
from silently inheriting a different default AWS profile. The administrator email causes CDK to
create IAM Identity Center, its first user, and two assigned permission sets:

- `PantherAdministrator` for infrastructure administration
- `PantherAssetUploader` for routine access to private game assets

Use `PantherAssetUploader` for game-specific sessions. Reserve `PantherAdministrator` for CDK and
account-administration work. The temporary root profile is only for account bootstrap and recovery.

The stack outputs the private and published bucket names. The same names are also stored in these
standard SSM parameters:

```text
/panther/foundation/private-asset-bucket
/panther/foundation/published-asset-bucket
```

## 6. Verify the private bucket

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
