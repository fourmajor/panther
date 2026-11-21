"""Create one access key for the Grafana reader and store it only in Secrets Manager.

The secret access key is never logged or returned to CloudFormation.
"""

import json

import boto3
from botocore.exceptions import ClientError

USER_NAME = "panther-grafana-readonly"
SECRET_NAME = "panther/grafana-cloudwatch-readonly"


def _clients():
    return boto3.client("iam"), boto3.client("secretsmanager")


def _code(error):
    return error.response.get("Error", {}).get("Code", "AWS service error")


def _existing(secrets_client):
    try:
        current = secrets_client.get_secret_value(SecretId=SECRET_NAME)
    except ClientError as error:
        if _code(error) == "ResourceNotFoundException":
            return None
        raise RuntimeError(_code(error)) from None
    try:
        payload = json.loads(current["SecretString"])
    except (json.JSONDecodeError, KeyError, TypeError):
        raise RuntimeError("Grafana credential is unreadable") from None
    if not payload.get("accessKeyId") or not payload.get("secretAccessKey"):
        raise RuntimeError("Grafana credential is incomplete")
    arn = current["ARN"]
    return {"PhysicalResourceId": arn, "Data": {"SecretArn": arn}}


def ensure_grafana_key(event, *, iam, secrets_client):
    if event.get("RequestType") not in {"Create", "Update", "Delete"}:
        raise ValueError("Invalid provisioning operation")
    physical = event.get("PhysicalResourceId") or SECRET_NAME
    if event["RequestType"] == "Delete":
        return {"PhysicalResourceId": physical}
    props = event.get("ResourceProperties") or {}
    if props.get("UserName") != USER_NAME:
        raise ValueError("Unexpected principal")
    existing = _existing(secrets_client)
    if existing:
        return existing
    try:
        created = iam.create_access_key(UserName=USER_NAME)["AccessKey"]
    except ClientError as error:
        raise RuntimeError(_code(error)) from None
    body = json.dumps({
        "accessKeyId": created["AccessKeyId"],
        "secretAccessKey": created["SecretAccessKey"],
    })
    try:
        result = secrets_client.create_secret(Name=SECRET_NAME, SecretString=body)
    except Exception:
        try:
            iam.delete_access_key(UserName=USER_NAME, AccessKeyId=created["AccessKeyId"])
        except ClientError:
            pass
        raise RuntimeError("Could not store the Grafana credential") from None
    arn = result["ARN"]
    return {"PhysicalResourceId": arn, "Data": {"SecretArn": arn}}


def handler(event, _context):
    iam, secrets_client = _clients()
    return ensure_grafana_key(event, iam=iam, secrets_client=secrets_client)
