import importlib
from pathlib import Path

import pytest


@pytest.mark.parametrize("capability", ["MODEL_PUBLISHERS", "MODEL_WORKERS", "ASSET_MIGRATORS"])
def test_private_capability_configuration_and_missing_defaults(monkeypatch, capability):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "infra/lambda/media-api"))
    policy = importlib.import_module("access_policy")
    claims = {"sub":"synthetic-sub", "cognito:username":"custom-account"}
    monkeypatch.delenv(capability, raising=False)
    assert not policy.authorized(claims, capability)
    monkeypatch.setenv(capability, "custom-account")
    assert policy.authorized(claims, capability)
    assert not policy.authorized({**claims, "sub":""}, capability)
    assert not policy.authorized({**claims, "cognito:username":"example-member"}, capability)
    assert not policy.authorized({"sub":"synthetic-sub"}, capability)
    monkeypatch.setenv(capability, "")
    assert not policy.authorized(claims, capability)
