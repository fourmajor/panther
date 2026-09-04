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

## 8. Activate the Identity Center user

Users created through the Identity Store API do not have an initial password. AWS does not expose
the email-OTP setting through CloudFormation, CDK, or a public API, so enable it in the IAM Identity
Center console under **Settings**, **Authentication**, **Standard authentication**, **Configure**,
then **Send email OTP**.

Start a first sign-in from the AWS access portal. Follow the emailed verification link to set a
password and register MFA. Do not recreate the user in the console.

The foundation stack outputs the private and published bucket names. The same names are also stored
in these standard SSM parameters:

```text
/panther/foundation/private-asset-bucket
/panther/foundation/published-asset-bucket
```

## 9. Verify the private bucket

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

## 10. Deploy the media explorer

Deploy the read-only media explorer with the short-lived administrator profile:

```bash
cd infra
AWS_PROFILE=panther-sso-admin npm run deploy -- PantherMediaExplorer \
  --context account=ACCOUNT_ID \
  --exclusively
```

CDK creates the private web bucket, CloudFront distribution, Cognito user pool, two users, protected
HTTP API, and on-demand Lambda functions. The default Cognito domain prefix is checked into
`infra/cdk.json`; change that context value if AWS reports that the globally named prefix is already
in use. `--exclusively` prevents this focused deployment from also updating the existing foundation
stack without its deployment-time budget email context.

The two initial usernames are `stu` and `other_stu`. Their generated passwords are stored as standard
SSM SecureString parameters. Retrieve each password with administrative access:

```bash
AWS_PROFILE=panther-sso-admin aws ssm get-parameter \
  --region us-west-2 \
  --name /panther/media-explorer/users/stu/password \
  --with-decryption \
  --query Parameter.Value \
  --output text

AWS_PROFILE=panther-sso-admin aws ssm get-parameter \
  --region us-west-2 \
  --name /panther/media-explorer/users/other_stu/password \
  --with-decryption \
  --query Parameter.Value \
  --output text
```

Password generation and user provisioning happen inside the CDK deployment. No password is passed
through CDK context, committed to Git, or returned in a CloudFormation output. CloudFormation cannot
natively set permanent Cognito passwords or create SSM SecureString values, so an on-demand custom
resource performs those two operations and owns their lifecycle.

Read the explorer URL from the deployment output or later with:

```bash
AWS_PROFILE=panther-sso-admin aws cloudformation describe-stacks \
  --region us-west-2 \
  --stack-name PantherMediaExplorer \
  --query "Stacks[0].Outputs[?OutputKey=='MediaExplorerUrl'].OutputValue | [0]" \
  --output text
```
