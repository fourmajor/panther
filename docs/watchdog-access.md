# Pipeline watchdog access

The `PantherWatchdog` stack defines a long-lived, read-only identity for the twice-daily pipeline watchdog. It does not use AWS SSO.

- IAM user `panther-watchdog` can only call `sts:AssumeRole` on `PantherWatchdogReadOnly`.
- The role can list and describe Panther Step Functions, read the foundation private and published asset buckets, and read CloudWatch Logs and metrics. An explicit deny covers start/stop/create/update/delete and S3/log/metric writes.
- Access keys are created out of band so the secret never enters CloudFormation. The watchdog hosts use the `panther-watchdog` AWS profile, which assumes the role through a `source_profile`.

Deploy only this stack, after `cdk diff PantherWatchdog --exclusively` shows just these IAM resources:

```bash
export PANTHER_IDENTITIES_FILE=/private/path/identities.json
export AWS_PROFILE=panther-sso-admin
cd infra
npx cdk deploy PantherWatchdog --exclusively --context account=223663280572
```

Then create one access key with the admin profile and store it only in the watchdog hosts' `~/.aws` files (mode 600). Rotate by issuing a new key, updating those profiles, and deleting the old key.
