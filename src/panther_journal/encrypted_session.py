"""User-scoped systemd credential store for unattended Linux workers.

The encrypted file can be backed up, but its host key is intentionally not
portable. A restored worker on a different host must sign in again.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from keyring.errors import KeyringError

NAME = "panther-session"


class EncryptedSessionStore:
    def __init__(self, filename: str):
        self.path = Path(filename).expanduser()
        if not self.path.is_absolute():
            raise KeyringError("Panther credential path must be absolute")

    def _private_directory(self, create: bool) -> bool:
        parent = self.path.parent
        if create:
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise KeyringError("Panther credential directory must be private and not a symlink") from error
        try:
            try:
                os.fchmod(descriptor, 0o700)
            except PermissionError as error:
                raise KeyringError("Panther credential directory must be private") from error
            details = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if details.st_uid != os.getuid() or details.st_mode & 0o077:
            raise KeyringError("Panther credential directory must be private")
        return True

    def _private_file(self) -> bool:
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise KeyringError("Panther credential file must be private and not a symlink") from error
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
                raise KeyringError("Panther credential file must be private")
            try:
                os.fchmod(descriptor, 0o600)
            except PermissionError as error:
                raise KeyringError("Panther credential file must be private") from error
            details = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if details.st_uid != os.getuid() or details.st_mode & 0o077:
            raise KeyringError("Panther credential file must be private")
        return True

    def get_password(self, service: str, account: str) -> str | None:
        if not self._private_directory(False) or not self._private_file():
            return None
        try:
            result = subprocess.run(
                ["systemd-creds", "decrypt", "--user", f"--name={NAME}", str(self.path), "-"],
                check=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise KeyringError("Cannot decrypt Panther credentials") from error
        return result.stdout.decode("utf-8")

    def set_password(self, service: str, account: str, value: str) -> None:
        self._private_directory(True)
        self._private_file()
        descriptor, candidate = tempfile.mkstemp(prefix=".session-", dir=self.path.parent)
        os.close(descriptor)
        try:
            subprocess.run(
                [
                    "systemd-creds", "encrypt", "--user", "--with-key=host",
                    f"--name={NAME}", "-", candidate,
                ],
                input=value.encode("utf-8"),
                check=True,
                capture_output=True,
            )
            os.chmod(candidate, 0o600)
            os.replace(candidate, self.path)
        except (OSError, subprocess.CalledProcessError) as error:
            raise KeyringError("Cannot encrypt Panther credentials") from error
        finally:
            if os.path.exists(candidate):
                os.unlink(candidate)

    def delete_password(self, service: str, account: str) -> None:
        if self._private_directory(False) and self._private_file():
            self.path.unlink()

    @contextmanager
    def refresh_lock(self):
        import fcntl

        self._private_directory(True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            details = os.fstat(descriptor)
            if details.st_uid != os.getuid() or not stat.S_ISREG(details.st_mode) or details.st_mode & 0o077:
                raise KeyringError("Panther credential lock must be private")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)
