"""Encrypted storage for the dashboard's data (job history, statistics).

This repository – and so its data/ folder – is public, so everything the
dashboard shows is stored encrypted. The settings page decrypts it in your
browser after you type the password; the password itself never leaves it.

Format (readable by the browser's built-in Web Crypto, no libraries):

* key   = PBKDF2-HMAC-SHA256(password, salt, 600 000 rounds) -> 256 bits
* file  = {"v": 1, "iv": base64, "ct": base64}
* ct    = AES-256-GCM(key, iv, gzip(JSON))   (ciphertext + 16-byte tag)
* data/history/vault.json holds the salt, the rounds, a small "check" value
  that tells whether a password is right, and the list of data shards.

The password comes from the DASHBOARD_PASSWORD secret. Without it nothing
is written (history is simply not kept), never stored in the clear.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITERATIONS = 600_000
CHECK_TEXT = "jobot-vault-v1"
META = "vault.json"


class WrongPassword(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def derive_key(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)


def seal(key: bytes, obj: Any) -> dict:
    """Compress, then encrypt: -> {"v", "iv", "ct"}."""
    raw = gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0)
    iv = os.urandom(12)
    return {"v": 1, "iv": _b64(iv), "ct": _b64(AESGCM(key).encrypt(iv, raw, None))}


def unseal(key: bytes, blob: dict) -> Any:
    try:
        raw = AESGCM(key).decrypt(base64.b64decode(blob["iv"]), base64.b64decode(blob["ct"]), None)
    except (InvalidTag, KeyError, ValueError) as exc:
        raise WrongPassword("wrong password, or the file is damaged") from exc
    return json.loads(gzip.decompress(raw).decode("utf-8"))


class Vault:
    """A folder of encrypted JSON files sharing one password-derived key."""

    def __init__(self, folder: str | Path, password: str):
        if not password:
            raise WrongPassword("no password")
        self.folder = Path(folder)
        self.meta: dict = {}
        meta_path = self.folder / META
        if meta_path.exists():
            self.meta = json.loads(meta_path.read_text(encoding="utf-8"))
            salt = base64.b64decode(self.meta["salt"])
            self.key = derive_key(password, salt, int(self.meta.get("iter", ITERATIONS)))
            if unseal(self.key, self.meta["check"]) != CHECK_TEXT:  # raises WrongPassword
                raise WrongPassword("wrong password")
        else:
            salt = os.urandom(16)
            self.key = derive_key(password, salt, ITERATIONS)
            self.meta = {"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITERATIONS, "salt": _b64(salt),
                         "check": seal(self.key, CHECK_TEXT), "shards": []}

    def path(self, name: str) -> Path:
        return self.folder / f"{name}.enc.json"

    def read(self, name: str, default: Any = None) -> Any:
        path = self.path(name)
        if not path.exists():
            return default
        return unseal(self.key, json.loads(path.read_text(encoding="utf-8")))

    def write(self, name: str, obj: Any) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path(name).write_text(json.dumps(seal(self.key, obj)) + "\n", encoding="utf-8")

    def save_meta(self, shards: list[str]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.meta["shards"] = sorted(shards)
        text = json.dumps(self.meta, indent=1) + "\n"
        path = self.folder / META
        if not path.exists() or path.read_text(encoding="utf-8") != text:  # keep daily commits small
            path.write_text(text, encoding="utf-8")
