"""Bootstrap safety checks: no real Keychain, credentials, or AWS writes."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shlex
import sys
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("machine_access_setup", Path(__file__).resolve().parents[1] / "ops/aws-access/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
credential_spec = importlib.util.spec_from_file_location(
    "machine_credential_process", Path(__file__).resolve().parents[1] / "ops/aws-access/credential_process.py")
credential_process = importlib.util.module_from_spec(credential_spec)
credential_spec.loader.exec_module(credential_process)


def outputs():
    return {"RoleArn": "arn:aws:iam::123456789012:role/PantherLaptopAdministrator",
            "ProfileArn": "arn:aws:rolesanywhere:us-west-2:123456789012:profile/1234-abcd",
            "TrustAnchorArn": "arn:aws:rolesanywhere:us-west-2:123456789012:trust-anchor/4567-abcd"}


def test_command_uses_keychain_serial_and_no_plaintext_key(tmp_path):
    directory = tmp_path / "a directory with spaces"
    args = shlex.split(setup.credential_command(directory, "123456789012", outputs(), "ABCDE123"))
    assert args[:2] == ["/usr/bin/python3", str(directory / "credential_process.py")]
    assert args[args.index("--directory") + 1] == str(directory)
    assert args[args.index("--cert-selector") + 1] == "Key=x509Serial,Value=ABCDE123"
    assert args[args.index("--session-duration") + 1] == "3600"
    assert "--private-key" not in args and "--no-verify-ssl" not in args


def test_previous_command_is_exact_legacy_helper_invocation(tmp_path):
    args = shlex.split(setup.previous_credential_command(tmp_path, "123456789012", outputs(), "ABCDE123"))
    assert args[:2] == [str(tmp_path / "aws_signing_helper"), "credential-process"]
    assert args[args.index("--cert-selector") + 1] == "Key=x509Serial,Value=ABCDE123"
    assert args[args.index("--role-arn") + 1] == outputs()["RoleArn"]


@pytest.mark.parametrize("key,value", [
    ("RoleArn", "arn:aws:iam::123456789012:role/OtherAdministrator"),
    ("RoleArn", "arn:aws:iam::000000000000:role/PantherLaptopAdministrator"),
    ("ProfileArn", "arn:aws:rolesanywhere:us-east-1:123456789012:profile/1234-abcd"),
    ("TrustAnchorArn", "arn:aws:rolesanywhere:us-west-2:000000000000:trust-anchor/4567-abcd"),
    ("ProfileArn", None),
])
def test_outputs_cannot_redirect_credentials(tmp_path, key, value):
    data = outputs()
    data[key] = value
    with pytest.raises(ValueError):
        setup.credential_command(tmp_path, "123456789012", data, "ABCDE")


def test_external_owner_only_directory_required(tmp_path):
    tmp_path.chmod(0o700)
    assert setup.private_directory(tmp_path) == tmp_path
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError):
        setup.private_directory(tmp_path)
    with pytest.raises(ValueError):
        setup.private_directory(setup.REPO)


def test_native_errors_do_not_expose_private_logs(monkeypatch):
    class Failed:
        returncode = 1
        stdout = "private device identity"
        stderr = "private native diagnostic"
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **kw: Failed())
    with pytest.raises(RuntimeError, match="security failed") as caught:
        setup.run("/usr/bin/security", "import", "private identity")
    assert "private" not in str(caught.value)


def test_private_files_are_no_overwrite_and_owner_only(tmp_path):
    target = tmp_path / "private.json"
    setup.write_new(target, "first")
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        setup.write_new(target, "second")
    assert target.read_text() == "first"


@pytest.mark.parametrize("import_fails", [False, True])
def test_prepare_scopes_keychain_access_and_always_removes_ephemeral_keys(tmp_path, monkeypatch, import_fails):
    tmp_path.chmod(0o700)
    binary = b"fictional test executable"

    class Download:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return binary

    monkeypatch.setattr(setup.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(setup, "BINARIES", {"arm64": ("Aarch64", hashlib.sha256(binary).hexdigest())})
    monkeypatch.setattr(setup.urllib.request, "urlopen", lambda *a, **kw: Download())
    monkeypatch.setattr(setup, "DIAGNOSTICS", None)
    keychain = tmp_path.parent / (tmp_path.name + "-keychain")
    keychain.touch()
    commands = []
    saved_password = None

    def native(*args):
        nonlocal saved_password
        commands.append(args)
        if args[:2] == ("/usr/bin/security", "default-keychain"):
            return '"' + str(keychain) + '"'
        if args[:2] == ("/usr/bin/security", "list-keychains") and "-s" not in args:
            return '"' + str(keychain) + '"'
        if args[:2] == ("/usr/bin/security", "add-generic-password"):
            saved_password = args[args.index("-w") + 1]
        if args[:2] == ("/usr/bin/security", "find-generic-password"):
            return saved_password
        if args[0] == "openssl":
            for flag in ("-out", "-keyout"):
                if flag in args:
                    Path(args[args.index(flag) + 1]).write_text("fictional certificate or key")
        if import_fails and "priv" in args:
            raise RuntimeError("simulated native import failure")
        return ""

    monkeypatch.setattr(setup, "run", native)
    keychain_checks = []
    monkeypatch.setattr(setup, "keychain_access", lambda directory, repair=False: keychain_checks.append((directory, repair)))
    if import_fails:
        with pytest.raises(RuntimeError):
            setup.prepare(tmp_path, "123456789012", True)
        assert not (tmp_path / "machine-access.json").exists()
    else:
        setup.prepare(tmp_path, "123456789012", True)
        assert (tmp_path / "machine-access.json").stat().st_mode & 0o777 == 0o600
        assert keychain_checks == [(tmp_path, True)]
    assert not list(tmp_path.glob("certificate-build-*"))
    imports = [args for args in commands if args[:2] == ("/usr/bin/security", "import")]
    assert len(imports) == 2
    assert all(args[args.index("-k") + 1] == str(tmp_path / "panther.keychain-db") for args in imports)
    assert "-x" in imports[1] and "-T" in imports[1]
    assert imports[1][imports[1].index("-T") + 1] == str(tmp_path / "aws_signing_helper")
    assert all("-A" not in args and "-P" not in args for args in imports)


@pytest.mark.parametrize("repair", [False, True])
def test_keychain_check_pins_vendor_and_binary_and_explicit_repair_mode(tmp_path, monkeypatch, repair):
    tmp_path.chmod(0o700)
    binary = b"fictional pinned helper"
    (tmp_path / "aws_signing_helper").write_bytes(binary)
    (tmp_path / "certificate.pem").write_text("fictional certificate")
    (tmp_path / "machine-access.json").write_text('{"certificate":"fictional certificate"}')
    (tmp_path / "keychain.json").write_text('{"keychainSecretAccount":"' + "a" * 32 + '"}')
    (tmp_path / "panther.keychain-db").touch()
    monkeypatch.setattr(setup.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(setup, "BINARIES", {"arm64": ("Aarch64", hashlib.sha256(binary).hexdigest())})
    calls = []
    def native(*args):
        calls.append(args)
        if args[0] == "/usr/bin/swift":
            return '{"targetLabel":"Imported Private Key","keychainPath":"' + str(tmp_path / "panther.keychain-db") + '",' \
                   '"partitions":["apple-tool:"],"partitionPresent":false}' if args[-1] == "inspect" else \
                   '{"targetLabel":"Imported Private Key","keychainPath":"' + str(tmp_path / "panther.keychain-db") + '",' \
                   '"partitions":["apple-tool:","teamid:94KV3E626L"],"partitionPresent":true}'
        if args[:2] == ("/usr/bin/security", "find-generic-password"):
            return "synthetic password"
        return ""
    clipboard = {"value": ""}
    def process(args, **kwargs):
        if args[0] == "/usr/bin/pbcopy":
            clipboard["value"] = kwargs["input"]
            return SimpleNamespace(stdout="", returncode=0)
        if args[0] == "/usr/bin/pbpaste":
            return SimpleNamespace(stdout=clipboard["value"], returncode=0)
        raise AssertionError(args)
    monkeypatch.setattr(setup, "run", native)
    monkeypatch.setattr(setup.subprocess, "run", process)
    setup.keychain_access(tmp_path, repair=repair)
    assert len(calls) == (7 if repair else 4)
    assert calls[0][0] == "/usr/bin/codesign"
    assert calls[0][calls[0].index("-R") + 1].startswith('=identifier "com.amazon.aws.rolesanywhere"')
    assert "94KV3E626L" in calls[0][calls[0].index("-R") + 1]
    assert calls[1][:2] == ("/usr/bin/security", "find-generic-password")
    assert calls[2][:2] == ("/usr/bin/security", "unlock-keychain")
    assert calls[3][0] == "/usr/bin/swift"
    assert calls[3][-1] == ("inspect" if repair else "check")
    if repair:
        assert calls[5][0] == "/usr/bin/swift" and calls[5][-1] == "repair"
        assert calls[6][-1] == "check"
        assert clipboard["value"] == ""
    (tmp_path / "aws_signing_helper").write_bytes(b"changed helper")
    with pytest.raises(ValueError, match="pinned official"):
        setup.keychain_access(tmp_path, repair=repair)
    assert len(calls) == (7 if repair else 4)
    (tmp_path / "aws_signing_helper").write_bytes(binary)
    (tmp_path / "certificate.pem").write_text("other certificate")
    with pytest.raises(ValueError, match="private deployment"):
        setup.keychain_access(tmp_path, repair=repair)
    assert len(calls) == (7 if repair else 4)


def test_missing_partition_uses_scoped_native_authorization_and_clears_clipboard(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    binary = b"fictional pinned helper"
    (tmp_path / "aws_signing_helper").write_bytes(binary)
    (tmp_path / "certificate.pem").write_text("fictional certificate")
    (tmp_path / "machine-access.json").write_text('{"certificate":"fictional certificate"}')
    (tmp_path / "keychain.json").write_text('{"keychainSecretAccount":"' + "a" * 32 + '"}')
    (tmp_path / "panther.keychain-db").touch()
    monkeypatch.setattr(setup.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(setup, "BINARIES", {"arm64": ("Aarch64", hashlib.sha256(binary).hexdigest())})
    calls = []

    def native(*args):
        calls.append(args)
        if args[:2] == ("/usr/bin/security", "find-generic-password"):
            return "synthetic password"
        if args[0] == "/usr/bin/swift":
            present = args[-1] == "check"
            return json.dumps({"targetLabel": "Imported Private Key",
                               "keychainPath": str(tmp_path / "panther.keychain-db"),
                               "partitions": ["teamid:94KV3E626L"] if present else [],
                               "partitionPresent": present})
        return ""

    clipboard = {"value": ""}
    def process(args, **kwargs):
        if args[0] == "/usr/bin/pbcopy":
            clipboard["value"] = kwargs["input"]
            return SimpleNamespace(stdout="", returncode=0)
        if args[0] == "/usr/bin/pbpaste":
            return SimpleNamespace(stdout=clipboard["value"], returncode=0)
        raise AssertionError(args)

    monkeypatch.setattr(setup, "run", native)
    monkeypatch.setattr(setup.subprocess, "run", process)
    setup.keychain_access(tmp_path, repair=True)
    assert [call[-1] for call in calls if call[0] == "/usr/bin/swift"] == ["inspect", "repair", "check"]
    assert clipboard["value"] == ""


def test_credential_process_unlocks_only_panther_keychain_and_invokes_pinned_helper(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    (tmp_path / "keychain.json").write_text('{"keychainSecretAccount":"' + "a" * 32 + '"}')
    (tmp_path / "panther.keychain-db").touch()
    (tmp_path / "aws_signing_helper").touch()
    args = ["credential_process.py", "--directory", str(tmp_path), "--region", "us-west-2",
            "--session-duration", "3600", "--cert-selector", "Key=x509Serial,Value=ABCDE",
            "--role-arn", outputs()["RoleArn"], "--profile-arn", outputs()["ProfileArn"],
            "--trust-anchor-arn", outputs()["TrustAnchorArn"]]
    monkeypatch.setattr(sys, "argv", args)
    calls = []

    def native(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[:2] == ["/usr/bin/security", "find-generic-password"]:
            return SimpleNamespace(stdout="synthetic password\n", returncode=0)
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(credential_process.subprocess, "run", native)
    assert credential_process.main() == 0
    assert calls[0][0][calls[0][0].index("-a") + 1] == "a" * 32
    assert calls[1][0] == ["/usr/bin/security", "unlock-keychain", "-p", "synthetic password",
                           str(tmp_path / "panther.keychain-db")]
    assert calls[2][0][:2] == [str(tmp_path / "aws_signing_helper"), "credential-process"]
    assert calls[2][0][calls[2][0].index("--role-arn") + 1] == outputs()["RoleArn"]
