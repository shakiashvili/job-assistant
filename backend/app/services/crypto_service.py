import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, Text
from sqlalchemy.types import TypeDecorator

from ..config import DATA_DIR, _is_prod, reload_env_files

logger = logging.getLogger(__name__)

_KEY_FILE: Path = DATA_DIR / ".fernet.key"
_BLIND_KEY_FILE: Path = DATA_DIR / ".blind_index.key"
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


def _get_blind_index_key_bytes() -> bytes:
    """
    Loads the dedicated HMAC blind-index key completely decoupled from ENCRYPTION_KEY.
    Rotating ENCRYPTION_KEY must NEVER invalidate existing email_hash lookups.
    - In production (_is_prod=True): requires BLIND_INDEX_KEY in environment variables.
    - In local dev/test: reads BLIND_INDEX_KEY or persists a dedicated DATA_DIR/.blind_index.key.
    """
    reload_env_files()
    env_key = os.getenv("BLIND_INDEX_KEY", "").strip()
    if env_key:
        return env_key.encode("utf-8")

    if _is_prod:
        raise RuntimeError(
            "FATAL SECURITY ERROR: BLIND_INDEX_KEY environment variable is required in production "
            "and must remain independent of ENCRYPTION_KEY."
        )

    if _BLIND_KEY_FILE.exists():
        raw = _BLIND_KEY_FILE.read_bytes().strip()
        if raw:
            return raw

    generated = secrets.token_urlsafe(48).encode("utf-8")
    try:
        _BLIND_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BLIND_KEY_FILE.write_bytes(generated)
    except Exception as e:
        logger.warning(f"Could not persist local blind-index key file: {e}")
    return generated


def _compute_blind_hmac(norm_value: str, key_material: bytes) -> str:
    secret = hashlib.sha256(key_material + b":blind-index").digest()
    return hmac.new(secret, norm_value.encode("utf-8"), hashlib.sha256).hexdigest()


def blind_index(value: Optional[str]) -> str:
    """Computes a keyed HMAC-SHA256 blind index using the dedicated BLIND_INDEX_KEY."""
    norm = (value or "").strip().lower()
    return _compute_blind_hmac(norm, _get_blind_index_key_bytes())


def blind_index_candidates(value: Optional[str]) -> List[str]:
    """
    Returns ordered active + BLIND_INDEX_KEY_PREVIOUS HMAC digests for zero-downtime
    blind-index key rotation prior to completing reindex_all_blind_indices().
    """
    norm = (value or "").strip().lower()
    active = _compute_blind_hmac(norm, _get_blind_index_key_bytes())
    hashes: List[str] = [active]
    prev_raw = os.getenv("BLIND_INDEX_KEY_PREVIOUS", "").strip()
    if prev_raw:
        for part in prev_raw.split(","):
            clean_part = part.strip()
            if clean_part:
                h = _compute_blind_hmac(norm, clean_part.encode("utf-8"))
                if h not in hashes:
                    hashes.append(h)
    return hashes


def reindex_all_blind_indices(session: Any) -> Dict[str, int]:
    """
    Explicitly recomputes User.email_hash and UserOTP.email_hash under the current active BLIND_INDEX_KEY
    by decrypting raw ciphertext columns cleanly (skipping any row unreadable by active+previous keys
    instead of corrupting hashes with empty digests).
    """
    from sqlalchemy import text

    updated_users = 0
    updated_otps = 0
    skipped_unreadable = 0
    conn = session.connection()

    for row in conn.execute(text("SELECT id, email, email_hash FROM users")).fetchall():
        rid, raw_email, cur_hash = row[0], row[1], row[2]
        try:
            plain = decrypt_str(raw_email, raise_on_error=True)
        except ValueError:
            skipped_unreadable += 1
            continue
        if not plain or not plain.strip():
            skipped_unreadable += 1
            continue
        new_hash = blind_index(plain)
        if new_hash != cur_hash:
            conn.execute(
                text("UPDATE users SET email_hash = :h WHERE id = :id"),
                {"h": new_hash, "id": rid},
            )
            updated_users += 1

    for row in conn.execute(text("SELECT id, email, email_hash FROM user_otps")).fetchall():
        rid, raw_email, cur_hash = row[0], row[1], row[2]
        try:
            plain = decrypt_str(raw_email, raise_on_error=True)
        except ValueError:
            skipped_unreadable += 1
            continue
        if not plain or not plain.strip():
            skipped_unreadable += 1
            continue
        new_hash = blind_index(plain)
        if new_hash != cur_hash:
            conn.execute(
                text("UPDATE user_otps SET email_hash = :h WHERE id = :id"),
                {"h": new_hash, "id": rid},
            )
            updated_otps += 1

    if updated_users or updated_otps:
        session.commit()
    return {
        "users_reindexed": updated_users,
        "otps_reindexed": updated_otps,
        "skipped_unreadable": skipped_unreadable,
    }


def encrypt_str(plaintext: Optional[str]) -> Optional[str]:
    """Encrypts plaintext unconditionally using versioned prefix `enc:v1:<token>`."""
    if plaintext is None:
        return None
    s = str(plaintext)
    token = _get_fernet().encrypt(s.encode("utf-8")).decode("utf-8")
    return f"{_VERSIONED_PREFIX}{token}"


def decrypt_str(ciphertext: Optional[str], *, raise_on_error: bool = False) -> Optional[str]:
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
    if raise_on_error:
        raise ValueError("Failed decrypting ciphertext with active and previous encryption keys.")
    logger.warning("Failed decrypting column value with active and previous encryption keys.")
    return ""


def rotate_encrypted_value(ciphertext: Optional[str]) -> Optional[str]:
    """Re-encrypts a legacy or previous-key ciphertext under the current active `enc:v1:` key cleanly without silent wipes."""
    if ciphertext is None:
        return None
    plain = decrypt_str(ciphertext, raise_on_error=True)
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


if __name__ == "__main__":
    import argparse
    from sqlmodel import Session as _Session
    from ..db.database import engine as _engine

    parser = argparse.ArgumentParser(description="TalentFlow encryption & blind-index key maintenance CLI")
    parser.add_argument("--reindex", action="store_true", help="Recompute User & UserOTP email_hash values with current BLIND_INDEX_KEY")
    args = parser.parse_args()
    if args.reindex:
        with _Session(_engine) as _sess:
            res = reindex_all_blind_indices(_sess)
        print(f"Blind index reindexing complete: {res}")
