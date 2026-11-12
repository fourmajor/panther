#!/usr/bin/env bash
# One-time, with admin credentials (AWS_PROFILE=panther-sso-admin).
# CDK already declares PT12H for PantherAdministrator and PantherAssetUploader.
# Run this if the live permission sets are still shorter. A later PantherAccess
# deploy keeps the same value. This does not change the console-only 90-day
# Identity Center interactive session.
set -euo pipefail

region="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-west-2}}"
instance="${PANTHER_SSO_INSTANCE_ARN:-}"
if [[ -z "$instance" ]]; then
  instance="$(aws sso-admin list-instances --region "$region" \
    --query 'Instances[0].InstanceArn' --output text)"
fi
if [[ -z "$instance" || "$instance" == None ]]; then
  echo "No IAM Identity Center instance found in ${region}." >&2
  exit 1
fi

token=""
found=0
while true; do
  if [[ -n "$token" ]]; then
    page="$(aws sso-admin list-permission-sets --instance-arn "$instance" \
      --region "$region" --starting-token "$token" --output json)"
  else
    page="$(aws sso-admin list-permission-sets --instance-arn "$instance" \
      --region "$region" --output json)"
  fi
  while IFS= read -r arn; do
    [[ -z "$arn" ]] && continue
    name="$(aws sso-admin describe-permission-set --instance-arn "$instance" \
      --permission-set-arn "$arn" --region "$region" \
      --query 'PermissionSet.Name' --output text)"
    case "$name" in
      PantherAdministrator|PantherAssetUploader)
        found=1
        echo "Setting ${name} session duration to PT12H"
        aws sso-admin update-permission-set --instance-arn "$instance" \
          --permission-set-arn "$arn" --session-duration PT12H --region "$region"
        aws sso-admin provision-permission-set --instance-arn "$instance" \
          --permission-set-arn "$arn" --region "$region" \
          --target-type ALL_PROVISIONED_ACCOUNTS
        ;;
    esac
  done < <(python3 -c 'import json,sys; print("\n".join(json.load(sys.stdin).get("PermissionSets") or []))' <<<"$page")
  token="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("NextToken") or "")' <<<"$page")"
  [[ -n "$token" ]] || break
done

if [[ "$found" != 1 ]]; then
  echo "Neither PantherAdministrator nor PantherAssetUploader was found." >&2
  exit 1
fi
echo "Permission-set sessions are PT12H. New SSO logins pick this up; open sessions keep their old length."
