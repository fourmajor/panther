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
        keychain = run("/usr/bin/security", "default-keychain", "-d", "user").strip('"')
        if not keychain or not Path(keychain).is_file():
            raise ValueError("An existing unlocked user Keychain is required")
        run("/usr/bin/security", "import", str(cert), "-k", keychain, "-t", "cert", "-f", "pemseq")
        run("/usr/bin/security", "import", str(import_key), "-k", keychain, "-t", "priv", "-f", "openssl", "-x", "-T", str(helper))
        configuration = {"schemaVersion": 1, "account": account, "region": "us-west-2",
                         "administratorAccessApproved": True, "enabled": True,
                         "caCertificate": ca.read_text(), "certificate": cert.read_text()}
        write_new(directory / "machine-access.json", json.dumps(configuration, indent=2) + "\n")
        write_new(directory / "certificate.pem", cert.read_text())
    finally:
        shutil.rmtree(temporary)
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
    return shlex.join([str(directory / "aws_signing_helper"), "credential-process", "--region", "us-west-2",
                       "--session-duration", "3600", "--cert-selector", f"Key=x509Serial,Value={serial}",
                       "--role-arn", outputs["RoleArn"], "--profile-arn", outputs["ProfileArn"],
                       "--trust-anchor-arn", outputs["TrustAnchorArn"]])


def configure(directory, outputs_file):
    directory = private_directory(directory)
    configuration = json.loads((directory / "machine-access.json").read_text())
    if configuration.get("administratorAccessApproved") is not True or configuration.get("enabled") is not True:
        raise ValueError("Enabled, owner-approved private configuration is required")
    outputs = json.loads(Path(outputs_file).read_text())["PantherMachineAccess"]
    serial = run("openssl", "x509", "-in", str(directory / "certificate.pem"), "-serial", "-noout").removeprefix("serial=")
    command = credential_command(directory, configuration["account"], outputs, serial)
    if os.environ.get("AWS_CONFIG_FILE") or os.environ.get("AWS_SHARED_CREDENTIALS_FILE"):
        raise ValueError("Custom AWS config/credential paths must be configured explicitly; refusing to guess")
    config = Path.home() / ".aws" / "config"
    if config.is_symlink():
        raise ValueError("Refusing to update a symlinked AWS config")
    if config.exists():
        parser = configparser.RawConfigParser()
        parser.read(config)
        section = "profile " + PROFILE
        if parser.has_section(section):
            expected = {"credential_process": command, "region": "us-west-2", "output": "json"}
            if dict(parser.items(section)) != expected:
                raise ValueError("Existing laptop profile differs; refusing to overwrite its configuration")
        else:
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
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            prepare(args.directory, args.account, args.approve_unattended_administrator)
        else:
            configure(args.directory, args.outputs)
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
