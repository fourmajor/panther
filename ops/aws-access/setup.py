#!/usr/bin/env python3
"""Local bootstrap only. AWS resources and permissions are created exclusively by CDK."""

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile
import uuid
import urllib.request

RELEASE = "1.8.5"
BINARIES = {
    "arm64": ("Aarch64", "ac4b656cd83ffde5a6e9e8f2317ffb90e036c9bb704cc80faa6aee414b55915a"),
    "x86_64": ("X86_64", "aab355e1e7468056be88a56bbfb030ea33ff32bef2ce20f5dd6a0b1cae5aae5a"),
}
PROFILE = "panther-laptop-admin"
REPO = Path(__file__).resolve().parents[2]
DIAGNOSTICS = None
KEYCHAIN_SERVICE = "Panther AWS machine access"


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        # Native commands may mention local certificate identifiers. Do not forward their logs.
        if DIAGNOSTICS is not None:
            write_new(DIAGNOSTICS / ("native-failure-" + uuid.uuid4().hex + ".log"), result.stderr)
        raise RuntimeError(f"{Path(args[0]).name} failed; check local Keychain authorization or tool installation")
    return result.stdout.strip()


def private_directory(value):
    directory = Path(value).expanduser().resolve()
    if directory == REPO or REPO in directory.parents:
        raise ValueError("Machine files must be outside the repository")
    if not directory.is_dir() or directory.stat().st_mode & 0o077 or directory.stat().st_uid != os.getuid():
        raise ValueError("Use an owner-owned directory with mode 700")
    return directory


def write_new(path, content):
    with open(path, "x", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        stream.write(content)


def keychain_password(directory):
    account = json.loads((directory / "keychain.json").read_text()).get("keychainSecretAccount")
    if not isinstance(account, str) or not re.fullmatch(r"[a-f0-9]{32}", account):
        raise ValueError("Dedicated Panther Keychain configuration is required")
    return run("/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
               "-a", account, "-w")


def unlock_keychain(directory):
    keychain = directory / "panther.keychain-db"
    if not keychain.is_file() or keychain.is_symlink():
        raise ValueError("Dedicated Panther Keychain is missing")
    run("/usr/bin/security", "unlock-keychain", "-p", keychain_password(directory), str(keychain))
    return keychain


def add_to_search_list(keychain):
    current = run("/usr/bin/security", "list-keychains", "-d", "user").splitlines()
    paths = [line.strip().strip('"') for line in current if line.strip()]
    if not paths or any(not path.startswith("/") for path in paths):
        raise ValueError("Cannot safely preserve the user Keychain search list")
    if str(keychain) not in paths:
        run("/usr/bin/security", "list-keychains", "-d", "user", "-s", *paths, str(keychain))


def prepare(directory, account, approved):
    global DIAGNOSTICS
    if platform.system() != "Darwin" or platform.machine() not in BINARIES:
        raise ValueError("This bootstrap supports macOS arm64/x86_64 only")
    if not approved or not re.fullmatch(r"\d{12}", account):
        raise ValueError("Explicit unattended administrator approval and a 12-digit account are required")
    directory = private_directory(directory)
    DIAGNOSTICS = directory
    if any(directory.iterdir()):
        raise ValueError("Use a new empty directory; never overwrite an existing identity")
    architecture, expected = BINARIES[platform.machine()]
    url = f"https://rolesanywhere.amazonaws.com/releases/{RELEASE}/{architecture}/MacOS/Sonoma/aws_signing_helper"
    with urllib.request.urlopen(url, timeout=60) as response:
        binary = response.read(100 * 1024 * 1024 + 1)
    if hashlib.sha256(binary).hexdigest() != expected:
        raise ValueError("Official AWS helper checksum mismatch")
    helper = directory / "aws_signing_helper"
    helper.write_bytes(binary)
    helper.chmod(0o700)
    run("/usr/bin/codesign", "--verify", "--strict", str(helper))
    issuer = "panther-ca-" + uuid.uuid4().hex
    subject = "panther-device-" + uuid.uuid4().hex
    # Only this owned ephemeral directory is deleted. Issuer keys are never retained.
    temporary = Path(tempfile.mkdtemp(prefix="certificate-build-", dir=directory))
    try:
        ca_key, ca, key, csr, cert, import_key = [temporary / name for name in
                                               ("ca.key", "ca.pem", "device.key", "device.csr", "device.pem", "import.key")]
        run("openssl", "req", "-new", "-x509", "-newkey", "rsa:3072", "-nodes", "-sha256",
            "-days", "1825", "-subj", f"/CN={issuer}", "-keyout", str(ca_key), "-out", str(ca),
            "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        run("openssl", "req", "-new", "-newkey", "rsa:3072", "-nodes", "-sha256",
            "-subj", f"/CN={subject}", "-keyout", str(key), "-out", str(csr))
        extension = temporary / "extensions.conf"
        write_new(extension, "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
                  "extendedKeyUsage=clientAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n")
        run("openssl", "x509", "-req", "-in", str(csr), "-CA", str(ca), "-CAkey", str(ca_key),
            "-set_serial", "0x" + uuid.uuid4().hex, "-sha256", "-days", "365", "-extfile", str(extension), "-out", str(cert))
        run("openssl", "verify", "-CAfile", str(ca), str(cert))
        # Native Keychain imports traditional RSA PEM without PKCS12 password/algorithm
        # compatibility pitfalls. Plaintext keys remain only in this owner-only build directory.
        run("openssl", "rsa", "-traditional", "-in", str(key), "-out", str(import_key))
        login_keychain = run("/usr/bin/security", "default-keychain", "-d", "user").strip('"')
        if not login_keychain or not Path(login_keychain).is_file():
            raise ValueError("An existing user Keychain is required")
        password = secrets.token_urlsafe(48)
        secret_account = uuid.uuid4().hex
        keychain = directory / "panther.keychain-db"
        run("/usr/bin/security", "create-keychain", "-p", password, str(keychain))
        run("/usr/bin/security", "lock-keychain", str(keychain))
        run("/usr/bin/security", "unlock-keychain", "-p", password, str(keychain))
        run("/usr/bin/security", "import", str(cert), "-k", str(keychain), "-t", "cert", "-f", "pemseq")
        run("/usr/bin/security", "import", str(import_key), "-k", str(keychain), "-t", "priv", "-f", "openssl", "-x", "-T", str(helper))
        run("/usr/bin/security", "add-generic-password", "-a", secret_account,
            "-s", KEYCHAIN_SERVICE, "-w", password, "-T", "/usr/bin/security", login_keychain)
        if run("/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
               "-a", secret_account, "-w") != password:
            raise ValueError("Generated Panther Keychain password did not round-trip exactly")
        add_to_search_list(keychain)
        configuration = {"schemaVersion": 1, "account": account, "region": "us-west-2",
                         "administratorAccessApproved": True, "enabled": True,
                         "caCertificate": ca.read_text(), "certificate": cert.read_text()}
        write_new(directory / "machine-access.json", json.dumps(configuration, indent=2) + "\n")
        write_new(directory / "keychain.json", json.dumps({"keychainSecretAccount": secret_account}) + "\n")
        write_new(directory / "certificate.pem", cert.read_text())
    finally:
        shutil.rmtree(temporary)
    keychain_access(directory, repair=True)
    print("Certificate imported as non-extractable with helper-only access. Ephemeral issuer/key files removed.")
    print("Private CDK configuration prepared; no AWS resource has been created. Certificate valid for one year.")


def credential_command(directory, account, outputs, serial):
    expected = {
        "RoleArn": rf"arn:aws:iam::{account}:role/PantherLaptopAdministrator",
        "ProfileArn": rf"arn:aws:rolesanywhere:us-west-2:{account}:profile/[a-f0-9-]+",
        "TrustAnchorArn": rf"arn:aws:rolesanywhere:us-west-2:{account}:trust-anchor/[a-f0-9-]+",
    }
    if not re.fullmatch(r"\d{12}", account) or not re.fullmatch(r"[A-Fa-f0-9]{1,64}", serial):
        raise ValueError("Invalid account or certificate serial")
    if not isinstance(outputs, dict) or any(not isinstance(outputs.get(k), str) or
                                           not re.fullmatch(pattern, outputs[k]) for k, pattern in expected.items()):
        raise ValueError("CDK outputs must match the approved account, region, and exact role")
    return shlex.join(["/usr/bin/python3", str(directory / "credential_process.py"),
                       "--directory", str(directory), "--region", "us-west-2",
                       "--session-duration", "3600", "--cert-selector", f"Key=x509Serial,Value={serial}",
                       "--role-arn", outputs["RoleArn"], "--profile-arn", outputs["ProfileArn"],
                       "--trust-anchor-arn", outputs["TrustAnchorArn"]])


def previous_credential_command(directory, account, outputs, serial):
    # Only for an exact, explicitly supplied predecessor when rotating the initial deployment.
    credential_command(directory, account, outputs, serial)
    return shlex.join([str(directory / "aws_signing_helper"), "credential-process", "--region", "us-west-2",
                       "--session-duration", "3600", "--cert-selector", f"Key=x509Serial,Value={serial}",
                       "--role-arn", outputs["RoleArn"], "--profile-arn", outputs["ProfileArn"],
                       "--trust-anchor-arn", outputs["TrustAnchorArn"]])


def keychain_access(directory, repair=False):
    global DIAGNOSTICS
    directory = private_directory(directory)
    DIAGNOSTICS = directory
    helper = directory / "aws_signing_helper"
    if platform.system() != "Darwin" or platform.machine() not in BINARIES:
        raise ValueError("Keychain verification requires macOS")
    if hashlib.sha256(helper.read_bytes()).hexdigest() != BINARIES[platform.machine()][1]:
        raise ValueError("Installed helper does not match the pinned official binary")
    configuration = json.loads((directory / "machine-access.json").read_text())
    if (directory / "certificate.pem").read_text() != configuration.get("certificate"):
        raise ValueError("Certificate does not match private deployment configuration")
    run("/usr/bin/codesign", "--verify", "--strict", "-R",
        '=identifier "com.amazon.aws.rolesanywhere" and anchor apple generic and certificate leaf[subject.OU] = "94KV3E626L"', str(helper))
    keychain = unlock_keychain(directory)
    source = str(Path(__file__).with_name("keychain-access.swift"))
    inputs = (str(directory / "certificate.pem"), str(helper))
    state = json.loads(run("/usr/bin/swift", source, *inputs, "inspect" if repair else "check"))
    if (state.get("targetLabel") != "Imported Private Key" or
            state.get("keychainPath") != str(keychain) or not isinstance(state.get("partitions"), list)):
        raise ValueError("Native preflight did not identify the expected unique Panther key")
    if repair and not state.get("partitionPresent"):
        # The native preflight has proven this exact label matches exactly one private signing key
        # in this specific Keychain, and that it is the non-extractable certificate identity.
        partitions = state["partitions"] + ["teamid:94KV3E626L"]
        if not set(partitions) <= {"apple-tool:", "apple:", "teamid:94KV3E626L"}:
            raise ValueError("Unexpected key partition; refusing to broaden it")
        password = keychain_password(directory)
        subprocess.run(["/usr/bin/pbcopy"], input=password, text=True, check=True)
        print("Paste the temporary Panther-only Keychain password into the macOS authorization dialog.", flush=True)
        try:
            run("/usr/bin/swift", source, *inputs, "repair")
        finally:
            clipboard = subprocess.run(["/usr/bin/pbpaste"], capture_output=True, text=True, check=True).stdout
            if clipboard == password:
                subprocess.run(["/usr/bin/pbcopy"], input="", text=True, check=True)
        state = json.loads(run("/usr/bin/swift", source, *inputs, "check"))
    if state.get("partitionPresent") is not True:
        raise ValueError("Verified AWS helper partition is not persisted")
    print("Verified non-extractable Panther key with exclusive helper signing access")


def configure(directory, outputs_file, previous_directory=None, previous_outputs=None):
    directory = private_directory(directory)
    keychain_access(directory)
    configuration = json.loads((directory / "machine-access.json").read_text())
    if configuration.get("administratorAccessApproved") is not True or configuration.get("enabled") is not True:
        raise ValueError("Enabled, owner-approved private configuration is required")
    outputs = json.loads(Path(outputs_file).read_text())["PantherMachineAccess"]
    serial = run("openssl", "x509", "-in", str(directory / "certificate.pem"), "-serial", "-noout").removeprefix("serial=")
    command = credential_command(directory, configuration["account"], outputs, serial)
    process = directory / "credential_process.py"
    if not process.exists():
        write_new(process, Path(__file__).with_name("credential_process.py").read_text())
    if os.environ.get("AWS_CONFIG_FILE") or os.environ.get("AWS_SHARED_CREDENTIALS_FILE"):
        raise ValueError("Custom AWS config/credential paths must be configured explicitly; refusing to guess")
    config = Path.home() / ".aws" / "config"
    if config.is_symlink():
        raise ValueError("Refusing to update a symlinked AWS config")
    if bool(previous_directory) != bool(previous_outputs):
        raise ValueError("Previous directory and outputs must be supplied together for rotation")
    backup_required = False
    if config.exists():
        parser = configparser.RawConfigParser()
        parser.read(config)
        section = "profile " + PROFILE
        if parser.has_section(section):
            expected = {"credential_process": command, "region": "us-west-2", "output": "json"}
            current = dict(parser.items(section))
            if current != expected:
                if not previous_directory:
                    raise ValueError("Existing laptop profile differs; explicit predecessor is required")
                prior = private_directory(previous_directory)
                old_config = json.loads((prior / "machine-access.json").read_text())
                if old_config.get("account") != configuration["account"]:
                    raise ValueError("Previous machine identity belongs to another account")
                old_outputs = json.loads(Path(previous_outputs).read_text())["PantherMachineAccess"]
                old_serial = run("openssl", "x509", "-in", str(prior / "certificate.pem"),
                                 "-serial", "-noout").removeprefix("serial=")
                old_command = previous_credential_command(prior, configuration["account"], old_outputs, old_serial)
                if current != {"credential_process": old_command, "region": "us-west-2", "output": "json"}:
                    raise ValueError("Existing laptop profile is not the exact specified predecessor")
                backup_required = True
        else:
            backup_required = True
    if backup_required:
        write_new(directory / ("aws-config-backup-" + uuid.uuid4().hex), config.read_text())
    for key, value in (("credential_process", command), ("region", "us-west-2"), ("output", "json")):
        run("aws", "configure", "set", key, value, "--profile", PROFILE)
    config.chmod(0o600)
    identity = json.loads(run("aws", "sts", "get-caller-identity", "--profile", PROFILE, "--output", "json"))
    if identity.get("Account") != configuration["account"] or ":assumed-role/PantherLaptopAdministrator/" not in identity.get("Arn", ""):
        raise ValueError("Credential validation returned an unexpected account or role")
    print("Verified renewable laptop administrator profile. Existing SSO profiles were preserved.")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    preparation = subparsers.add_parser("prepare")
    preparation.add_argument("--directory", required=True)
    preparation.add_argument("--account", required=True)
    preparation.add_argument("--approve-unattended-administrator", action="store_true")
    configuration = subparsers.add_parser("configure")
    configuration.add_argument("--directory", required=True)
    configuration.add_argument("--outputs", required=True)
    configuration.add_argument("--previous-directory")
    configuration.add_argument("--previous-outputs")
    keychain = subparsers.add_parser("keychain")
    keychain.add_argument("--directory", required=True)
    keychain.add_argument("--repair", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            prepare(args.directory, args.account, args.approve_unattended_administrator)
        elif args.action == "configure":
            configure(args.directory, args.outputs, args.previous_directory, args.previous_outputs)
        else:
            keychain_access(args.directory, args.repair)
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
