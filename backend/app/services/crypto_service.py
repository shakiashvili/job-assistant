import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, Text
from sqlalchemy.types import TypeDecorator

from ..config import DATA_DIR, reload_env_files

logger = logging.getLogger(__name__)

_KEY_FILE: Path = DATA_DIR / ".fernet.key"
_PREFIX = "enc:"


def _get_fernet_key_bytes() -> bytes:
    """Loads or generates the local 256-bit Fernet symmetric encryption key (never committed to Git)."""
    reload_env_files()
    env_key = os.getenv("ENCRYPTION_KEY", "").strip()
    if env_key:
        try:
            Fernet(env_key.encode("utf-8"))
            return env_key.encode("utf-8")
        except Exception:
            # Derive deterministic Fernet key from arbitrary ENCRYPTION_KEY string
            digest = hashlib.sha256(env_key.encode("utf-8")).digest()
            return base64.urlsafe_b64encode(digest)

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


def _get_fernet() -> Fernet:
    return Fernet(_get_fernet_key_bytes())


def blind_index(value: Optional[str]) -> str:
    """Computes a keyed HMAC-SHA256 blind index for exact-match SQL lookups without storing plaintext."""
    norm = (value or "").strip().lower()
    secret = hashlib.sha256(_get_fernet_key_bytes() + b":blind-index").digest()
    return hmac.new(secret, norm.encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt_str(plaintext: Optional[str]) -> Optional[str]:
    if plaintext is None:
        return None
    s = str(plaintext)
    if s.startswith(_PREFIX):
        return s
    token = _get_fernet().encrypt(s.encode("utf-8")).decode("utf-8")
    return f"{_PREFIX}{token}"


def decrypt_str(ciphertext: Optional[str]) -> Optional[str]:
    if ciphertext is None:
        return None
    s = str(ciphertext)
    if not s.startswith(_PREFIX):
        return s
    raw_token = s[len(_PREFIX):].encode("utf-8")
    try:
        return _get_fernet().decrypt(raw_token).decode("utf-8")
    except InvalidToken:
        logger.warning("Failed decrypting column value with current encryption key.")
        return ""


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
