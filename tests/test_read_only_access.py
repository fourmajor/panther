"""Synthetic reader and Grafana key handlers never return secret material."""

import json
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).parents[1] / "infra/lambda/read-only-access"))

import grafana_key  # noqa: E402
import viewer  # noqa: E402


def client_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "operation")


class Secrets:
    def __init__(self, payload=None, missing=False):
        self.payload = payload
        self.missing = missing
        self.created = None

    def get_secret_value(self, SecretId):
        if self.missing:
            raise client_error("ResourceNotFoundException")
        if SecretId != viewer.SECRET_NAME and SecretId != grafana_key.SECRET_NAME:
            raise AssertionError(SecretId)
        return {"SecretString": json.dumps(self.payload), "ARN": f"arn:aws:secretsmanager:us-west-2:223663280572:secret:{SecretId}-AbCdEf"}

    def create_secret(self, Name, SecretString):
        self.created = {"Name": Name, "SecretString": SecretString}
        return {"ARN": f"arn:aws:secretsmanager:us-west-2:223663280572:secret:{Name}-AbCdEf"}


class Cognito:
    def __init__(self, exists=False):
        self.exists = exists
        self.created = False
        self.password = None
        self.permanent = None

    def admin_get_user(self, UserPoolId, Username):
        if not self.exists:
            raise client_error("UserNotFoundException")
        return {"Username": Username, "UserPoolId": UserPoolId}

    def admin_create_user(self, **kwargs):
        self.created = True
        self.exists = True
        assert kwargs["MessageAction"] == "SUPPRESS"
        assert "UserAttributes" not in kwargs

    def admin_set_user_password(self, **kwargs):
        self.password = kwargs["Password"]
        self.permanent = kwargs["Permanent"]


class Iam:
    def __init__(self):
        self.deleted = None

    def create_access_key(self, UserName):
        assert UserName == grafana_key.USER_NAME
        return {"AccessKey": {"AccessKeyId": "AKIAEXAMPLE", "SecretAccessKey": "example-secret-not-real"}}

    def delete_access_key(self, UserName, AccessKeyId):
        self.deleted = (UserName, AccessKeyId)


def test_viewer_sets_a_permanent_password_and_returns_none_of_it():
    cognito = Cognito()
    secrets = Secrets({"username": viewer.USERNAME, "password": "Correct-Horse-Battery-9!"})
    result = viewer.ensure_viewer({
        "RequestType": "Create",
        "ResourceProperties": {"Username": viewer.USERNAME, "UserPoolId": "us-west-2_Example", "SecretId": viewer.SECRET_NAME},
    }, cognito=cognito, secrets_client=secrets)
    assert result == {"PhysicalResourceId": "us-west-2_Example:penelope-viewer"}
    assert "password" not in json.dumps(result)
    assert cognito.created and cognito.permanent is True
    assert cognito.password == "Correct-Horse-Battery-9!"


def test_viewer_refuses_any_other_account_and_leaves_existing_users_uncreated():
    cognito = Cognito(exists=True)
    secrets = Secrets({"username": viewer.USERNAME, "password": "Correct-Horse-Battery-9!"})
    with pytest.raises(ValueError):
        viewer.ensure_viewer({
            "RequestType": "Create",
            "ResourceProperties": {"Username": "someone-else", "UserPoolId": "us-west-2_Example", "SecretId": viewer.SECRET_NAME},
        }, cognito=cognito, secrets_client=secrets)
    viewer.ensure_viewer({
        "RequestType": "Update",
        "ResourceProperties": {"Username": viewer.USERNAME, "UserPoolId": "us-west-2_Example", "SecretId": viewer.SECRET_NAME},
    }, cognito=cognito, secrets_client=secrets)
    assert cognito.created is False
    assert viewer.ensure_viewer({"RequestType": "Delete", "PhysicalResourceId": "kept"}, cognito=cognito, secrets_client=secrets) == {"PhysicalResourceId": "kept"}


def test_grafana_key_is_stored_once_and_omitted_from_the_response():
    iam = Iam()
    secrets = Secrets(missing=True)
    created = grafana_key.ensure_grafana_key({
        "RequestType": "Create", "ResourceProperties": {"UserName": grafana_key.USER_NAME},
    }, iam=iam, secrets_client=secrets)
    assert created["Data"] == {"SecretArn": "arn:aws:secretsmanager:us-west-2:223663280572:secret:panther/grafana-cloudwatch-readonly-AbCdEf"}
    assert "example-secret-not-real" not in json.dumps(created)
    stored = json.loads(secrets.created["SecretString"])
    assert stored["accessKeyId"] == "AKIAEXAMPLE"
    again = grafana_key.ensure_grafana_key({
        "RequestType": "Update", "ResourceProperties": {"UserName": grafana_key.USER_NAME},
    }, iam=iam, secrets_client=Secrets(payload=stored))
    assert again["Data"]["SecretArn"].endswith("panther/grafana-cloudwatch-readonly-AbCdEf")
    assert "example-secret-not-real" not in json.dumps(again)


def test_grafana_key_deletes_an_unstored_key_and_hides_the_failure():
    iam = Iam()

    class Broken(Secrets):
        def create_secret(self, Name, SecretString):
            raise RuntimeError("store failed")

    with pytest.raises(RuntimeError, match="Could not store the Grafana credential"):
        grafana_key.ensure_grafana_key({
            "RequestType": "Create", "ResourceProperties": {"UserName": grafana_key.USER_NAME},
        }, iam=iam, secrets_client=Broken(missing=True))
    assert iam.deleted == (grafana_key.USER_NAME, "AKIAEXAMPLE")
