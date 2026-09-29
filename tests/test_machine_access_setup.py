"""Bootstrap safety checks: no real Keychain, credentials, or AWS writes."""
import importlib.util
import hashlib
from pathlib import Path
import shlex

import pytest

spec = importlib.util.spec_from_file_location("machine_access_setup", Path(__file__).resolve().parents[1] / "ops/aws-access/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def outputs():
    return {"RoleArn": "arn:aws:iam::123456789012:role/PantherLaptopAdministrator",
            "ProfileArn": "arn:aws:rolesanywhere:us-west-2:123456789012:profile/1234-abcd",
            "TrustAnchorArn": "arn:aws:rolesanywhere:us-west-2:123456789012:trust-anchor/4567-abcd"}


def test_command_uses_keychain_serial_and_no_plaintext_key(tmp_path):
    directory = tmp_path / "a directory with spaces"
    args = shlex.split(setup.credential_command(directory, "123456789012", outputs(), "ABCDE123"))
    assert args[0] == str(directory / "aws_signing_helper")
    assert args[1] == "credential-process"
    assert args[args.index("--cert-selector") + 1] == "Key=x509Serial,Value=ABCDE123"
    assert args[args.index("--session-duration") + 1] == "3600"
    assert "--private-key" not in args and "--no-verify-ssl" not in args


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

    def native(*args):
        commands.append(args)
        if args[:2] == ("/usr/bin/security", "default-keychain"):
            return '"' + str(keychain) + '"'
        if args[0] == "openssl":
            for flag in ("-out", "-keyout"):
                if flag in args:
                    Path(args[args.index(flag) + 1]).write_text("fictional certificate or key")
        if import_fails and "priv" in args:
            raise RuntimeError("simulated native import failure")
        return ""

    monkeypatch.setattr(setup, "run", native)
    if import_fails:
        with pytest.raises(RuntimeError):
            setup.prepare(tmp_path, "123456789012", True)
        assert not (tmp_path / "machine-access.json").exists()
    else:
        setup.prepare(tmp_path, "123456789012", True)
        assert (tmp_path / "machine-access.json").stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("certificate-build-*"))
    imports = [args for args in commands if args[:2] == ("/usr/bin/security", "import")]
    assert len(imports) == 2
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
    monkeypatch.setattr(setup.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(setup, "BINARIES", {"arm64": ("Aarch64", hashlib.sha256(binary).hexdigest())})
    calls = []
    monkeypatch.setattr(setup, "run", lambda *args: calls.append(args) or "verified")
    setup.keychain_access(tmp_path, repair=repair)
    assert len(calls) == 2
    assert calls[0][0] == "/usr/bin/codesign"
    assert calls[0][calls[0].index("-R") + 1].startswith('=identifier "com.amazon.aws.rolesanywhere"')
    assert "94KV3E626L" in calls[0][calls[0].index("-R") + 1]
    assert calls[1][0] == "/usr/bin/swift"
    assert calls[1][-1] == ("repair" if repair else "check")
    (tmp_path / "aws_signing_helper").write_bytes(b"changed helper")
    with pytest.raises(ValueError, match="pinned official"):
        setup.keychain_access(tmp_path, repair=repair)
    assert len(calls) == 2
    (tmp_path / "aws_signing_helper").write_bytes(binary)
    (tmp_path / "certificate.pem").write_text("other certificate")
    with pytest.raises(ValueError, match="private deployment"):
        setup.keychain_access(tmp_path, repair=repair)
    assert len(calls) == 2
