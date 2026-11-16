"""Set the first password of passwordBootstrap worker accounts. Run by Deploy after CDK.

Reads the identities file (PANTHER_IDENTITIES_FILE) and PANTHER_BOOTSTRAP_PASSWORDS, a JSON object
mapping username to password (a GitHub Actions secret). Only an account still in
FORCE_CHANGE_PASSWORD is touched, so a later password change is never overwritten. Passwords
are passed to the AWS CLI through a private temporary file and are never printed.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def aws(*args, stdin_file=None):
    command = ["aws", *args, "--region", "us-west-2", "--output", "json"]
    if stdin_file:
        command += ["--cli-input-json", f"file://{stdin_file}"]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        # The CLI error never contains the input file contents.
        raise SystemExit(f"aws {args[0]} {args[1]} failed: {result.stderr.strip()[:300]}")
    return json.loads(result.stdout or "{}")


def pool_id():
    stack = aws("cloudformation", "describe-stacks", "--stack-name", "PantherMediaExplorer")
    for output in stack["Stacks"][0].get("Outputs", []):
        if output["OutputKey"] == "UserPoolId":
            return output["OutputValue"]
    raise SystemExit("PantherMediaExplorer has no UserPoolId output")


def main():
    identities = json.loads(Path(os.environ["PANTHER_IDENTITIES_FILE"]).read_text())
    names = identities.get("passwordBootstrap") or []
    if not names:
        print("No passwordBootstrap accounts.")
        return
    raw = os.environ.get("PANTHER_BOOTSTRAP_PASSWORDS", "").strip()
    passwords = json.loads(raw) if raw else {}
    pool = pool_id()
    for name in names:
        status = aws("cognito-idp", "admin-get-user", "--user-pool-id", pool, "--username", name)["UserStatus"]
        if status != "FORCE_CHANGE_PASSWORD":
            print(f"{name}: {status}; password left unchanged.")
            continue
        password = passwords.get(name)
        if not isinstance(password, str) or not password:
            print(f"{name}: waiting for a PANTHER_BOOTSTRAP_PASSWORDS entry.", file=sys.stderr)
            continue
        with tempfile.NamedTemporaryFile("w", dir=os.environ.get("RUNNER_TEMP"), delete=False) as stream:
            os.chmod(stream.name, 0o600)
            json.dump({"UserPoolId": pool, "Username": name, "Password": password, "Permanent": True}, stream)
        try:
            aws("cognito-idp", "admin-set-user-password", stdin_file=stream.name)
        finally:
            os.unlink(stream.name)
        print(f"{name}: first password set.")


if __name__ == "__main__":
    main()
