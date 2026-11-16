"""Opt-in encrypted credential file for a headless box with no OS keyring or systemd.

Enable with ``PANTHER_SESSION_STORE=box-file``. Values are AES-256-GCM encrypted in
``PANTHER_BOX_SESSION_FILE`` (default ``~/.local/share/panther/box-session.enc``) with a random
key in ``PANTHER_BOX_SESSION_KEY`` (default ``~/.secrets/panther-session.key``). Both files and
their directories must be owner-only. The key is created on first save. The OS keyring stays
the default whenever this variable is unset.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile

from keyring.errors import KeyringError

OPT_IN = "PANTHER_SESSION_STORE"
OPT_IN_VALUE = "box-file"
DEFAULT_FILE = "~/.local/share/panther/box-session.enc"
DEFAULT_KEY = "~/.secrets/panther-session.key"
MAGIC = b"PBS1"


def enabled():
    value = os.environ.get(OPT_IN, "").strip()
    if value and value != OPT_IN_VALUE:
        raise KeyringError(f"{OPT_IN} must be {OPT_IN_VALUE} or unset")
    return value == OPT_IN_VALUE


def _private_dir(path, create):
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        return False
    details = path.stat()
    if details.st_uid != os.getuid() or details.st_mode & 0o077:
        raise KeyringError(f"{path} must be owned by you and mode 700")
    return True


def _private_file(path):
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid() or details.st_mode & 0o077:
        raise KeyringError(f"{path} must be a regular file owned by you with mode 600")
    return True


def _atomic_write(path, data):
    descriptor, candidate = tempfile.mkstemp(prefix=".panther-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(candidate, path)
    finally:
        if os.path.exists(candidate):
            os.unlink(candidate)


class BoxSessionStore:
    def __init__(self, filename=None, key_filename=None):
        self.path = Path(filename or os.environ.get("PANTHER_BOX_SESSION_FILE") or DEFAULT_FILE).expanduser()
        self.key_path = Path(key_filename or os.environ.get("PANTHER_BOX_SESSION_KEY") or DEFAULT_KEY).expanduser()
        if not self.path.is_absolute() or not self.key_path.is_absolute():
            raise KeyringError("Panther box credential paths must be absolute")

    def _key(self, create):
        present = _private_dir(self.key_path.parent, create) and _private_file(self.key_path)
        if not present:
            if not create:
                return None
            _atomic_write(self.key_path, secrets.token_bytes(32))
        key = self.key_path.read_bytes()
        if len(key) != 32:
            raise KeyringError("Panther box credential key is not 32 bytes")
        return key

    def _load(self):
        if not (_private_dir(self.path.parent, False) and _private_file(self.path)):
            return {}
        key = self._key(False)
        if key is None:
            raise KeyringError("Panther box credential key is missing")
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        blob = self.path.read_bytes()
        if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 12 + 16:
            raise KeyringError("Panther box credential file is malformed")
        nonce, sealed = blob[len(MAGIC):len(MAGIC) + 12], blob[len(MAGIC) + 12:]
        try:
            plain = AESGCM(key).decrypt(nonce, sealed, MAGIC)
        except InvalidTag as error:
            raise KeyringError("Cannot decrypt Panther box credentials") from error
        value = json.loads(plain)
        if not isinstance(value, dict):
            raise KeyringError("Panther box credential file is malformed")
        return value

    def _save(self, values):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = self._key(True)
        _private_dir(self.path.parent, True)
        _private_file(self.path)
        nonce = secrets.token_bytes(12)
        sealed = AESGCM(key).encrypt(nonce, json.dumps(values).encode(), MAGIC)
        _atomic_write(self.path, MAGIC + nonce + sealed)

    @staticmethod
    def _name(service, account):
        return f"{service}\n{account}"

    def get_password(self, service, account):
        return self._load().get(self._name(service, account))

    def set_password(self, service, account, value):
        values = self._load()
        values[self._name(service, account)] = value
        self._save(values)

    def delete_password(self, service, account):
        values = self._load()
        if values.pop(self._name(service, account), None) is not None:
            self._save(values)

    @contextmanager
    def refresh_lock(self):
        import fcntl

        _private_dir(self.path.parent, True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)
