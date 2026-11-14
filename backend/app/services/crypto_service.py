import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Any, List, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, Text
from sqlalchemy.types import TypeDecorator

from ..config import DATA_DIR, _is_prod, reload_env_files

logger = logging.getLogger(__name__)

_KEY_FILE: Path = DATA_DIR / ".fernet.key"
_LEGACY_PREFIX = "enc:"
_VERSIONED_PREFIX = "enc:v1:"


def _derive_fernet_bytes(raw_secret: str) -> bytes:
    """Normalizes a valid Fernet key or derives a deterministic 32-byte urlsafe key from a secret string."""
    clean = raw_secret.strip()
    try:
        Fernet(clean.encode("utf-8"))
        return clean.encode("utf-8")
    except Exception:
        digest = hashlib.sha256(clean.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)


def _get_fernet_key_bytes() -> bytes:
    """
    Loads the active 256-bit Fernet symmetric encryption key.
    - In production (_is_prod=True), requires ENCRYPTION_KEY in environment variables and raises RuntimeError if absent.
    - In local development, reads ENCRYPTION_KEY or persists a stable key in DATA_DIR/.fernet.key (never regenerated on restart).
    """
    reload_env_files()
    env_key = os.getenv("ENCRYPTION_KEY", "").strip()
    if env_key:
        return _derive_fernet_bytes(env_key)

    if _is_prod:
        raise RuntimeError(
            "FATAL SECURITY ERROR: ENCRYPTION_KEY environment variable is required in production "
            "to guarantee stable field-level encryption across restarts and deployments."
        )

    if _KEY_FILE.exists():
        raw = _KEY_FILE.read_bytes().strip()
        if raw:
            return raw

    key = Fernet.generate_key()
    try:
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_bytes(key)
    except Exception as e:
        logger.warning(f"Could not persist local encryption key file: {e}")
    return key


def _get_previous_fernet_instances() -> List[Fernet]:
    """Returns Fernet instances for comma-separated ENCRYPTION_KEY_PREVIOUS values to support safe key rotation."""
    prev_raw = os.getenv("ENCRYPTION_KEY_PREVIOUS", "").strip()
    if not prev_raw:
        return []
    instances: List[Fernet] = []
    for part in prev_raw.split(","):
        if part.strip():
            try:
                instances.append(Fernet(_derive_fernet_bytes(part.strip())))
            except Exception as e:
                logger.warning(f"Invalid key in ENCRYPTION_KEY_PREVIOUS skipped: {e}")
    return instances


def _get_fernet() -> Fernet:
    return Fernet(_get_fernet_key_bytes())


def blind_index(value: Optional[str]) -> str:
    """Computes a keyed HMAC-SHA256 blind index for exact-match SQL lookups without storing plaintext."""
    norm = (value or "").strip().lower()
    secret = hashlib.sha256(_get_fernet_key_bytes() + b":blind-index").digest()
    return hmac.new(secret, norm.encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt_str(plaintext: Optional[str]) -> Optional[str]:
    """Encrypts plaintext using versioned prefix `enc:v1:<token>`."""
    if plaintext is None:
        return None
    s = str(plaintext)
    if s.startswith(_VERSIONED_PREFIX) or s.startswith(_LEGACY_PREFIX):
        return s
    token = _get_fernet().encrypt(s.encode("utf-8")).decode("utf-8")
    return f"{_VERSIONED_PREFIX}{token}"


def decrypt_str(ciphertext: Optional[str]) -> Optional[str]:
    """
    Decrypts versioned (`enc:v1:`) or legacy (`enc:`) ciphertext using the primary key,
    falling back to ENCRYPTION_KEY_PREVIOUS during key rotation.
    """
    if ciphertext is None:
        return None
    s = str(ciphertext)
    if s.startswith(_VERSIONED_PREFIX):
        raw_token = s[len(_VERSIONED_PREFIX):].encode("utf-8")
    elif s.startswith(_LEGACY_PREFIX):
        raw_token = s[len(_LEGACY_PREFIX):].encode("utf-8")
    else:
        return s

    for fernet_inst in [_get_fernet(), *_get_previous_fernet_instances()]:
        try:
            return fernet_inst.decrypt(raw_token).decode("utf-8")
        except InvalidToken:
            continue
    logger.warning("Failed decrypting column value with active and previous encryption keys.")
    return ""


def rotate_encrypted_value(ciphertext: Optional[str]) -> Optional[str]:
    """Re-encrypts a legacy or previous-key ciphertext under the current active `enc:v1:` key."""
    if ciphertext is None:
        return None
    plain = decrypt_str(ciphertext)
    if plain is None:
        return None
    token = _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")
    return f"{_VERSIONED_PREFIX}{token}"


def mask_email(email: Optional[str]) -> str:
    """Masks an email address for safe diagnostic logs (e.g. a***@gmail.com)."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    prefix = local[0] if local else "*"
    return f"{prefix}***@{domain}"


class EncryptedString(TypeDecorator):
    """Transparently AES-encrypts String columns at rest in SQLite/PostgreSQL."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        return encrypt_str(str(value))

    def process_result_value(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        return decrypt_str(str(value))


class EncryptedText(TypeDecorator):
    """Transparently AES-encrypts large Text columns at rest (e.g., skills.md markdown)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        return encrypt_str(str(value))

    def process_result_value(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        return decrypt_str(str(value))


class EncryptedJSON(TypeDecorator):
    """Transparently serializes JSON and AES-encrypts it at rest (OAuth tokens, parsed skills)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        serialized = json.dumps(value, ensure_ascii=False)
        return encrypt_str(serialized)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        decrypted = decrypt_str(str(value))
        if not decrypted:
            return {}
        try:
            return json.loads(decrypted)
        except Exception:
            return {}
