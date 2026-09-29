"""Invite new accounts, preserve existing credentials, and purge legacy copies.

Never log events, email addresses or temporary credentials. Cognito owns passwords.
"""

import re
import secrets
import string

import boto3
from botocore.exceptions import ClientError


cognito = boto3.client("cognito-idp")
ssm = boto3.client("ssm")


def _temporary_password():
    groups = [
        string.ascii_lowercase,
        string.ascii_uppercase,
        string.digits,
        "!@#$%^&*()-_=+",
    ]
    characters = [secrets.choice(group) for group in groups]
    alphabet = "".join(groups)
    characters.extend(secrets.choice(alphabet) for _ in range(20))
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def _user_exists(user_pool_id, username):
    try:
        cognito.admin_get_user(UserPoolId=user_pool_id, Username=username)
        return True
    except cognito.exceptions.UserNotFoundException:
        return False


def _purge_legacy_copy(parameter_name):
    try:
        ssm.delete_parameter(Name=parameter_name)
    except ssm.exceptions.ParameterNotFound:
        pass


def handler(event, _context):
    properties = event["ResourceProperties"]
    user_pool_id = properties["UserPoolId"]
    username = properties["Username"]
    parameter_name = properties["PasswordParameterName"]
    if not isinstance(username, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", username):
        raise ValueError("Invalid configured account")
    if parameter_name != f"/panther/media-explorer/users/{username}/password":
        raise ValueError("Unexpected legacy credential location")
    if event["RequestType"] not in {"Create", "Update", "Delete"}:
        raise ValueError("Invalid provisioning operation")
    if event["RequestType"] == "Update":
        old = event.get("OldResourceProperties", properties)
        if old.get("UserPoolId") != user_pool_id or old.get("Username") != username:
            raise ValueError("Account replacement requires an explicit separate migration")
    physical_id = f"{user_pool_id}:{username}"

    try:
        if event["RequestType"] != "Delete" and not _user_exists(user_pool_id, username):
            email = properties.get("InvitationEmail")
            if (
                not isinstance(email, str)
                or len(email) > 254
                or not re.fullmatch(r"[^\s@\x00-\x1f]+@[^\s@\x00-\x1f]+\.[^\s@\x00-\x1f]+", email)
            ):
                raise ValueError("New accounts require a private invitation email")
            cognito.admin_create_user(
                UserPoolId=user_pool_id,
                Username=username,
                TemporaryPassword=_temporary_password(),
                UserAttributes=[{"Name": "email", "Value": email}],
                DesiredDeliveryMediums=["EMAIL"],
            )
        # CONFIRMED and FORCE_CHANGE_PASSWORD accounts are never reset. Removal
        # preserves the account; no AdminDeleteUser permission exists.
        _purge_legacy_copy(parameter_name)
    except ClientError as error:
        raise RuntimeError(
            error.response.get("Error", {}).get("Code", "AWS service error")
        ) from None

    return {"PhysicalResourceId": physical_id}
