import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError


@pytest.fixture
def provisioner(monkeypatch):
    import boto3

    class MissingUser(Exception):
        pass

    class MissingParameter(Exception):
        pass

    class Cognito:
        exceptions = SimpleNamespace(UserNotFoundException=MissingUser)
        users = {}

        def admin_get_user(self, **kwargs):
            if kwargs["Username"] not in self.users:
                raise MissingUser()
            return dict(self.users[kwargs["Username"]])

        def admin_create_user(self, **kwargs):
            self.users[kwargs["Username"]] = {
                "UserStatus": "FORCE_CHANGE_PASSWORD",
                "UserCreateDate": "fixed",
            }

        def admin_set_user_password(self, **kwargs):
            self.users[kwargs["Username"]]["UserStatus"] = "CONFIRMED"

        def admin_delete_user(self, **kwargs):
            del self.users[kwargs["Username"]]

    class SSM:
        exceptions = SimpleNamespace(ParameterNotFound=MissingParameter)
        parameters = {}

        def put_parameter(self, **kwargs):
            self.parameters[kwargs["Name"]] = kwargs["Value"]

        def get_parameter(self, **kwargs):
            return {"Parameter": {"Value": self.parameters[kwargs["Name"]]}}

        def delete_parameter(self, **kwargs):
            if kwargs["Name"] not in self.parameters:
                raise MissingParameter()
            del self.parameters[kwargs["Name"]]

    clients = {"cognito-idp": Cognito(), "ssm": SSM()}
    monkeypatch.setattr(boto3, "client", lambda service: clients[service])
    spec = importlib.util.spec_from_file_location(
        "test_user_provisioner",
        Path(__file__).parents[1] / "infra/lambda/user-provisioner/index.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    properties = {
        "UserPoolId": "synthetic-pool",
        "Username": "example-member",
        "PasswordParameterName": "/panther/media-explorer/users/example-member/password",
        "CredentialPolicyVersion": 2,
    }
    yield module, properties


@pytest.mark.parametrize("confirmed", [False, True])
def test_existing_accounts_preserved_and_legacy_copy_deleted(provisioner, confirmed, monkeypatch):
    module, properties = provisioner
    module.cognito.admin_create_user(
        UserPoolId=properties["UserPoolId"], Username=properties["Username"]
    )
    if confirmed:
        module.cognito.admin_set_user_password(
            UserPoolId=properties["UserPoolId"],
            Username=properties["Username"],
            Password="Synthetic-Test!123456",
            Permanent=True,
        )
    before = module.cognito.admin_get_user(
        UserPoolId=properties["UserPoolId"], Username=properties["Username"]
    )
    module.ssm.put_parameter(
        Name=properties["PasswordParameterName"], Value="synthetic-legacy", Type="SecureString"
    )

    def forbidden(**_kwargs):
        pytest.fail("Existing credentials must not be read, reset, deleted or rewritten")

    for method in ["admin_create_user", "admin_set_user_password", "admin_delete_user"]:
        monkeypatch.setattr(module.cognito, method, forbidden)
    monkeypatch.setattr(module.ssm, "get_parameter", forbidden)
    monkeypatch.setattr(module.ssm, "put_parameter", forbidden)
    event = {
        "RequestType": "Update",
        "ResourceProperties": properties,
        "OldResourceProperties": {
            k: v for k, v in properties.items() if k != "CredentialPolicyVersion"
        },
    }
    result = module.handler(event, None)
    module.handler(event, None)  # Missing legacy parameter is an idempotent success.
    after = module.cognito.admin_get_user(
        UserPoolId=properties["UserPoolId"], Username=properties["Username"]
    )
    assert after["UserStatus"] == before["UserStatus"]
    assert after["UserCreateDate"] == before["UserCreateDate"]
    assert result == {"PhysicalResourceId": f"{properties['UserPoolId']}:{properties['Username']}"}
    assert module.ssm.parameters == {}


def test_new_account_requires_private_invitation_and_never_permanent_password(
    provisioner, monkeypatch
):
    module, properties = provisioner
    with pytest.raises(ValueError, match="invitation email"):
        module.handler({"RequestType": "Create", "ResourceProperties": properties}, None)
    calls = []
    monkeypatch.setattr(module.cognito, "admin_create_user", lambda **kwargs: calls.append(kwargs))
    properties["InvitationEmail"] = "example-member@example.invalid"
    result = module.handler({"RequestType": "Create", "ResourceProperties": properties}, None)
    assert set(result) == {"PhysicalResourceId"}
    assert len(calls) == 1
    request = calls[0]
    assert request["DesiredDeliveryMediums"] == ["EMAIL"]
    assert request["UserAttributes"] == [{"Name": "email", "Value": properties["InvitationEmail"]}]
    assert "MessageAction" not in request
    assert len(request["TemporaryPassword"]) == 24
    assert module.ssm.parameters == {}


def test_delete_preserves_user_and_rejects_replacement_or_arbitrary_parameter(provisioner):
    module, properties = provisioner
    module.cognito.admin_create_user(
        UserPoolId=properties["UserPoolId"], Username=properties["Username"]
    )
    module.handler({"RequestType": "Delete", "ResourceProperties": properties}, None)
    assert module._user_exists(properties["UserPoolId"], properties["Username"])
    with pytest.raises(ValueError, match="replacement"):
        module.handler(
            {
                "RequestType": "Update",
                "ResourceProperties": properties,
                "OldResourceProperties": {**properties, "UserPoolId": "other-pool"},
            },
            None,
        )
    with pytest.raises(ValueError, match="location"):
        module.handler(
            {
                "RequestType": "Update",
                "ResourceProperties": {
                    **properties,
                    "PasswordParameterName": "/unrelated/password",
                },
            },
            None,
        )


def test_aws_errors_do_not_expose_private_values(provisioner, monkeypatch):
    module, properties = provisioner

    def fail(**_kwargs):
        raise ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "sensitive synthetic data"}},
            "DeleteParameter",
        )

    monkeypatch.setattr(
        module, "ssm", SimpleNamespace(delete_parameter=fail, exceptions=module.ssm.exceptions)
    )
    with pytest.raises(RuntimeError) as error:
        module.handler({"RequestType": "Delete", "ResourceProperties": properties}, None)
    assert str(error.value) == "AccessDeniedException"


@pytest.mark.parametrize("version", [None, 1, "prepare", True, 3])
@pytest.mark.parametrize("operation", ["Create", "Update", "Delete"])
def test_obsolete_policy_fails_before_any_account_or_parameter_operation(
    provisioner, monkeypatch, version, operation
):
    module, properties = provisioner

    def forbidden(**_kwargs):
        pytest.fail("Invalid policy must not access accounts or credentials")

    monkeypatch.setattr(module.cognito, "admin_get_user", forbidden)
    monkeypatch.setattr(module.cognito, "admin_create_user", forbidden)
    monkeypatch.setattr(module.ssm, "delete_parameter", forbidden)
    invalid = {**properties, "CredentialPolicyVersion": version}
    with pytest.raises(ValueError, match="policy version 2"):
        module.handler({"RequestType": operation, "ResourceProperties": invalid}, None)


def test_obsolete_rollback_cannot_restore_password_copies_or_reset_accounts(provisioner, monkeypatch):
    module, properties = provisioner
    module.cognito.admin_create_user(
        UserPoolId=properties["UserPoolId"], Username=properties["Username"]
    )
    module.ssm.put_parameter(
        Name=properties["PasswordParameterName"], Value="synthetic-legacy", Type="SecureString"
    )

    def forbidden(**_kwargs):
        pytest.fail("Rollback must not read or reset credentials")

    monkeypatch.setattr(module.cognito, "admin_set_user_password", forbidden)
    monkeypatch.setattr(module.ssm, "get_parameter", forbidden)
    prepared = {k: v for k, v in properties.items() if k != "CredentialPolicyVersion"}
    with pytest.raises(ValueError, match="policy version 2"):
        module.handler({"RequestType": "Update", "ResourceProperties": prepared}, None)
    assert module.ssm.parameters
    module.handler(
        {
            "RequestType": "Update",
            "ResourceProperties": {**properties, "CredentialPolicyVersion": "2"},
        },
        None,
    )
    assert not module.ssm.parameters
    with pytest.raises(ValueError, match="policy version 2"):
        module.handler({"RequestType": "Update", "ResourceProperties": prepared}, None)
    assert not module.ssm.parameters
    assert module._user_exists(properties["UserPoolId"], properties["Username"])
