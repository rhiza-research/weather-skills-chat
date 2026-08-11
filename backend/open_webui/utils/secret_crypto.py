"""AES-256-GCM encryption for secret values.

The data-encryption key is loaded from SECRETS_ENCRYPTION_KEY (32-byte
base64 or 64-char hex) when set. Otherwise a key is created once under
DATA_DIR and reused so ciphertext stays readable across restarts.

Ciphertext is bound to its scope+name via GCM AAD so rows cannot be swapped.
"""

import base64
import logging
import os
import stat
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from open_webui.env import DATA_DIR, SECRETS_ENCRYPTION_KEY, SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

KEY_FILE = Path(DATA_DIR) / "secret_store.key"
NONCE_SIZE = 12
KEY_SIZE = 32


def _decode_key(raw: str) -> bytes:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Empty encryption key")
    if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
        key = bytes.fromhex(raw)
    else:
        try:
            key = base64.b64decode(raw)
        except Exception as e:
            raise ValueError("SECRETS_ENCRYPTION_KEY must be 32-byte hex or base64") from e
    if len(key) != KEY_SIZE:
        raise ValueError("SECRETS_ENCRYPTION_KEY must decode to 32 bytes")
    return key


def _load_or_create_key() -> bytes:
    env_key = (SECRETS_ENCRYPTION_KEY or os.environ.get("SECRETS_ENCRYPTION_KEY", "")).strip()
    if env_key:
        return _decode_key(env_key)

    if KEY_FILE.exists():
        key = KEY_FILE.read_bytes()
        if len(key) == KEY_SIZE:
            return key
        raise ValueError(f"Invalid secret store key file: {KEY_FILE}")

    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(KEY_SIZE)
    KEY_FILE.write_bytes(key)
    try:
        os.chmod(KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    log.warning(
        "Generated %s for secret encryption. Set SECRETS_ENCRYPTION_KEY "
        "to a 32-byte key to manage it explicitly. Losing this file makes "
        "stored secrets unrecoverable.",
        KEY_FILE,
    )
    return key


_KEY: Optional[bytes] = None


def get_master_key() -> bytes:
    global _KEY
    if _KEY is None:
        _KEY = _load_or_create_key()
    return _KEY


def _aad(*, user_id: str, team_id: Optional[str], name: str) -> bytes:
    # Bind ciphertext to its row identity so DB-level swaps fail to decrypt.
    if team_id:
        return f"v1|team|{team_id}|{name}".encode("utf-8")
    return f"v1|personal|{user_id}|{name}".encode("utf-8")


def encrypt_secret(
    plaintext: str, *, name: str, user_id: str, team_id: Optional[str]
) -> Tuple[str, str]:
    if plaintext is None:
        raise ValueError("Secret value is required")
    data = plaintext.encode("utf-8")
    nonce = os.urandom(NONCE_SIZE)
    token = AESGCM(get_master_key()).encrypt(
        nonce, data, _aad(user_id=user_id, team_id=team_id, name=name)
    )
    return (
        base64.b64encode(token).decode("ascii"),
        base64.b64encode(nonce).decode("ascii"),
    )


def decrypt_secret(
    ciphertext: str,
    nonce: str,
    *,
    name: str,
    user_id: str,
    team_id: Optional[str],
) -> str:
    token = base64.b64decode(ciphertext)
    raw_nonce = base64.b64decode(nonce)
    data = AESGCM(get_master_key()).decrypt(
        raw_nonce, token, _aad(user_id=user_id, team_id=team_id, name=name)
    )
    return data.decode("utf-8")
