"""Age-encrypted JSON vault.

The master ``age`` X25519 identity is stored in the OS keyring under
``service="jarvis", username="vault"``. On WSL this maps to libsecret
through dbus if available; otherwise we fall back to a file-backed
keyring (after warning the user).

The vault file itself is a single age-encrypted blob containing a JSON
object ``{name: value}``.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import keyring

from jarvis.config import get_settings
from jarvis.utils.logging import get_logger

log = get_logger("vault")

_KEYRING_SERVICE = "jarvis"
_KEYRING_USER = "vault"


def _generate_identity() -> tuple[str, str]:
    """Return ``(identity, recipient)``. Uses pyrage if present, else `age`."""
    try:
        import pyrage  # type: ignore[import-untyped]
    except ImportError:
        pyrage = None

    if pyrage is not None:
        ident = pyrage.x25519.Identity.generate()
        return ident.to_str(), ident.to_public().to_str()

    # Fallback: `age-keygen` CLI.
    import subprocess

    out = subprocess.check_output(["age-keygen"]).decode("utf-8")
    identity = ""
    recipient = ""
    for line in out.splitlines():
        if line.startswith("AGE-SECRET-KEY"):
            identity = line.strip()
        if line.startswith("# public key:"):
            recipient = line.split(":", 1)[1].strip()
    return identity, recipient


def _encrypt(identity_str: str, plaintext: bytes) -> bytes:
    import pyrage

    ident = pyrage.x25519.Identity.from_str(identity_str)
    return pyrage.encrypt(plaintext, [ident.to_public()])


def _decrypt(identity_str: str, ciphertext: bytes) -> bytes:
    import pyrage

    ident = pyrage.x25519.Identity.from_str(identity_str)
    return pyrage.decrypt(ciphertext, [ident])


class Vault:
    """Tiny key→value secret store, age-encrypted on disk."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (get_settings().state_path / "vault.age")

    # ---------------- identity management ---------------- #

    def _identity(self, create_if_missing: bool = False) -> str:
        ident = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
        if ident:
            return ident
        if not create_if_missing:
            raise RuntimeError("vault identity not found in keyring; run `jarvis vault init` first")
        identity, recipient = _generate_identity()
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, identity)
        log.info("vault_identity_created", recipient=recipient)
        return identity

    # ---------------- file io ---------------- #

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        identity = self._identity()
        blob = self._path.read_bytes()
        return json.loads(_decrypt(identity, blob).decode("utf-8"))

    def _write(self, data: dict[str, str]) -> None:
        identity = self._identity(create_if_missing=True)
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        ct = _encrypt(identity, payload)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_bytes(ct)
        # Tight perms: 0600.
        os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)

    # ---------------- public api ---------------- #

    def init(self) -> str:
        """Create the vault if it doesn't exist; return the recipient pubkey."""
        identity = self._identity(create_if_missing=True)
        if not self._path.exists():
            self._write({})
        try:
            import pyrage

            ident = pyrage.x25519.Identity.from_str(identity)
            return ident.to_public().to_str()
        except Exception:  # noqa: BLE001
            return "<unknown>"

    def get(self, name: str) -> str | None:
        return self._read().get(name)

    def set(self, name: str, value: str) -> None:
        data = self._read()
        data[name] = value
        self._write(data)

    def delete(self, name: str) -> bool:
        data = self._read()
        if name not in data:
            return False
        del data[name]
        self._write(data)
        return True

    def keys(self) -> list[str]:
        return sorted(self._read().keys())


_DEFAULT: Vault | None = None


def default_vault() -> Vault:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Vault()
    return _DEFAULT
