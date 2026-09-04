import secrets
import string

import boto3
from botocore.exceptions import ClientError


cognito = boto3.client("cognito-idp")
ssm = boto3.client("ssm")


def _password():
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


def _read_or_create_password(parameter_name):
    try:
        return ssm.get_parameter(Name=parameter_name, WithDecryption=True)["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        password = _password()
        ssm.put_parameter(
            Name=parameter_name,
            Description="Generated Panther media explorer password",
            Value=password,
            Type="SecureString",
            Tier="Standard",
            Tags=[
                {"Key": "Project", "Value": "Panther"},
                {"Key": "ManagedBy", "Value": "AWS-CDK"},
                {"Key": "Environment", "Value": "production"},
            ],
        )
        return password


def _user_exists(user_pool_id, username):
    try:
        cognito.admin_get_user(UserPoolId=user_pool_id, Username=username)
        return True
    except cognito.exceptions.UserNotFoundException:
        return False


def _upsert_user(user_pool_id, username, parameter_name):
    password = _read_or_create_password(parameter_name)
    if not _user_exists(user_pool_id, username):
        cognito.admin_create_user(
            UserPoolId=user_pool_id,
            Username=username,
            TemporaryPassword=password,
            MessageAction="SUPPRESS",
        )
        cognito.admin_set_user_password(
            UserPoolId=user_pool_id,
            Username=username,
            Password=password,
            Permanent=True,
        )


def _delete_user(user_pool_id, username, parameter_name):
    try:
        cognito.admin_delete_user(UserPoolId=user_pool_id, Username=username)
    except (cognito.exceptions.UserNotFoundException, cognito.exceptions.ResourceNotFoundException):
        pass
    try:
        ssm.delete_parameter(Name=parameter_name)
    except ssm.exceptions.ParameterNotFound:
        pass


def handler(event, _context):
    properties = event["ResourceProperties"]
    user_pool_id = properties["UserPoolId"]
    username = properties["Username"]
    parameter_name = properties["PasswordParameterName"]
    physical_id = f"{user_pool_id}:{username}"

    try:
        if event["RequestType"] == "Delete":
            _delete_user(user_pool_id, username, parameter_name)
        else:
            _upsert_user(user_pool_id, username, parameter_name)
    except ClientError as error:
        raise RuntimeError(error.response.get("Error", {}).get("Code", "AWS service error"))

    return {"PhysicalResourceId": physical_id}
