#!/usr/bin/env python3
"""Unlock Panther's dedicated Keychain and request short-lived AWS credentials."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    for name in ("directory", "region", "session-duration", "cert-selector",
                 "role-arn", "profile-arn", "trust-anchor-arn"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    directory = Path(args.directory).resolve()
    if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        raise ValueError("Panther machine directory must be owner-only")
    config = json.loads((directory / "keychain.json").read_text())
    account = config.get("keychainSecretAccount")
    if not isinstance(account, str) or not re.fullmatch(r"[a-f0-9]{32}", account):
        raise ValueError("Dedicated Panther Keychain secret is not configured")
    keychain = directory / "panther.keychain-db"
    helper = directory / "aws_signing_helper"
    if keychain.is_symlink() or not keychain.is_file() or helper.is_symlink() or not helper.is_file():
        raise ValueError("Panther machine identity files are missing")
    secret = subprocess.run(["/usr/bin/security", "find-generic-password", "-s",
                             "Panther AWS machine access", "-a", account, "-w"],
                            capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["/usr/bin/security", "unlock-keychain", "-p", secret, str(keychain)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    command = [str(helper), "credential-process", "--region", args.region,
               "--session-duration", args.session_duration, "--cert-selector", args.cert_selector,
               "--role-arn", args.role_arn, "--profile-arn", args.profile_arn,
               "--trust-anchor-arn", args.trust_anchor_arn]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError):
        print("Panther machine credential process failed; inspect the local Keychain setup", file=sys.stderr)
        sys.exit(1)
